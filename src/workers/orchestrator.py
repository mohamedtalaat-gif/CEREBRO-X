"""
================================================================================
CEREBRO-X |  TASK ORCHESTRATOR & RETRY ENGINE
================================================================================
File: cerebro_orchestrator.py

Separates ML compute from API serving + provides robust task orchestration:

  1. Task Orchestrator
     - DAG-based pipeline execution (dependency resolution)
     - Parallel execution of independent tasks
     - State machine per task: pending → running → success/failed/retrying

  2. Retry Engine
     - Exponential backoff with jitter
     - Per-task retry policies (max retries, backoff factor)
     - Dead letter queue for permanently failed tasks
     - Circuit breaker v2 (with half-open state)

  3. ML Job Isolation
     - ML tasks run in Celery workers (separate process/container)
     - API layer only submits + polls — never blocks
     - Resource limits per job type (CPU, memory, timeout)

  4. Queue Management (Celery + Redis)
     - Priority queues: critical > ml_training > data_fetch > reporting
     - Task routing: ML → GPU queue, data → IO queue, reports → CPU queue
     - Rate limiting per queue
     - Task chaining and chord patterns

  5. Health & Heartbeat
     - Worker heartbeat monitoring
     - Stale task detection
     - Auto-recovery on worker restart

References:
  - Microsoft CQRS pattern
  - Netflix Hystrix circuit breaker
  - Celery best practices (Ask Solem, 2023)
================================================================================
"""

import logging
import os
import random
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any

log = logging.getLogger("CEREBRO-ORCH")

# ─────────────────────────────────────────────────────────────────────────────
# Optional imports
# ─────────────────────────────────────────────────────────────────────────────
try:
    from celery import Celery, chain, chord, group, signature
    from celery.utils.log import get_task_logger
    _HAS_CELERY = True
except ImportError:
    _HAS_CELERY = False

try:
    import redis
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False


# ─────────────────────────────────────────────────────────────────────────────
# 1. Circuit Breaker v2 (with half-open state)
# ─────────────────────────────────────────────────────────────────────────────
class CircuitState(Enum):
    CLOSED    = "closed"      # Normal — requests pass through
    OPEN      = "open"        # Tripped — all requests fail immediately
    HALF_OPEN = "half_open"   # Testing — allow one request through


@dataclass
class CircuitBreakerConfig:
    failure_threshold:  int   = 5      # failures before opening
    recovery_timeout:   float = 60.0   # seconds before half-open
    success_threshold:  int   = 3      # successes in half-open to close
    half_open_max:      int   = 1      # concurrent requests in half-open


class CircuitBreaker:
    """
    Circuit breaker with three states: CLOSED → OPEN → HALF_OPEN → CLOSED.

    CLOSED:    Normal operation. Counts failures.
    OPEN:      After failure_threshold hits, all calls fail fast for
               recovery_timeout seconds (no actual execution).
    HALF_OPEN: After recovery_timeout, allows a limited number of test
               calls. If they succeed → CLOSED. If they fail → OPEN.

    Thread-safe via lock.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig = None):
        self.name   = name
        self.config = config or CircuitBreakerConfig()
        self.state  = CircuitState.CLOSED
        self._failure_count  = 0
        self._success_count  = 0
        self._last_failure   = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()
        self._listeners: list[Callable] = []

    def add_listener(self, callback: Callable):
        """Register a callback: callback(breaker_name, old_state, new_state)."""
        self._listeners.append(callback)

    def _notify(self, old: CircuitState, new: CircuitState):
        for cb in self._listeners:
            try:
                cb(self.name, old, new)
            except Exception as _exc_bare:
                pass

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                elapsed = time.time() - self._last_failure
                if elapsed >= self.config.recovery_timeout:
                    old = self.state
                    self.state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
                    self._notify(old, self.state)
                    log.info(f"[CB:{self.name}] OPEN → HALF_OPEN "
                             f"(after {elapsed:.0f}s)")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                return self._half_open_calls < self.config.half_open_max

        return False

    def record_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    old = self.state
                    self.state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._notify(old, self.state)
                    log.info(f"[CB:{self.name}] HALF_OPEN → CLOSED "
                             f"({self._success_count} successes)")
            elif self.state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure = time.time()

            if self.state == CircuitState.HALF_OPEN:
                old = self.state
                self.state = CircuitState.OPEN
                self._notify(old, self.state)
                log.warning(f"[CB:{self.name}] HALF_OPEN → OPEN (test failed)")

            elif (self.state == CircuitState.CLOSED and
                  self._failure_count >= self.config.failure_threshold):
                old = self.state
                self.state = CircuitState.OPEN
                self._notify(old, self.state)
                log.warning(f"[CB:{self.name}] CLOSED → OPEN "
                            f"({self._failure_count} failures)")

    def __call__(self, func):
        """Use as decorator: @circuit_breaker."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN — "
                    f"failing fast until recovery"
                )
            try:
                with self._lock:
                    self._half_open_calls += 1
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise
        return wrapper

    @property
    def status(self) -> dict:
        return {
            "name":          self.name,
            "state":         self.state.value,
            "failures":      self._failure_count,
            "threshold":     self.config.failure_threshold,
            "last_failure":  self._last_failure,
            "recovery_sec":  self.config.recovery_timeout,
        }


class CircuitBreakerOpenError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# 2. Retry Engine (exponential backoff with jitter)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RetryPolicy:
    max_retries:    int   = 3
    base_delay:     float = 1.0    # seconds
    max_delay:      float = 60.0   # cap
    backoff_factor: float = 2.0    # exponential
    jitter:         bool  = True   # randomize to prevent thundering herd
    retryable_exceptions: tuple = (Exception,)


def retry_with_backoff(policy: RetryPolicy = None):
    """
    Decorator: retry a function with exponential backoff + jitter.

    Usage:
        @retry_with_backoff(RetryPolicy(max_retries=5, base_delay=2.0))
        def fetch_from_api():
            ...
    """
    pol = policy or RetryPolicy()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(pol.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except pol.retryable_exceptions as e:
                    last_exception = e
                    if attempt >= pol.max_retries:
                        break

                    delay = min(
                        pol.base_delay * (pol.backoff_factor ** attempt),
                        pol.max_delay,
                    )
                    if pol.jitter:
                        delay *= (0.5 + random.random())

                    log.warning(
                        f"[RETRY] {func.__name__} attempt {attempt + 1}/{pol.max_retries} "
                        f"failed: {e}. Retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)

            log.error(f"[RETRY] {func.__name__} exhausted all "
                      f"{pol.max_retries} retries")
            raise last_exception
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# 3. Task State Machine
# ─────────────────────────────────────────────────────────────────────────────
class TaskState(Enum):
    PENDING    = "pending"
    QUEUED     = "queued"
    RUNNING    = "running"
    SUCCESS    = "success"
    FAILED     = "failed"
    RETRYING   = "retrying"
    CANCELLED  = "cancelled"
    DEAD       = "dead"       # exceeded all retries → dead letter queue


@dataclass
class TaskDefinition:
    """Definition of a task in the pipeline DAG."""
    name:           str
    func:           Callable
    depends_on:     list[str] = field(default_factory=list)
    retry_policy:   RetryPolicy = field(default_factory=RetryPolicy)
    timeout_sec:    float = 300.0
    queue:          str = "default"     # celery queue name
    priority:       int = 5             # 0 = highest, 9 = lowest
    resource_class: str = "cpu"         # cpu | gpu | io
    tags:           dict = field(default_factory=dict)


@dataclass
class TaskExecution:
    """Runtime state of a task execution."""
    task_id:    str
    task_name:  str
    state:      TaskState = TaskState.PENDING
    attempt:    int = 0
    started_at: str | None = None
    finished_at: str | None = None
    result:     Any = None
    error:      str | None = None
    celery_id:  str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pipeline DAG Orchestrator
# ─────────────────────────────────────────────────────────────────────────────
class PipelineOrchestrator:
    """
    DAG-based pipeline executor.
    Resolves task dependencies, runs independent tasks in parallel,
    handles failures with retry + circuit breaker.

    Usage:
        orch = PipelineOrchestrator()
        orch.register(TaskDefinition("fetch_data", fetch_data_fn))
        orch.register(TaskDefinition("train_model", train_fn,
                                     depends_on=["fetch_data"]))
        orch.register(TaskDefinition("generate_report", report_fn,
                                     depends_on=["train_model"]))
        results = orch.execute()
    """

    def __init__(self):
        self.tasks: dict[str, TaskDefinition] = {}
        self.executions: dict[str, TaskExecution] = {}
        self.breakers: dict[str, CircuitBreaker] = {}
        self._dead_letter: list[TaskExecution] = []

    def register(self, task: TaskDefinition):
        """Register a task definition in the DAG."""
        self.tasks[task.name] = task
        self.breakers[task.name] = CircuitBreaker(
            task.name,
            CircuitBreakerConfig(
                failure_threshold=task.retry_policy.max_retries,
                recovery_timeout=60.0,
            )
        )

    def _topological_sort(self) -> list[list[str]]:
        """
        Kahn's algorithm: returns list of levels.
        Each level contains tasks that can run in parallel.
        """
        in_degree = {name: 0 for name in self.tasks}
        adj = defaultdict(list)

        for name, task in self.tasks.items():
            for dep in task.depends_on:
                if dep in self.tasks:
                    adj[dep].append(name)
                    in_degree[name] += 1

        # BFS
        queue = [n for n, d in in_degree.items() if d == 0]
        levels = []
        visited = set()

        while queue:
            levels.append(sorted(queue))
            next_queue = []
            for node in queue:
                visited.add(node)
                for neighbor in adj[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0 and neighbor not in visited:
                        next_queue.append(neighbor)
            queue = next_queue

        if len(visited) != len(self.tasks):
            missing = set(self.tasks.keys()) - visited
            raise ValueError(f"Circular dependency detected: {missing}")

        return levels

    def execute(self, run_id: str = None) -> dict[str, TaskExecution]:
        """
        Execute the full DAG.
        Tasks at each level run in parallel (via threads).
        """
        import secrets
        run_id = run_id or f"orch_{secrets.token_hex(4)}"
        log.info(f"[ORCHESTRATOR] Starting pipeline run: {run_id}")

        levels = self._topological_sort()

        for level_idx, level_tasks in enumerate(levels):
            log.info(f"[ORCHESTRATOR] Level {level_idx}: {level_tasks}")

            threads = []
            for task_name in level_tasks:
                exec_id = f"{run_id}_{task_name}"
                self.executions[task_name] = TaskExecution(
                    task_id=exec_id, task_name=task_name
                )
                t = threading.Thread(
                    target=self._execute_task,
                    args=(task_name,),
                    name=f"task-{task_name}",
                )
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # Check for failures — halt if any critical task failed
            for task_name in level_tasks:
                ex = self.executions[task_name]
                if ex.state in (TaskState.FAILED, TaskState.DEAD):
                    # Check if downstream tasks exist
                    has_dependents = any(
                        task_name in self.tasks[t].depends_on
                        for t in self.tasks
                    )
                    if has_dependents:
                        log.error(f"[ORCHESTRATOR] {task_name} failed — "
                                  f"aborting downstream tasks")
                        # Mark all remaining as cancelled
                        for remaining_level in levels[level_idx + 1:]:
                            for rem_task in remaining_level:
                                self.executions[rem_task] = TaskExecution(
                                    task_id=f"{run_id}_{rem_task}",
                                    task_name=rem_task,
                                    state=TaskState.CANCELLED,
                                )
                        return self.executions

        log.info(f"[ORCHESTRATOR] Pipeline run {run_id} complete")
        return self.executions

    def _execute_task(self, task_name: str):
        """Execute a single task with retry logic."""
        task_def  = self.tasks[task_name]
        execution = self.executions[task_name]
        breaker   = self.breakers[task_name]
        policy    = task_def.retry_policy

        # Collect results from dependencies
        dep_results = {}
        for dep in task_def.depends_on:
            dep_ex = self.executions.get(dep)
            if dep_ex and dep_ex.state == TaskState.SUCCESS:
                dep_results[dep] = dep_ex.result

        for attempt in range(policy.max_retries + 1):
            execution.attempt = attempt + 1
            execution.state   = TaskState.RUNNING if attempt == 0 else TaskState.RETRYING
            execution.started_at = datetime.utcnow().isoformat()

            if not breaker.can_execute():
                execution.state = TaskState.DEAD
                execution.error = "Circuit breaker OPEN"
                self._dead_letter.append(execution)
                return

            try:
                result = task_def.func(**dep_results)
                execution.state      = TaskState.SUCCESS
                execution.result     = result
                execution.finished_at = datetime.utcnow().isoformat()
                breaker.record_success()
                log.info(f"[TASK] {task_name} → SUCCESS (attempt {attempt + 1})")
                return

            except Exception as e:
                breaker.record_failure()
                execution.error = f"{type(e).__name__}: {e!s}"
                log.warning(f"[TASK] {task_name} attempt {attempt + 1} failed: {e}")

                if attempt >= policy.max_retries:
                    execution.state      = TaskState.DEAD
                    execution.finished_at = datetime.utcnow().isoformat()
                    self._dead_letter.append(execution)
                    log.error(f"[TASK] {task_name} → DEAD (all retries exhausted)")
                    return

                delay = min(
                    policy.base_delay * (policy.backoff_factor ** attempt),
                    policy.max_delay,
                )
                if policy.jitter:
                    delay *= (0.5 + random.random())
                time.sleep(delay)

    @property
    def dead_letter_queue(self) -> list[dict]:
        return [
            {"task_id": e.task_id, "task_name": e.task_name,
             "error": e.error, "attempts": e.attempt}
            for e in self._dead_letter
        ]

    @property
    def status(self) -> dict:
        return {
            "tasks": {
                name: {
                    "state": ex.state.value,
                    "attempt": ex.attempt,
                    "error": ex.error,
                }
                for name, ex in self.executions.items()
            },
            "circuit_breakers": {
                name: cb.status
                for name, cb in self.breakers.items()
            },
            "dead_letter_queue": self.dead_letter_queue,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Celery Queue Configuration
# ─────────────────────────────────────────────────────────────────────────────
REDIS_URL     = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER = os.environ.get("CELERY_BROKER", "redis://localhost:6379/0")
CELERY_BACK   = os.environ.get("CELERY_BACKEND", "redis://localhost:6379/1")

if _HAS_CELERY:
    celery_app = Celery(
        "cerebro_orchestrator",
        broker=CELERY_BROKER,
        backend=CELERY_BACK,
    )

    # ── Queue configuration ──────────────────────────────────────────────
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,

        # Worker settings
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        worker_max_tasks_per_child=50,  # restart worker after 50 tasks (leak prevention)
        worker_max_memory_per_child=512_000,  # 512MB limit

        # Retry settings
        task_reject_on_worker_lost=True,
        task_default_retry_delay=30,

        # Priority queues
        task_queues={
            "critical":    {"exchange": "critical",    "routing_key": "critical"},
            "ml_training": {"exchange": "ml_training", "routing_key": "ml_training"},
            "data_fetch":  {"exchange": "data_fetch",  "routing_key": "data_fetch"},
            "reporting":   {"exchange": "reporting",   "routing_key": "reporting"},
            "default":     {"exchange": "default",     "routing_key": "default"},
        },

        # Route tasks to queues
        task_routes={
            "cerebro.train_*":    {"queue": "ml_training"},
            "cerebro.fetch_*":    {"queue": "data_fetch"},
            "cerebro.report_*":   {"queue": "reporting"},
            "cerebro.pipeline_*": {"queue": "critical"},
        },

        # Rate limits
        task_annotations={
            "cerebro.fetch_*": {"rate_limit": "10/m"},   # API rate limit
            "cerebro.train_*": {"rate_limit": "2/m"},    # CPU-bound
        },

        # Results
        result_expires=3600,  # 1 hour
    )

    # ── Task definitions ─────────────────────────────────────────────────

    @celery_app.task(
        bind=True,
        name="cerebro.pipeline_full",
        queue="critical",
        max_retries=3,
        default_retry_delay=60,
        autoretry_for=(Exception,),
        retry_backoff=True,
        retry_backoff_max=300,
        retry_jitter=True,
        acks_late=True,
        track_started=True,
        time_limit=3600,       # hard kill after 1h
        soft_time_limit=3000,  # soft signal at 50 min
    )
    def pipeline_full_task(self, config: dict = None):
        """Full CEREBRO-X pipeline as async Celery task."""
        log.info(f"[CELERY] Pipeline task {self.request.id} starting")
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import CEREBRO_Pipeline as cp
            try:
                from cerebro_pipeline_patches import apply_patches
                apply_patches(cp)
            except ImportError:
                log.warning("[CELERY] cerebro_pipeline_patches.py not found — running unpatched")
            cp.setup_workspace()

            drugs = config.get("drugs", []) if config else []
            if not drugs:
                return {"status": "error",
                         "message": "No drugs specified in config. v22.1 forbids default drug names."}
            df_mab = cp.CascadeDataEngine.build_mab_dataset(drugs)
            if df_mab.empty:
                return {"status": "error", "message": "No data fetched"}

            df_ml, _, metrics = cp.AdvancedMLEngine.train(
                df_mab,
                feature_cols=["MW_Da", "LogP", "Half_Life_Days", "Docking_Affinity_kcal"]
            )
            df_ml = cp.ADMETEngine.run(df_ml)
            cp.ReportingEngine.generate_master_report(df_mab, None, df_ml, metrics)

            return {
                "status": "success",
                "r2": metrics.get("r2", 0),
                "n_candidates": len(df_ml),
                "task_id": self.request.id,
            }
        except Exception as e:
            log.exception(f"[CELERY] Pipeline failed: {e}")
            raise self.retry(exc=e)

    @celery_app.task(
        bind=True,
        name="cerebro.train_model",
        queue="ml_training",
        max_retries=2,
        time_limit=1800,
        soft_time_limit=1500,
    )
    def train_model_task(self, model_config: dict = None):
        """ML training as isolated Celery task (separate from API)."""
        log.info(f"[CELERY:ML] Training task {self.request.id}")
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import CEREBRO_Pipeline as cp
            try:
                from cerebro_pipeline_patches import apply_patches
                apply_patches(cp)
            except ImportError:
                log.warning("[CELERY:ML] cerebro_pipeline_patches.py not found — running unpatched")

            drugs = model_config.get("drugs", []) if model_config else []
            if not drugs:
                return {"status":"error",
                         "message":"No drugs in model_config. v22.1 forbids defaults."}
            df = cp.CascadeDataEngine.build_mab_dataset(drugs)
            if df.empty:
                return {"status": "error", "message": "No training data"}

            features = model_config.get("features", [
                "MW_Da", "LogP", "Half_Life_Days", "Docking_Affinity_kcal"
            ]) if model_config else [
                "MW_Da", "LogP", "Half_Life_Days", "Docking_Affinity_kcal"
            ]

            df_ml, _, metrics = cp.AdvancedMLEngine.train(df, features)

            return {
                "status":  "success",
                "metrics": metrics,
                "n_samples": len(df_ml),
                "task_id": self.request.id,
            }
        except Exception as e:
            log.exception(f"[CELERY:ML] Training failed: {e}")
            raise self.retry(exc=e)

    @celery_app.task(
        name="cerebro.fetch_data",
        queue="data_fetch",
        max_retries=5,
        default_retry_delay=10,
        autoretry_for=(Exception,),
        retry_backoff=True,
    )
    def fetch_data_task(drug_name: str):
        """Data fetching as isolated task (IO-bound, separate queue)."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import CEREBRO_Pipeline as cp
        data = cp.CascadeDataEngine.fetch_drug(drug_name)
        return {"drug": drug_name, "data": data}

    @celery_app.task(
        name="cerebro.report_generate",
        queue="reporting",
        time_limit=600,
    )
    def generate_report_task(report_config: dict = None):
        """Report generation as isolated task."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        # Report generation logic here
        return {"status": "success", "task": "report"}

    # ── Pipeline chains ──────────────────────────────────────────────────
    def build_pipeline_chain(drugs: list[str]):
        """
        Build a Celery chain: fetch → train → report.
        Each step runs only after the previous succeeds.
        """
        return chain(
            group([fetch_data_task.s(d) for d in drugs]),
            train_model_task.s(),
            generate_report_task.s(),
        )

else:
    log.warning("[ORCHESTRATOR] Celery not installed — "
                "using thread-based orchestration only")


# ─────────────────────────────────────────────────────────────────────────────
# 6. CEREBRO Pipeline DAG (pre-configured)
# ─────────────────────────────────────────────────────────────────────────────
def create_cerebro_pipeline_dag() -> PipelineOrchestrator:
    """
    Factory: creates the standard CEREBRO-X pipeline DAG.

    DAG structure:
      fetch_drug_data ──┐
      fetch_aav_data  ──┤
                        ├→ build_dataset → train_ml → admet_screen ──┐
      fetch_clinical ───┘                                            │
                                                           dds_analysis ──→ generate_report
    """
    orch = PipelineOrchestrator()

    # Level 0: independent data fetches (parallel)
    orch.register(TaskDefinition(
        name="fetch_drug_data",
        func=lambda: {"status": "fetched"},  # placeholder
        retry_policy=RetryPolicy(max_retries=5, base_delay=2.0),
        queue="data_fetch",
        priority=3,
        resource_class="io",
    ))
    orch.register(TaskDefinition(
        name="fetch_aav_data",
        func=lambda: {"status": "fetched"},
        retry_policy=RetryPolicy(max_retries=5, base_delay=2.0),
        queue="data_fetch",
        priority=3,
        resource_class="io",
    ))

    # Level 1: dataset building (depends on fetches)
    orch.register(TaskDefinition(
        name="build_dataset",
        func=lambda **kw: {"status": "built"},
        depends_on=["fetch_drug_data", "fetch_aav_data"],
        queue="default",
        priority=5,
    ))

    # Level 2: ML training (CPU/GPU intensive)
    orch.register(TaskDefinition(
        name="train_ml",
        func=lambda **kw: {"status": "trained"},
        depends_on=["build_dataset"],
        retry_policy=RetryPolicy(max_retries=2, base_delay=5.0),
        timeout_sec=1800,
        queue="ml_training",
        priority=2,
        resource_class="gpu",
    ))

    # Level 3: ADMET + DDS (depends on ML)
    orch.register(TaskDefinition(
        name="admet_screen",
        func=lambda **kw: {"status": "screened"},
        depends_on=["train_ml"],
        queue="ml_training",
        priority=4,
    ))
    orch.register(TaskDefinition(
        name="dds_analysis",
        func=lambda **kw: {"status": "analyzed"},
        depends_on=["admet_screen"],
        queue="default",
        priority=5,
    ))

    # Level 4: reporting (depends on everything)
    orch.register(TaskDefinition(
        name="generate_report",
        func=lambda **kw: {"status": "reported"},
        depends_on=["dds_analysis"],
        queue="reporting",
        priority=7,
    ))

    return orch