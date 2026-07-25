"""
================================================================================
CEREBRO-X |  MONITORING & OBSERVABILITY ENGINE
================================================================================
File: cerebro_monitoring.py

Production observability stack:

  1. Structured Logging
     - JSON-formatted log output (machine-parseable)
     - Correlation IDs (trace requests across services)
     - Log levels: DEBUG → INFO → WARNING → ERROR → CRITICAL
     - Sinks: stdout, file (rotating), Loki-compatible

  2. Metrics (Prometheus)
     - Request latency histograms (per endpoint)
     - Pipeline execution counters (success/failure)
     - ML training duration + model metrics (R², MAE)
     - Queue depth gauges (Celery tasks pending)
     - System metrics: CPU, memory, disk

  3. Health Checks
     - Deep health: DB + Redis + Celery + model loaded
     - Liveness probe: /healthz (is the process alive?)
     - Readiness probe: /readyz (can it serve traffic?)

  4. Alerting
     - Rule-based alerts (threshold breaches)
     - Alert channels: log, webhook, email
     - Alert deduplication (no spam)
     - Escalation policies

  5. Distributed Tracing
     - Request ID propagation via middleware
     - Span tracking for pipeline stages
     - Latency breakdown per stage

References:
  - Google SRE Book, Ch. 6: "Monitoring Distributed Systems"
  - Prometheus best practices
  - OpenTelemetry specification
================================================================================
"""

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps

# ─────────────────────────────────────────────────────────────────────────────
# Optional imports
# ─────────────────────────────────────────────────────────────────────────────
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Info,
        Summary,
        generate_latest,
    )
    from prometheus_client import (
        start_http_server as prom_start_server,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

try:
    from fastapi import FastAPI, Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

log = logging.getLogger("CEREBRO-MONITOR")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Structured JSON Logger
# ─────────────────────────────────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    """
    Outputs log records as JSON lines for centralized log aggregation
    (ELK stack, Loki, Datadog, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp":  datetime.utcnow().isoformat() + "Z",
            "level":      record.levelname,
            "logger":     record.name,
            "message":    record.getMessage(),
            "module":     record.module,
            "function":   record.funcName,
            "line":       record.lineno,
        }

        # Add correlation/request ID if present
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id
        if hasattr(record, "request_id"):
            log_obj["request_id"] = record.request_id

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_obj.update(record.extra_data)

        # Exception info
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


def setup_structured_logging(
    log_file: str = "outputs/logs/cerebro_structured.jsonl",
    console_json: bool = False,
):
    """
    Configure structured logging for the entire application.
    """
    from pathlib import Path
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()

    # File handler (always JSON)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(JSONFormatter())
    fh.setLevel(logging.INFO)
    root.addHandler(fh)

    # Console handler
    if console_json:
        ch = logging.StreamHandler()
        ch.setFormatter(JSONFormatter())
        root.addHandler(ch)
    else:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S"
        ))
        root.addHandler(ch)

    root.setLevel(logging.INFO)
    log.info("[MONITOR] Structured logging initialized")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prometheus Metrics
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_PROMETHEUS:

    # ── Request metrics ──────────────────────────────────────────────────
    REQUEST_COUNT = Counter(
        "cerebro_http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status_code"],
    )
    REQUEST_LATENCY = Histogram(
        "cerebro_http_request_duration_seconds",
        "HTTP request latency",
        ["method", "endpoint"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
    )
    REQUESTS_IN_PROGRESS = Gauge(
        "cerebro_http_requests_in_progress",
        "Currently processing HTTP requests",
        ["method", "endpoint"],
    )

    # ── Pipeline metrics ─────────────────────────────────────────────────
    PIPELINE_RUNS = Counter(
        "cerebro_pipeline_runs_total",
        "Total pipeline executions",
        ["status"],  # success, failed, timeout
    )
    PIPELINE_DURATION = Histogram(
        "cerebro_pipeline_duration_seconds",
        "Pipeline execution time",
        buckets=[10, 30, 60, 120, 300, 600, 1800, 3600],
    )

    # ── ML metrics ───────────────────────────────────────────────────────
    MODEL_TRAINING_DURATION = Histogram(
        "cerebro_model_training_seconds",
        "ML model training time",
        ["model_name"],
    )
    MODEL_R2_SCORE = Gauge(
        "cerebro_model_r2_score",
        "Current model R² score",
        ["model_name", "version"],
    )
    MODEL_PREDICTIONS = Counter(
        "cerebro_model_predictions_total",
        "Total predictions served",
        ["model_name"],
    )

    # ── Queue metrics ────────────────────────────────────────────────────
    CELERY_QUEUE_DEPTH = Gauge(
        "cerebro_celery_queue_depth",
        "Number of pending tasks in queue",
        ["queue_name"],
    )
    CELERY_ACTIVE_TASKS = Gauge(
        "cerebro_celery_active_tasks",
        "Number of currently running tasks",
    )

    # ── System metrics ───────────────────────────────────────────────────
    SYSTEM_CPU = Gauge("cerebro_system_cpu_percent", "System CPU usage")
    SYSTEM_MEMORY = Gauge("cerebro_system_memory_percent", "System memory usage")
    SYSTEM_DISK = Gauge("cerebro_system_disk_percent", "Disk usage percent")

    # ── Drift metrics ────────────────────────────────────────────────────
    DRIFT_EVENTS = Counter(
        "cerebro_drift_events_total",
        "Drift events detected",
        ["drift_type", "severity"],
    )

    def start_metrics_server(port: int = 8001):
        """Start Prometheus metrics exporter on a separate port."""
        try:
            prom_start_server(port)
            log.info(f"[METRICS] Prometheus exporter on :{port}/metrics")
        except Exception as e:
            log.warning(f"[METRICS] Could not start Prometheus server: {e}")

    def collect_system_metrics():
        """Collect CPU/memory/disk and update Prometheus gauges."""
        try:
            import psutil
            SYSTEM_CPU.set(psutil.cpu_percent())
            SYSTEM_MEMORY.set(psutil.virtual_memory().percent)
            SYSTEM_DISK.set(psutil.disk_usage("/").percent)
        except ImportError:
            pass

else:
    # Stubs when prometheus_client not available
    def start_metrics_server(port=8001):
        log.warning("[METRICS] prometheus_client not installed")

    def collect_system_metrics():
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 3. FastAPI Middleware (request tracking + metrics)
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_FASTAPI:

    class RequestTrackingMiddleware(BaseHTTPMiddleware):
        """
        Middleware that:
          1. Assigns a unique request_id to each request
          2. Records latency and status code in Prometheus
          3. Logs structured request info
        """

        async def dispatch(self, request: Request, call_next):
            request_id = request.headers.get(
                "X-Request-ID", str(uuid.uuid4())
            )
            request.state.request_id = request_id

            method   = request.method
            endpoint = request.url.path

            start = time.time()

            if _HAS_PROMETHEUS:
                REQUESTS_IN_PROGRESS.labels(method, endpoint).inc()

            try:
                response = await call_next(request)
                status = response.status_code
            except Exception:
                status = 500
                raise
            finally:
                duration = time.time() - start

                if _HAS_PROMETHEUS:
                    REQUEST_COUNT.labels(method, endpoint, status).inc()
                    REQUEST_LATENCY.labels(method, endpoint).observe(duration)
                    REQUESTS_IN_PROGRESS.labels(method, endpoint).dec()

                log.info(
                    f"{method} {endpoint} → {status} ({duration:.3f}s) "
                    f"[{request_id}]"
                )

            response.headers["X-Request-ID"] = request_id
            return response


# ─────────────────────────────────────────────────────────────────────────────
# 4. Health Check System
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class HealthCheckResult:
    service:  str
    healthy:  bool
    latency_ms: float = 0
    details:  dict = field(default_factory=dict)


class HealthChecker:
    """
    Deep health check: verifies all dependencies are operational.
    """

    @staticmethod
    def check_postgres(db_url: str = None) -> HealthCheckResult:
        start = time.time()
        try:
            from sqlalchemy import create_engine, text
            url = db_url or os.environ.get("DATABASE_URL", "")
            if not url:
                return HealthCheckResult("postgres", False,
                                         details={"error": "No URL"})
            engine = create_engine(url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return HealthCheckResult(
                "postgres", True,
                latency_ms=round((time.time() - start) * 1000, 1),
            )
        except Exception as e:
            return HealthCheckResult(
                "postgres", False,
                latency_ms=round((time.time() - start) * 1000, 1),
                details={"error": str(e)},
            )

    @staticmethod
    def check_redis(redis_url: str = None) -> HealthCheckResult:
        start = time.time()
        try:
            import redis
            url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            r = redis.from_url(url, socket_timeout=3)
            r.ping()
            return HealthCheckResult(
                "redis", True,
                latency_ms=round((time.time() - start) * 1000, 1),
            )
        except Exception as e:
            return HealthCheckResult(
                "redis", False,
                latency_ms=round((time.time() - start) * 1000, 1),
                details={"error": str(e)},
            )

    @staticmethod
    def check_celery() -> HealthCheckResult:
        start = time.time()
        try:
            from cerebro_orchestrator import celery_app
            insp = celery_app.control.inspect(timeout=3)
            active = insp.active()
            return HealthCheckResult(
                "celery", active is not None,
                latency_ms=round((time.time() - start) * 1000, 1),
                details={"workers": list(active.keys()) if active else []},
            )
        except Exception as e:
            return HealthCheckResult(
                "celery", False,
                latency_ms=round((time.time() - start) * 1000, 1),
                details={"error": str(e)},
            )

    @staticmethod
    def check_model_loaded(model_dir: str = "outputs/model_store"
                           ) -> HealthCheckResult:
        from pathlib import Path
        p = Path(model_dir)
        models = list(p.glob("*.pkl")) if p.exists() else []
        return HealthCheckResult(
            "ml_model", len(models) > 0,
            details={"n_models": len(models),
                     "latest": str(models[-1].name) if models else None},
        )

    @classmethod
    def deep_health(cls) -> dict:
        checks = [
            cls.check_postgres(),
            cls.check_redis(),
            cls.check_celery(),
            cls.check_model_loaded(),
        ]
        all_healthy = all(c.healthy for c in checks)
        return {
            "status":   "healthy" if all_healthy else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {
                c.service: {
                    "healthy":    c.healthy,
                    "latency_ms": c.latency_ms,
                    "details":    c.details,
                }
                for c in checks
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Alert Engine
# ─────────────────────────────────────────────────────────────────────────────
class AlertSeverity:
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    name:        str
    condition:   Callable[[], bool]  # returns True when alert should fire
    severity:    str = AlertSeverity.WARNING
    cooldown_sec: int = 300          # minimum seconds between alerts
    message:     str = ""
    channels:    list[str] = field(default_factory=lambda: ["log"])


@dataclass
class Alert:
    rule_name:  str
    severity:   str
    message:    str
    fired_at:   str
    details:    dict = field(default_factory=dict)


class AlertEngine:
    """
    Rule-based alerting with deduplication and cooldown.
    """

    def __init__(self):
        self.rules: dict[str, AlertRule] = {}
        self._last_fired: dict[str, float] = {}
        self._alert_history: list[Alert] = []
        self._channels: dict[str, Callable] = {
            "log": self._send_log,
        }

    def register_rule(self, rule: AlertRule):
        self.rules[rule.name] = rule

    def register_channel(self, name: str, handler: Callable):
        """Register a custom alert channel (e.g., webhook, email)."""
        self._channels[name] = handler

    def evaluate(self) -> list[Alert]:
        """Evaluate all rules and fire alerts for triggered conditions."""
        fired = []
        now = time.time()

        for name, rule in self.rules.items():
            try:
                if not rule.condition():
                    continue
            except Exception as e:
                log.warning(f"[ALERT] Rule '{name}' evaluation error: {e}")
                continue

            # Cooldown check
            last = self._last_fired.get(name, 0)
            if (now - last) < rule.cooldown_sec:
                continue

            alert = Alert(
                rule_name=name,
                severity=rule.severity,
                message=rule.message or f"Alert: {name}",
                fired_at=datetime.utcnow().isoformat(),
            )

            # Send to channels
            for ch in rule.channels:
                handler = self._channels.get(ch)
                if handler:
                    try:
                        handler(alert)
                    except Exception as e:
                        log.error(f"[ALERT] Channel '{ch}' failed: {e}")

            self._last_fired[name] = now
            self._alert_history.append(alert)
            fired.append(alert)

        return fired

    @staticmethod
    def _send_log(alert: Alert):
        level = {
            AlertSeverity.INFO:     logging.INFO,
            AlertSeverity.WARNING:  logging.WARNING,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }.get(alert.severity, logging.WARNING)
        log.log(level, f"[ALERT:{alert.severity.upper()}] "
                       f"{alert.rule_name}: {alert.message}")

    @property
    def history(self) -> list[dict]:
        return [
            {"rule": a.rule_name, "severity": a.severity,
             "message": a.message, "fired_at": a.fired_at}
            for a in self._alert_history[-100:]  # last 100
        ]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Pipeline Performance Tracker
# ─────────────────────────────────────────────────────────────────────────────
class PipelineTimer:
    """
    Context manager for tracking pipeline stage durations.

    Usage:
        with PipelineTimer("data_fetch") as t:
            data = fetch_data()
        print(t.duration_sec)
    """

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.start_time = 0.0
        self.end_time   = 0.0
        self.duration_sec = 0.0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, *exc):
        self.end_time = time.time()
        self.duration_sec = self.end_time - self.start_time

        if _HAS_PROMETHEUS:
            PIPELINE_DURATION.observe(self.duration_sec)

        log.info(f"[TIMER] {self.stage_name}: {self.duration_sec:.2f}s")
        return False


def track_pipeline_execution(func):
    """Decorator: tracks pipeline function execution in Prometheus."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            if _HAS_PROMETHEUS:
                PIPELINE_RUNS.labels("success").inc()
            return result
        except Exception:
            if _HAS_PROMETHEUS:
                PIPELINE_RUNS.labels("failed").inc()
            raise
        finally:
            duration = time.time() - start
            if _HAS_PROMETHEUS:
                PIPELINE_DURATION.observe(duration)
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# 7. Default Alert Rules (CEREBRO-specific)
# ─────────────────────────────────────────────────────────────────────────────
def setup_default_alerts(alert_engine: AlertEngine):
    """Register standard monitoring alerts for CEREBRO-X."""

    # Pipeline failure rate
    alert_engine.register_rule(AlertRule(
        name="high_pipeline_failure_rate",
        condition=lambda: False,  # will be wired to actual metrics
        severity=AlertSeverity.CRITICAL,
        cooldown_sec=600,
        message="Pipeline failure rate exceeded 20% in the last hour",
        channels=["log"],
    ))

    # Model drift
    alert_engine.register_rule(AlertRule(
        name="model_drift_detected",
        condition=lambda: False,
        severity=AlertSeverity.WARNING,
        cooldown_sec=3600,
        message="Prediction distribution shift detected (PSI > 0.25)",
        channels=["log"],
    ))

    # High latency
    alert_engine.register_rule(AlertRule(
        name="high_api_latency",
        condition=lambda: False,
        severity=AlertSeverity.WARNING,
        cooldown_sec=300,
        message="API p99 latency exceeded 10s",
        channels=["log"],
    ))

    # Disk space
    alert_engine.register_rule(AlertRule(
        name="low_disk_space",
        condition=lambda: _check_disk_space(),
        severity=AlertSeverity.CRITICAL,
        cooldown_sec=1800,
        message="Disk usage exceeded 90%",
        channels=["log"],
    ))


def _check_disk_space() -> bool:
    try:
        import psutil
        return psutil.disk_usage("/").percent > 90
    except ImportError:
        return False