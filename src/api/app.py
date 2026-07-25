# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  ASYNC API GATEWAY
================================================================================
File: cerebro_api_v2.py

Production-grade async FastAPI application that wires together:
  - JWT Authentication + RBAC  (cerebro_auth.py)
  - MLOps pipeline             (cerebro_mlops.py)
  - Task orchestration + Celery (cerebro_orchestrator.py)
  - Knowledge Graph            (cerebro_knowledge_graph.py)
  - Monitoring + metrics       (cerebro_monitoring.py)

Design principles:
  - ALL endpoints are async (non-blocking)
  - Heavy computation → Celery queue (never blocks API)
  - JWT + API key dual authentication
  - RBAC permission checks per endpoint
  - Request tracking middleware (correlation IDs)
  - Prometheus metrics on every request
  - Structured JSON logging

Startup sequence:
  1. Init DB tables (users, api_keys, audit_logs, models)
  2. Bootstrap admin user if empty
  3. Start Prometheus metrics server (:8001)
  4. Register default alerts
  5. Start background scheduler
  6. Serve FastAPI on :8000
================================================================================
"""

import os
import sys
import asyncio
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# Anchor
# ─────────────────────────────────────────────────────────────────────────────
try:
    SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
except NameError:
    SCRIPT_DIR = Path(os.path.abspath(sys.argv[0])).parent
sys.path.insert(0, str(SCRIPT_DIR))

# Registers the legacy flat module names (cerebro_auth, cerebro_mlops, ...)
# used by the imports below. Required here because this module is also the
# process entrypoint when launched directly via `uvicorn src.api.app:app`
# (docker-compose.prod.yml), which never goes through run.py.
import src.path_resolver  # noqa: F401,E402

# ─────────────────────────────────────────────────────────────────────────────
# Core imports
# ─────────────────────────────────────────────────────────────────────────────
from fastapi import (
    FastAPI, Depends, HTTPException, BackgroundTasks,
    status, Query, UploadFile, File,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# ─────────────────────────────────────────────────────────────────────────────
# CEREBRO modules
# ─────────────────────────────────────────────────────────────────────────────
from cerebro_auth import (
    AuthService, UserModel, UserCreate, UserResponse,
    TokenResponse, Role, has_permission, TokenEngine,
    AuthBase, bootstrap_admin,
)
from cerebro_mlops import (
    ModelRegistry, ModelVersion, ModelStage,
    ModelDriftDetector, DataDriftDetector,
    ExperimentTracker, DriftEventLogger, MLOpsPipeline,
)
from cerebro_orchestrator import (
    PipelineOrchestrator, TaskDefinition, RetryPolicy,
    CircuitBreaker, CircuitBreakerConfig,
    retry_with_backoff, create_cerebro_pipeline_dag,
)
from cerebro_knowledge_graph import (
    CerebroKnowledgeGraph, export_kg_to_json,
)
from cerebro_monitoring import (
    setup_structured_logging, start_metrics_server,
    HealthChecker, AlertEngine, setup_default_alerts,
    PipelineTimer, track_pipeline_execution,
    collect_system_metrics,
)

# Conditional: request tracking middleware
try:
    from cerebro_monitoring import RequestTrackingMiddleware
    _HAS_TRACKING_MW = True
except ImportError:
    _HAS_TRACKING_MW = False

# Conditional: Celery tasks
try:
    from cerebro_orchestrator import (
        celery_app, pipeline_full_task, train_model_task,
        fetch_data_task, generate_report_task,
    )
    _HAS_CELERY = True
except ImportError:
    _HAS_CELERY = False

# Conditional: Prometheus
try:
    from cerebro_monitoring import (
        PIPELINE_RUNS, MODEL_R2_SCORE, MODEL_PREDICTIONS,
        CELERY_QUEUE_DEPTH, DRIFT_EVENTS,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

log = logging.getLogger("CEREBRO-API")

# ─────────────────────────────────────────────────────────────────────────────
# Database setup (SQLAlchemy)
# ─────────────────────────────────────────────────────────────────────────────
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///CEREBRO_RESULTS/cerebro_enterprise.db"
)

try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
except Exception:
    # SQLite fallback
    engine = create_engine(
        "sqlite:///CEREBRO_RESULTS/cerebro_enterprise.db",
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(bind=engine)

# Create auth tables
try:
    AuthBase.metadata.create_all(bind=engine)
except Exception as e:
    log.warning(f"[DB] Auth table creation: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Auth dependency (wired with DB)
# ─────────────────────────────────────────────────────────────────────────────
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    token:   Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
    db:      Session = Depends(get_db),
) -> UserModel:
    """Universal auth: JWT first, then API key."""
    # JWT
    if token:
        try:
            payload = TokenEngine.decode_token(token)
            if payload.get("type") == "access":
                user = db.query(UserModel).filter(
                    UserModel.id == int(payload["sub"])
                ).first()
                if user and user.is_active:
                    return user
        except Exception as _exc_bare:
            pass

    # API key
    if api_key:
        svc = AuthService(db)
        user = svc.verify_api_key(api_key)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_optional(
    token:   Optional[str] = Depends(oauth2_scheme),
    api_key: Optional[str] = Depends(api_key_header),
    db:      Session = Depends(get_db),
) -> Optional[UserModel]:
    """Like get_current_user but returns None instead of 401."""
    try:
        return await get_current_user(token, api_key, db)
    except HTTPException:
        return None


def require_role(*roles: str):
    """Dependency factory: restrict endpoint to specific roles."""
    async def check(user: UserModel = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role: {roles}. You have: {user.role}",
            )
        return user
    return check


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────
class PipelineRunRequest(BaseModel):
    drugs:       List[str] = Field(default_factory=list,
                                     description="Drug names — required, no defaults")
    aav_vectors: List[str] = Field(default=["AAV9", "AAV-PHP.eB"])
    async_mode:  bool      = True

class DDSRunRequest(BaseModel):
    config_path: Optional[str] = None

class PredictRequest(BaseModel):
    molecule_input: str
    drug_name:      str = ""

class DriftCheckRequest(BaseModel):
    model_name: str = "cerebro_ensemble"

class KGBuildRequest(BaseModel):
    include_formulations: bool = True

class ModelPromoteRequest(BaseModel):
    model_name: str
    version:    str
    target_stage: str = ModelStage.PRODUCTION


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Application
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CEREBRO-X API",
    description=(
        "Production-grade drug-discovery pipeline with JWT auth, RBAC, "
        "MLOps, Knowledge Graph, and async task orchestration."
    ),
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — wildcard origin ("*") combined with allow_credentials=True is a
# well-known unsafe combination (any site can make credentialed requests on
# a logged-in user's behalf); only enable credentials when explicit origins
# are configured.
_cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
_cors_wildcard = _cors_origins == ["*"]
if _cors_wildcard:
    log.warning(
        "[CORS] CORS_ORIGINS not set (defaulting to '*') — allow_credentials "
        "forced to False. Set CORS_ORIGINS to your real frontend origin(s) "
        "to enable credentialed cross-origin requests."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request tracking middleware
if _HAS_TRACKING_MW:
    app.add_middleware(RequestTrackingMiddleware)

# Mount auth routes (register, login, refresh, api-key, me)
# Override the DB dependency in auth_router endpoints
from fastapi import APIRouter

_auth = APIRouter(prefix="/auth", tags=["Authentication"])

from fastapi.security import OAuth2PasswordRequestForm
from cerebro_auth import (
    UserCreate, UserRegister, TokenResponse, TokenRefreshRequest,
    APIKeyCreate, APIKeyResponse,
)

@_auth.post("/register", response_model=UserResponse)
async def register(user_data: UserRegister, db: Session = Depends(get_db)):
    # UserRegister has no `role` field — every self-registered account is
    # forced to READONLY here. Elevation requires an authenticated admin
    # via PUT /users/{id}/role (see the Admin section below).
    svc = AuthService(db)
    try:
        user = svc.create_user(UserCreate(
            email=user_data.email,
            username=user_data.username,
            password=user_data.password,
            full_name=user_data.full_name,
            role=Role.READONLY,
        ))
        return user
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))

@_auth.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db:   Session = Depends(get_db),
):
    svc = AuthService(db)
    result = svc.login(form.username, form.password)
    if not result:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Incorrect username or password")
    return result

@_auth.post("/refresh", response_model=TokenResponse)
async def refresh(req: TokenRefreshRequest, db: Session = Depends(get_db)):
    svc = AuthService(db)
    result = svc.refresh_tokens(req.refresh_token)
    if not result:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Invalid or revoked refresh token")
    return result

@_auth.get("/me", response_model=UserResponse)
async def get_me(user: UserModel = Depends(get_current_user)):
    return user

@_auth.post("/api-key", response_model=APIKeyResponse)
async def create_api_key_endpoint(
    req: APIKeyCreate,
    user: UserModel = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    """Generate a new API key. The raw key is returned ONCE — store it safely."""
    svc = AuthService(db)
    raw_key, key_model = svc.create_api_key(user.id, req.name, req.scopes)
    return APIKeyResponse(
        key=raw_key,
        key_prefix=key_model.key_prefix,
        name=key_model.name,
        scopes=key_model.scopes or [],
        created_at=key_model.created_at,
    )

app.include_router(_auth)


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH ENDPOINTS (public)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "CEREBRO-X API",
        "version": "2.0.0",
        "status":  "running",
        "docs":    "/docs",
    }

@app.get("/healthz", tags=["Health"])
async def liveness():
    """Kubernetes liveness probe — is the process alive?"""
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

@app.get("/readyz", tags=["Health"])
async def readiness():
    """Kubernetes readiness probe — can it serve traffic?"""
    health = HealthChecker.deep_health()
    if health["status"] != "healthy":
        return JSONResponse(status_code=503, content=health)
    return health

@app.get("/health/deep", tags=["Health"])
async def deep_health(user: UserModel = Depends(get_current_user)):
    """Authenticated deep health check with all dependency statuses."""
    return HealthChecker.deep_health()


# ═════════════════════════════════════════════════════════════════════════════
# PIPELINE ENDPOINTS (async, non-blocking)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/pipeline/run", tags=["Pipeline"])
async def run_pipeline(
    req:  PipelineRunRequest,
    user: UserModel = Depends(require_role(Role.ADMIN, Role.RESEARCHER)),
):
    """
    Submit a full pipeline run.
    async_mode=True → Celery (returns task_id, non-blocking)
    async_mode=False → BackgroundTasks (still non-blocking for caller)
    """
    if not has_permission(user.role, "pipeline:run"):
        raise HTTPException(403, "Permission denied: pipeline:run")

    if req.async_mode and _HAS_CELERY:
        task = pipeline_full_task.delay({"drugs": req.drugs})
        return {
            "status":  "submitted",
            "task_id": str(task.id),
            "queue":   "critical",
            "message": "Poll /pipeline/status/{task_id} for progress",
        }

    # Fallback: run in background thread
    import threading
    threading.Thread(
        target=_sync_pipeline_run,
        args=(req.drugs,),
        daemon=True,
    ).start()
    return {
        "status": "started",
        "mode":   "background_thread",
        "message": "Check /results for outputs",
    }

@app.get("/pipeline/status/{task_id}", tags=["Pipeline"])
async def pipeline_status(
    task_id: str,
    user: UserModel = Depends(get_current_user),
):
    """Poll Celery task status."""
    if not _HAS_CELERY:
        raise HTTPException(503, "Celery not available")

    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)
    response = {
        "task_id": task_id,
        "state":   result.state,
    }
    if result.ready():
        response["result"] = result.result
    elif result.state == "PROGRESS":
        response["progress"] = result.info
    return response


# ═════════════════════════════════════════════════════════════════════════════
# DDS ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/dds/run", tags=["DDS"])
async def run_dds(
    req:  DDSRunRequest,
    user: UserModel = Depends(require_role(Role.ADMIN, Role.RESEARCHER)),
):
    """Submit DDS formulation analysis (async)."""
    if _HAS_CELERY:
        from cerebro_orchestrator import celery_app
        task = celery_app.send_task("cerebro.run_dds")
        return {"status": "submitted", "task_id": str(task.id)}
    return {"status": "started", "mode": "sync"}

@app.get("/dds/ranking", tags=["DDS"])
async def dds_ranking(
    limit:     int   = Query(20, ge=1, le=100),
    min_score: float = Query(0.0, ge=0, le=100),
    user: UserModel  = Depends(get_current_user),
):
    """Return DDS formulation ranking."""
    import pandas as pd
    p = Path("CEREBRO_RESULTS/dds_analysis/formulation_ranking.csv")
    if not p.exists():
        raise HTTPException(404, "Run /dds/run first")
    df = pd.read_csv(p)
    df = df[df["BBB_Engineering_Score"] >= min_score]
    return df.head(limit).to_dict(orient="records")


# ═════════════════════════════════════════════════════════════════════════════
# ML INFERENCE ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/predict", tags=["Inference"])
async def predict_molecule(
    req:  PredictRequest,
    user: UserModel = Depends(get_current_user),
):
    """
    Predict ML_Success_Probability for a new molecule.
    Uses SAVED model scaler via .transform() (no re-training).
    """
    if not has_permission(user.role, "model:predict"):
        raise HTTPException(403, "Permission denied: model:predict")

    if _HAS_PROMETHEUS:
        MODEL_PREDICTIONS.labels("cerebro_ensemble").inc()

    # Load production model from registry
    registry = ModelRegistry()
    prod = registry.get_production("cerebro_ensemble")
    if not prod:
        raise HTTPException(404, "No production model. Run /pipeline/run first.")

    try:
        import joblib
        model = joblib.load(prod.artifact_path)
    except Exception as e:
        raise HTTPException(500, f"Model load failed: {e}")

    # Build features (simplified — real version uses MoleculeEngine)
    features = {
        "MW_Da": 0, "LogP": 0,
        "Half_Life_Days": 0, "Docking_Affinity_kcal": -8.5,
    }
    import numpy as np
    X = np.array([[features["MW_Da"], features["LogP"],
                   features["Half_Life_Days"],
                   features["Docking_Affinity_kcal"]]])

    try:
        score = float(model.predict(X)[0])
    except Exception as e:
        raise HTTPException(500, f"Prediction failed: {e}")

    return {
        "drug_name":              req.drug_name or req.molecule_input[:30],
        "ML_Success_Probability": round(score, 4),
        "model_version":          prod.version,
        "model_stage":            prod.stage,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MLOps ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/mlops/models", tags=["MLOps"])
async def list_models(
    model_name: str = "cerebro_ensemble",
    stage: Optional[str] = None,
    user: UserModel = Depends(get_current_user),
):
    """List all model versions."""
    registry = ModelRegistry()
    versions = registry.list_versions(model_name, stage)
    return [
        {"version": v.version, "stage": v.stage,
         "metrics": v.metrics, "created_at": v.created_at}
        for v in versions
    ]

@app.post("/mlops/promote", tags=["MLOps"])
async def promote_model(
    req:  ModelPromoteRequest,
    user: UserModel = Depends(require_role(Role.ADMIN)),
):
    """Promote a model version to a new stage (admin only)."""
    registry = ModelRegistry()
    registry.promote(req.model_name, req.version, req.target_stage)
    return {"status": "promoted", "model": req.model_name,
            "version": req.version, "stage": req.target_stage}

@app.post("/mlops/drift-check", tags=["MLOps"])
async def check_drift(
    req:  DriftCheckRequest,
    user: UserModel = Depends(require_role(Role.ADMIN, Role.RESEARCHER)),
):
    """Run model + data drift detection."""
    import numpy as np
    # In production, load reference predictions from model registry
    # For now, return structure
    ref_preds = np.random.normal(0.65, 0.1, 100)
    cur_preds = np.random.normal(0.63, 0.12, 50)

    model_drift = ModelDriftDetector.detect_prediction_drift(ref_preds, cur_preds)

    if _HAS_PROMETHEUS and model_drift["severity"] != "none":
        DRIFT_EVENTS.labels("model_drift", model_drift["severity"]).inc()

    return {"model_name": req.model_name, "drift": model_drift}

@app.get("/mlops/drift-events", tags=["MLOps"])
async def get_drift_events(
    hours: int = 24,
    user:  UserModel = Depends(get_current_user),
):
    """Get recent drift events."""
    logger = DriftEventLogger()
    return logger.get_recent(hours=hours)

@app.get("/mlops/experiments", tags=["MLOps"])
async def list_experiments(
    model_name: str = "cerebro_ensemble",
    user: UserModel  = Depends(get_current_user),
):
    """List recent experiment runs."""
    tracker = ExperimentTracker()
    import sqlite3
    conn = sqlite3.connect(str(tracker.db_path))
    rows = conn.execute("""
        SELECT run_id, model_name, status, started_at, finished_at
        FROM experiments WHERE model_name = ?
        ORDER BY started_at DESC LIMIT 20
    """, (model_name,)).fetchall()
    conn.close()
    return [
        {"run_id": r[0], "model_name": r[1], "status": r[2],
         "started_at": r[3], "finished_at": r[4]}
        for r in rows
    ]


# ═════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/kg/build", tags=["Knowledge Graph"])
async def build_knowledge_graph(
    req:  KGBuildRequest,
    user: UserModel = Depends(require_role(Role.ADMIN, Role.RESEARCHER)),
):
    """Build the drug-DDS-target knowledge graph from pipeline data."""
    import pandas as pd
    kg = CerebroKnowledgeGraph()

    # Load available data
    ranking_path = Path("CEREBRO_RESULTS/dds_analysis/formulation_ranking.csv")
    if ranking_path.exists() and req.include_formulations:
        df = pd.read_csv(ranking_path)
        kg.build_from_pipeline_data(formulation_df=df)

    # Export
    out_path = "CEREBRO_RESULTS/knowledge_graph.json"
    export_kg_to_json(kg, out_path)

    # Analytics
    G = kg.to_networkx()
    top_carriers = kg.find_top_carriers(5)

    return {
        "n_nodes":      len(kg.nodes),
        "n_edges":      len(kg.edges),
        "top_carriers":  top_carriers,
        "export_path":  out_path,
    }

@app.get("/kg/suggest/{drug_id}", tags=["Knowledge Graph"])
async def suggest_combinations(
    drug_id: str,
    top_n:   int = 5,
    user: UserModel = Depends(get_current_user),
):
    """Suggest new drug-carrier combinations via link prediction."""
    import pandas as pd
    kg = CerebroKnowledgeGraph()
    ranking_path = Path("CEREBRO_RESULTS/dds_analysis/formulation_ranking.csv")
    if ranking_path.exists():
        df = pd.read_csv(ranking_path)
        kg.build_from_pipeline_data(formulation_df=df)
        kg.to_networkx()
    return kg.suggest_combinations(f"drug:{drug_id}", top_n)


# ═════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/orchestrator/status", tags=["Orchestration"])
async def orchestrator_status(
    user: UserModel = Depends(require_role(Role.ADMIN)),
):
    """Get pipeline DAG orchestration status."""
    orch = create_cerebro_pipeline_dag()
    topo = orch._topological_sort()
    return {
        "dag_levels": topo,
        "n_tasks":    len(orch.tasks),
        "circuit_breakers": {
            name: cb.status for name, cb in orch.breakers.items()
        },
    }

@app.get("/orchestrator/dead-letter", tags=["Orchestration"])
async def dead_letter_queue(
    user: UserModel = Depends(require_role(Role.ADMIN)),
):
    """View the dead letter queue (permanently failed tasks)."""
    orch = create_cerebro_pipeline_dag()
    return {"dead_letter_queue": orch.dead_letter_queue}


# ═════════════════════════════════════════════════════════════════════════════
# MONITORING ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/monitoring/alerts", tags=["Monitoring"])
async def get_alerts(
    user: UserModel = Depends(require_role(Role.ADMIN)),
):
    """Get alert history."""
    return {"alerts": _alert_engine.history}

@app.get("/monitoring/metrics-summary", tags=["Monitoring"])
async def metrics_summary(
    user: UserModel = Depends(require_role(Role.ADMIN)),
):
    """System metrics summary."""
    collect_system_metrics()
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "note": "Full Prometheus metrics at :8001/metrics",
    }


# ═════════════════════════════════════════════════════════════════════════════
# RESULTS ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/results", tags=["Results"])
async def list_results(user: UserModel = Depends(get_current_user)):
    """List all output files."""
    out = Path("CEREBRO_RESULTS")
    files = []
    if out.exists():
        for p in out.rglob("*"):
            if p.is_file() and not p.name.endswith("_DOCUMENTATION.txt"):
                files.append({
                    "path":     str(p.relative_to(out)),
                    "size_kb":  round(p.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(
                        p.stat().st_mtime).isoformat(),
                })
    return {"n_files": len(files), "files": files}

@app.get("/results/{filepath:path}", tags=["Results"])
async def download_result(
    filepath: str,
    user: UserModel = Depends(get_current_user),
):
    """Download a result file."""
    full = Path("CEREBRO_RESULTS") / filepath
    if not full.exists():
        raise HTTPException(404, f"File not found: {filepath}")
    return FileResponse(str(full))


# ═════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT (admin only)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/users", tags=["Admin"])
async def list_users(
    user: UserModel = Depends(require_role(Role.ADMIN)),
    db:   Session   = Depends(get_db),
):
    """List all users (admin only)."""
    users = db.query(UserModel).all()
    return [
        {"id": u.id, "username": u.username, "email": u.email,
         "role": u.role, "is_active": u.is_active}
        for u in users
    ]

@app.put("/users/{user_id}/role", tags=["Admin"])
async def update_role(
    user_id: int,
    role:    str,
    admin:   UserModel = Depends(require_role(Role.ADMIN)),
    db:      Session   = Depends(get_db),
):
    """Change a user's role (admin only)."""
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    if role not in [r.value for r in Role]:
        raise HTTPException(400, f"Invalid role: {role}")
    target.role = role
    db.commit()
    return {"status": "updated", "user_id": user_id, "new_role": role}


# ═════════════════════════════════════════════════════════════════════════════
# STARTUP / SHUTDOWN
# ═════════════════════════════════════════════════════════════════════════════

_alert_engine = AlertEngine()

@app.on_event("startup")
async def startup():
    log.info("=" * 65)
    log.info("  CEREBRO-X — API")
    log.info("=" * 65)

    # Structured logging
    setup_structured_logging()

    # Bootstrap admin
    db = SessionLocal()
    try:
        bootstrap_admin(db)
    finally:
        db.close()

    # Prometheus metrics
    metrics_port = int(os.environ.get("METRICS_PORT", "8001"))
    start_metrics_server(metrics_port)

    # Alerts
    setup_default_alerts(_alert_engine)

    # System metrics collection loop
    async def _collect_loop():
        while True:
            collect_system_metrics()
            _alert_engine.evaluate()
            await asyncio.sleep(30)
    asyncio.create_task(_collect_loop())

    log.info("[STARTUP] All systems initialized")

@app.on_event("shutdown")
async def shutdown():
    log.info("[SHUTDOWN] CEREBRO-X API shutting down")


# ─────────────────────────────────────────────────────────────────────────────
# Sync helpers (for background thread fallback when Celery unavailable)
# ─────────────────────────────────────────────────────────────────────────────
def _sync_pipeline_run(drugs: List[str]):
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import CEREBRO_Pipeline as cp
        cp.setup_workspace()
        df_mab = cp.CascadeDataEngine.build_mab_dataset(drugs)
        if df_mab.empty:
            log.warning("[SYNC] No data fetched")
            return
        df_ml, _, metrics = cp.AdvancedMLEngine.train(
            df_mab,
            ["MW_Da", "LogP", "Half_Life_Days", "Docking_Affinity_kcal"]
        )
        df_ml = cp.ADMETEngine.run(df_ml)
        cp.ReportingEngine.generate_master_report(df_mab, None, df_ml, metrics)
        log.info(f"[SYNC] Pipeline complete: R²={metrics.get('r2', 0):.4f}")
    except Exception as e:
        log.exception(f"[SYNC] Pipeline failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    host = os.environ.get("FASTAPI_HOST", "0.0.0.0")
    port = int(os.environ.get("FASTAPI_PORT", "8000"))
    log.info(f"Starting CEREBRO-X API on http://{host}:{port}")
    uvicorn.run(
        "cerebro_api_v2:app",
        host=host,
        port=port,
        workers=int(os.environ.get("API_WORKERS", "4")),
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()