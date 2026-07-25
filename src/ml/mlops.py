"""
================================================================================
CEREBRO-X |  MLOps ENGINE
================================================================================
File: cerebro_mlops.py

Production ML lifecycle management:

  1. Model Registry
     - Version control for trained models (semantic versioning)
     - Metadata tracking: hyperparameters, metrics, training data hash
     - Model promotion pipeline: staging → production → archived
     - Rollback to any previous version

  2. Model Drift Detection
     - PSI (Population Stability Index) on prediction distributions
     - KS test (Kolmogorov-Smirnov) for distribution shift
     - Performance degradation monitoring (R², MAE thresholds)
     - Automated retraining triggers

  3. Data Drift Detection
     - Feature-level distribution comparison (reference vs. live)
     - Missing value ratio monitoring
     - Schema validation (column presence, types, ranges)
     - Wasserstein distance for continuous features

  4. Experiment Tracking
     - Run-level logging (params, metrics, artifacts)
     - Comparison across experiments
     - Reproducibility: random seeds, data hashes, code version

  5. A/B Model Serving
     - Traffic splitting between model versions
     - Statistical significance testing
     - Automatic winner promotion

References:
  - Sculley et al. (2015) "Hidden Technical Debt in ML Systems"
  - Google MLOps Whitepaper (2020)
  - Evidently AI drift detection methodology
================================================================================
"""

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger("CEREBRO-MLOPS")

# ─────────────────────────────────────────────────────────────────────────────
# Optional imports
# ─────────────────────────────────────────────────────────────────────────────
try:
    from scipy import stats as sp_stats
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

try:
    import joblib
    _HAS_JOBLIB = True
except ImportError:
    _HAS_JOBLIB = False


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
MLOPS_DB_PATH = Path(os.environ.get(
    "MLOPS_DB_PATH",
    "CEREBRO_RESULTS/mlops_registry.db"
))
MLOPS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

MODEL_STORE_DIR = Path(os.environ.get(
    "MODEL_STORE_DIR",
    "CEREBRO_RESULTS/model_store"
))
MODEL_STORE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Model Registry
# ─────────────────────────────────────────────────────────────────────────────
class ModelStage:
    DEVELOPMENT = "development"
    STAGING     = "staging"
    PRODUCTION  = "production"
    ARCHIVED    = "archived"


@dataclass
class ModelVersion:
    model_name:     str
    version:        str              # semantic: "1.0.0", "1.1.0", etc.
    stage:          str = ModelStage.DEVELOPMENT
    metrics:        dict = field(default_factory=dict)
    hyperparams:    dict = field(default_factory=dict)
    training_data_hash: str = ""
    artifact_path:  str = ""
    created_at:     str = ""
    description:    str = ""
    tags:           dict = field(default_factory=dict)
    run_id:         str = ""


class ModelRegistry:
    """
    SQLite-backed model registry with versioning and stage promotion.

    Lifecycle: development → staging → production → archived
    Only ONE model version can be in 'production' stage at a time.
    """

    def __init__(self, db_path: Path = MLOPS_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name      TEXT NOT NULL,
                version         TEXT NOT NULL,
                stage           TEXT DEFAULT 'development',
                metrics         TEXT DEFAULT '{}',
                hyperparams     TEXT DEFAULT '{}',
                training_data_hash TEXT DEFAULT '',
                artifact_path   TEXT DEFAULT '',
                created_at      TEXT DEFAULT '',
                description     TEXT DEFAULT '',
                tags            TEXT DEFAULT '{}',
                run_id          TEXT DEFAULT '',
                UNIQUE(model_name, version)
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT UNIQUE NOT NULL,
                model_name  TEXT NOT NULL,
                params      TEXT DEFAULT '{}',
                metrics     TEXT DEFAULT '{}',
                artifacts   TEXT DEFAULT '[]',
                status      TEXT DEFAULT 'running',
                started_at  TEXT,
                finished_at TEXT,
                data_hash   TEXT DEFAULT '',
                code_hash   TEXT DEFAULT '',
                notes       TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS drift_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name   TEXT NOT NULL,
                drift_type   TEXT NOT NULL,
                metric_name  TEXT,
                metric_value REAL,
                threshold    REAL,
                severity     TEXT DEFAULT 'warning',
                details      TEXT DEFAULT '{}',
                detected_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mv_name_stage
                ON model_versions(model_name, stage);
            CREATE INDEX IF NOT EXISTS idx_drift_model
                ON drift_events(model_name, detected_at);
        """)
        conn.commit()
        conn.close()

    def register(self, mv: ModelVersion) -> int:
        """Register a new model version."""
        mv.created_at = mv.created_at or datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("""
            INSERT INTO model_versions
                (model_name, version, stage, metrics, hyperparams,
                 training_data_hash, artifact_path, created_at,
                 description, tags, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            mv.model_name, mv.version, mv.stage,
            json.dumps(mv.metrics), json.dumps(mv.hyperparams),
            mv.training_data_hash, mv.artifact_path,
            mv.created_at, mv.description,
            json.dumps(mv.tags), mv.run_id,
        ))
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        log.info(f"[REGISTRY] Registered {mv.model_name} v{mv.version} "
                 f"(stage={mv.stage})")
        return rid

    def promote(self, model_name: str, version: str, target_stage: str):
        """
        Promote a model version to a new stage.
        If promoting to 'production', demote current production → archived.
        """
        conn = sqlite3.connect(self.db_path)
        if target_stage == ModelStage.PRODUCTION:
            # Demote current production
            conn.execute("""
                UPDATE model_versions SET stage = ?
                WHERE model_name = ? AND stage = ?
            """, (ModelStage.ARCHIVED, model_name, ModelStage.PRODUCTION))

        conn.execute("""
            UPDATE model_versions SET stage = ?
            WHERE model_name = ? AND version = ?
        """, (target_stage, model_name, version))
        conn.commit()
        conn.close()
        log.info(f"[REGISTRY] Promoted {model_name} v{version} → {target_stage}")

    def get_production(self, model_name: str) -> ModelVersion | None:
        """Get the current production model version."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("""
            SELECT * FROM model_versions
            WHERE model_name = ? AND stage = ?
            ORDER BY created_at DESC LIMIT 1
        """, (model_name, ModelStage.PRODUCTION)).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_mv(row)

    def get_latest(self, model_name: str) -> ModelVersion | None:
        """Get the latest model version regardless of stage."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("""
            SELECT * FROM model_versions
            WHERE model_name = ?
            ORDER BY created_at DESC LIMIT 1
        """, (model_name,)).fetchone()
        conn.close()
        return self._row_to_mv(row) if row else None

    def list_versions(self, model_name: str,
                      stage: str = None) -> list[ModelVersion]:
        conn = sqlite3.connect(self.db_path)
        if stage:
            rows = conn.execute("""
                SELECT * FROM model_versions
                WHERE model_name = ? AND stage = ?
                ORDER BY created_at DESC
            """, (model_name, stage)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM model_versions
                WHERE model_name = ?
                ORDER BY created_at DESC
            """, (model_name,)).fetchall()
        conn.close()
        return [self._row_to_mv(r) for r in rows]

    def rollback(self, model_name: str, target_version: str):
        """Rollback production to a specific version."""
        self.promote(model_name, target_version, ModelStage.PRODUCTION)
        log.warning(f"[REGISTRY] ROLLBACK: {model_name} → v{target_version}")

    @staticmethod
    def _row_to_mv(row) -> ModelVersion:
        return ModelVersion(
            model_name=row[1], version=row[2], stage=row[3],
            metrics=json.loads(row[4] or "{}"),
            hyperparams=json.loads(row[5] or "{}"),
            training_data_hash=row[6], artifact_path=row[7],
            created_at=row[8], description=row[9],
            tags=json.loads(row[10] or "{}"), run_id=row[11],
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Model Drift Detection
# ─────────────────────────────────────────────────────────────────────────────
class ModelDriftDetector:
    """
    Detects prediction distribution shifts between reference and live data.

    Methods:
      - PSI (Population Stability Index): standard banking/pharma metric
          PSI < 0.10 → no shift
          PSI 0.10–0.25 → moderate shift (monitor)
          PSI > 0.25 → significant drift (retrain)

      - KS Test: nonparametric distribution comparison
          p < 0.05 → statistically significant drift

      - Performance degradation: checks if live R²/MAE crosses threshold
    """

    PSI_THRESHOLD_MODERATE = 0.10
    PSI_THRESHOLD_SEVERE   = 0.25
    KS_ALPHA               = 0.05

    @staticmethod
    def compute_psi(reference: np.ndarray, current: np.ndarray,
                    n_bins: int = 10) -> float:
        """
        Population Stability Index.

        PSI = Σ (P_i − Q_i) × ln(P_i / Q_i)

        where P = reference distribution, Q = current distribution,
        both bucketed into n_bins quantile-based bins.
        """
        ref = np.array(reference, dtype=float)
        cur = np.array(current, dtype=float)

        # Create bins from reference distribution
        breakpoints = np.percentile(ref, np.linspace(0, 100, n_bins + 1))
        breakpoints = np.unique(breakpoints)

        ref_counts = np.histogram(ref, bins=breakpoints)[0]
        cur_counts = np.histogram(cur, bins=breakpoints)[0]

        # Convert to proportions (with epsilon to avoid log(0))
        eps = 1e-6
        ref_pct = (ref_counts + eps) / (ref_counts.sum() + eps * len(ref_counts))
        cur_pct = (cur_counts + eps) / (cur_counts.sum() + eps * len(cur_counts))

        psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
        return float(psi)

    @staticmethod
    def ks_test(reference: np.ndarray,
                current: np.ndarray) -> tuple[float, float]:
        """
        Two-sample Kolmogorov-Smirnov test.
        Returns (statistic, p_value).
        """
        if not _HAS_SCIPY:
            log.warning("[DRIFT] scipy not available for KS test")
            return (0.0, 1.0)
        stat, p = sp_stats.ks_2samp(reference, current)
        return float(stat), float(p)

    @classmethod
    def detect_prediction_drift(
        cls,
        reference_preds: np.ndarray,
        current_preds:   np.ndarray,
    ) -> dict[str, Any]:
        """
        Full prediction drift analysis.
        Returns dict with PSI, KS test, and drift verdict.
        """
        psi = cls.compute_psi(reference_preds, current_preds)
        ks_stat, ks_p = cls.ks_test(reference_preds, current_preds)

        severity = "none"
        if psi > cls.PSI_THRESHOLD_SEVERE or ks_p < cls.KS_ALPHA:
            severity = "severe"
        elif psi > cls.PSI_THRESHOLD_MODERATE:
            severity = "moderate"

        result = {
            "psi":          round(psi, 6),
            "psi_threshold": cls.PSI_THRESHOLD_SEVERE,
            "ks_statistic": round(ks_stat, 6),
            "ks_p_value":   round(ks_p, 6),
            "ks_alpha":     cls.KS_ALPHA,
            "severity":     severity,
            "action":       {
                "none":     "No action required",
                "moderate": "Monitor closely — consider retraining",
                "severe":   "RETRAIN REQUIRED — prediction distribution shifted",
            }.get(severity, "Unknown"),
            "ref_mean":  float(np.mean(reference_preds)),
            "cur_mean":  float(np.mean(current_preds)),
            "ref_std":   float(np.std(reference_preds)),
            "cur_std":   float(np.std(current_preds)),
            "n_ref":     len(reference_preds),
            "n_cur":     len(current_preds),
        }

        if severity != "none":
            log.warning(f"[MODEL DRIFT] severity={severity} PSI={psi:.4f} "
                        f"KS_p={ks_p:.4f}")
        return result

    @classmethod
    def check_performance_degradation(
        cls,
        current_r2:  float,
        baseline_r2: float,
        current_mae: float,
        baseline_mae: float,
        r2_drop_threshold:  float = 0.10,
        mae_rise_threshold: float = 0.20,
    ) -> dict[str, Any]:
        """
        Compare current model metrics vs baseline.
        Flags degradation if R² drops or MAE rises beyond thresholds.
        """
        r2_delta  = baseline_r2 - current_r2
        mae_delta = (current_mae - baseline_mae) / max(baseline_mae, 1e-6)

        degraded = (r2_delta > r2_drop_threshold or
                    mae_delta > mae_rise_threshold)

        return {
            "degraded":          degraded,
            "r2_current":        round(current_r2, 4),
            "r2_baseline":       round(baseline_r2, 4),
            "r2_delta":          round(r2_delta, 4),
            "mae_current":       round(current_mae, 4),
            "mae_baseline":      round(baseline_mae, 4),
            "mae_delta_pct":     round(mae_delta * 100, 2),
            "r2_threshold":      r2_drop_threshold,
            "mae_threshold_pct": mae_rise_threshold * 100,
            "action": "RETRAIN: performance degraded" if degraded
                      else "OK: within acceptable bounds",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Data Drift Detection
# ─────────────────────────────────────────────────────────────────────────────
class DataDriftDetector:
    """
    Feature-level data drift detection.

    Compares a reference dataset (training data snapshot) against
    live/incoming data to detect schema violations, distribution shifts,
    and anomalous missing value patterns.
    """

    WASSERSTEIN_THRESHOLD = 0.1   # normalized
    MISSING_RATIO_THRESHOLD = 0.2  # 20% increase in nulls = alert

    @classmethod
    def compute_reference_profile(cls, df: pd.DataFrame,
                                  numeric_cols: list[str]) -> dict:
        """
        Snapshot reference statistics from training data.
        Store this once after training — compare all future data against it.
        """
        profile = {
            "schema": {
                "columns":  list(df.columns),
                "dtypes":   {c: str(df[c].dtype) for c in df.columns},
                "n_rows":   len(df),
            },
            "features": {},
            "computed_at": datetime.utcnow().isoformat(),
        }

        for col in numeric_cols:
            if col not in df.columns:
                continue
            vals = df[col].dropna().values.astype(float)
            profile["features"][col] = {
                "mean":       float(np.mean(vals)) if len(vals) > 0 else 0,
                "std":        float(np.std(vals))  if len(vals) > 0 else 0,
                "min":        float(np.min(vals))  if len(vals) > 0 else 0,
                "max":        float(np.max(vals))  if len(vals) > 0 else 0,
                "median":     float(np.median(vals)) if len(vals) > 0 else 0,
                "q25":        float(np.percentile(vals, 25)) if len(vals) > 0 else 0,
                "q75":        float(np.percentile(vals, 75)) if len(vals) > 0 else 0,
                "missing_pct": float(df[col].isna().mean()),
                "n_unique":    int(df[col].nunique()),
                "values":      vals.tolist(),  # for distribution tests
            }
        return profile

    @classmethod
    def detect_drift(cls, reference_profile: dict,
                     live_df: pd.DataFrame,
                     numeric_cols: list[str]) -> dict:
        """
        Run full drift detection suite against reference profile.
        Returns per-feature drift results + overall summary.
        """
        results = {
            "schema_drift":   cls._check_schema(reference_profile, live_df),
            "feature_drift":  {},
            "overall_drift":  False,
            "drifted_features": [],
            "checked_at":     datetime.utcnow().isoformat(),
        }

        for col in numeric_cols:
            if col not in live_df.columns:
                continue
            ref_stats = reference_profile.get("features", {}).get(col)
            if not ref_stats:
                continue

            live_vals = live_df[col].dropna().values.astype(float)
            ref_vals  = np.array(ref_stats.get("values", []))

            if len(live_vals) < 5 or len(ref_vals) < 5:
                continue

            # KS test
            ks_stat, ks_p = (0.0, 1.0)
            if _HAS_SCIPY:
                ks_stat, ks_p = sp_stats.ks_2samp(ref_vals, live_vals)

            # Wasserstein distance (normalized by reference range)
            wasserstein = 0.0
            if _HAS_SCIPY:
                w = sp_stats.wasserstein_distance(ref_vals, live_vals)
                ref_range = ref_stats["max"] - ref_stats["min"]
                wasserstein = w / max(ref_range, 1e-6)

            # Missing ratio change
            live_missing = float(live_df[col].isna().mean())
            ref_missing  = ref_stats.get("missing_pct", 0)
            missing_delta = live_missing - ref_missing

            # PSI
            psi = ModelDriftDetector.compute_psi(ref_vals, live_vals)

            drifted = (
                ks_p < 0.05 or
                wasserstein > cls.WASSERSTEIN_THRESHOLD or
                psi > ModelDriftDetector.PSI_THRESHOLD_MODERATE or
                missing_delta > cls.MISSING_RATIO_THRESHOLD
            )

            results["feature_drift"][col] = {
                "ks_statistic":      round(float(ks_stat), 4),
                "ks_p_value":        round(float(ks_p), 4),
                "wasserstein_norm":  round(wasserstein, 4),
                "psi":               round(psi, 4),
                "missing_ref":       round(ref_missing, 4),
                "missing_live":      round(live_missing, 4),
                "missing_delta":     round(missing_delta, 4),
                "mean_ref":          round(ref_stats["mean"], 4),
                "mean_live":         round(float(np.mean(live_vals)), 4),
                "drifted":           drifted,
            }

            if drifted:
                results["drifted_features"].append(col)

        results["overall_drift"] = len(results["drifted_features"]) > 0
        results["n_drifted"]     = len(results["drifted_features"])
        results["n_checked"]     = len(results["feature_drift"])

        if results["overall_drift"]:
            log.warning(f"[DATA DRIFT] {results['n_drifted']}/{results['n_checked']} "
                        f"features drifted: {results['drifted_features']}")
        return results

    @staticmethod
    def _check_schema(ref_profile: dict, live_df: pd.DataFrame) -> dict:
        """Check for missing columns, new columns, type changes."""
        ref_cols  = set(ref_profile.get("schema", {}).get("columns", []))
        live_cols = set(live_df.columns)
        return {
            "missing_columns": sorted(ref_cols - live_cols),
            "new_columns":     sorted(live_cols - ref_cols),
            "schema_valid":    ref_cols.issubset(live_cols),
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Experiment Tracker
# ─────────────────────────────────────────────────────────────────────────────
class ExperimentTracker:
    """
    Lightweight experiment tracker (MLflow-compatible concepts, SQLite-backed).
    Logs parameters, metrics, and artifacts for each training run.
    """

    def __init__(self, db_path: Path = MLOPS_DB_PATH):
        self.db_path = db_path

    def start_run(self, model_name: str, params: dict = None,
                  notes: str = "") -> str:
        """Start a new experiment run. Returns run_id."""
        import secrets
        run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}"
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO experiments
                (run_id, model_name, params, status, started_at, notes)
            VALUES (?,?,?,?,?,?)
        """, (run_id, model_name, json.dumps(params or {}),
              "running", datetime.utcnow().isoformat(), notes))
        conn.commit()
        conn.close()
        log.info(f"[EXPERIMENT] Started run {run_id} for {model_name}")
        return run_id

    def log_metrics(self, run_id: str, metrics: dict):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE experiments SET metrics = ? WHERE run_id = ?
        """, (json.dumps(metrics), run_id))
        conn.commit()
        conn.close()

    def log_artifact(self, run_id: str, artifact_path: str):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT artifacts FROM experiments WHERE run_id = ?", (run_id,)
        ).fetchone()
        arts = json.loads(row[0]) if row else []
        arts.append(artifact_path)
        conn.execute("""
            UPDATE experiments SET artifacts = ? WHERE run_id = ?
        """, (json.dumps(arts), run_id))
        conn.commit()
        conn.close()

    def end_run(self, run_id: str, status: str = "completed",
                data_hash: str = ""):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            UPDATE experiments
            SET status = ?, finished_at = ?, data_hash = ?
            WHERE run_id = ?
        """, (status, datetime.utcnow().isoformat(), data_hash, run_id))
        conn.commit()
        conn.close()
        log.info(f"[EXPERIMENT] Run {run_id} → {status}")

    def get_run(self, run_id: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT * FROM experiments WHERE run_id = ?", (run_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "run_id":      row[1], "model_name": row[2],
            "params":      json.loads(row[3] or "{}"),
            "metrics":     json.loads(row[4] or "{}"),
            "artifacts":   json.loads(row[5] or "[]"),
            "status":      row[6],
            "started_at":  row[7], "finished_at": row[8],
            "data_hash":   row[9], "code_hash":   row[10],
            "notes":       row[11],
        }

    def compare_runs(self, run_ids: list[str]) -> pd.DataFrame:
        """Compare metrics across multiple runs as a DataFrame."""
        runs = [self.get_run(rid) for rid in run_ids]
        runs = [r for r in runs if r is not None]
        if not runs:
            return pd.DataFrame()

        records = []
        for r in runs:
            row = {"run_id": r["run_id"], "model_name": r["model_name"],
                   "status": r["status"]}
            row.update(r.get("params", {}))
            row.update({f"metric_{k}": v for k, v in r.get("metrics", {}).items()})
            records.append(row)
        return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Drift Event Logger (persistent)
# ─────────────────────────────────────────────────────────────────────────────
class DriftEventLogger:
    """Logs drift events to SQLite for monitoring and alerting."""

    def __init__(self, db_path: Path = MLOPS_DB_PATH):
        self.db_path = db_path

    def log_event(self, model_name: str, drift_type: str,
                  metric_name: str, metric_value: float,
                  threshold: float, severity: str = "warning",
                  details: dict = None):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO drift_events
                (model_name, drift_type, metric_name, metric_value,
                 threshold, severity, details, detected_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            model_name, drift_type, metric_name, metric_value,
            threshold, severity, json.dumps(details or {}),
            datetime.utcnow().isoformat(),
        ))
        conn.commit()
        conn.close()

    def get_recent(self, model_name: str = None,
                   hours: int = 24) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        if model_name:
            rows = conn.execute("""
                SELECT * FROM drift_events
                WHERE model_name = ? AND detected_at > ?
                ORDER BY detected_at DESC
            """, (model_name, cutoff)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM drift_events WHERE detected_at > ?
                ORDER BY detected_at DESC
            """, (cutoff,)).fetchall()
        conn.close()
        return [
            {"id": r[0], "model_name": r[1], "drift_type": r[2],
             "metric_name": r[3], "metric_value": r[4], "threshold": r[5],
             "severity": r[6], "details": json.loads(r[7] or "{}"),
             "detected_at": r[8]}
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# 6. MLOps Pipeline (ties everything together)
# ─────────────────────────────────────────────────────────────────────────────
class MLOpsPipeline:
    """
    High-level MLOps workflow:
      1. Train → log experiment → register model → save reference profile
      2. On new data: check data drift → predict → check model drift
      3. If drift detected: trigger retraining → register new version → promote
    """

    def __init__(self):
        self.registry    = ModelRegistry()
        self.tracker     = ExperimentTracker()
        self.drift_log   = DriftEventLogger()

    def train_and_register(
        self,
        model_name:  str,
        train_func:  callable,  # train_func(X, y) → (model, metrics)
        X_train:     np.ndarray,
        y_train:     np.ndarray,
        hyperparams: dict = None,
        description: str = "",
    ) -> tuple[Any, str]:
        """
        Full training workflow:
        1. Start experiment
        2. Train model via provided function
        3. Log metrics
        4. Save model artifact
        5. Register in model registry
        6. Save reference data profile
        """
        # Determine next version
        latest = self.registry.get_latest(model_name)
        if latest:
            parts = latest.version.split(".")
            next_v = f"{parts[0]}.{int(parts[1]) + 1}.0"
        else:
            next_v = "1.0.0"

        # Data hash
        data_hash = hashlib.sha256(
            X_train.tobytes() + y_train.tobytes()
        ).hexdigest()[:16]

        # Experiment
        run_id = self.tracker.start_run(
            model_name, params=hyperparams, notes=description
        )

        try:
            # Train
            model, metrics = train_func(X_train, y_train)

            # Save artifact
            artifact_path = str(
                MODEL_STORE_DIR / f"{model_name}_v{next_v}.pkl"
            )
            if _HAS_JOBLIB:
                joblib.dump(model, artifact_path)
            else:
                import pickle
                with open(artifact_path, "wb") as f:
                    pickle.dump(model, f)

            # Log
            self.tracker.log_metrics(run_id, metrics)
            self.tracker.log_artifact(run_id, artifact_path)
            self.tracker.end_run(run_id, "completed", data_hash)

            # Register
            mv = ModelVersion(
                model_name=model_name,
                version=next_v,
                stage=ModelStage.STAGING,
                metrics=metrics,
                hyperparams=hyperparams or {},
                training_data_hash=data_hash,
                artifact_path=artifact_path,
                description=description,
                run_id=run_id,
            )
            self.registry.register(mv)

            # Auto-promote if better than current production
            prod = self.registry.get_production(model_name)
            if not prod:
                self.registry.promote(model_name, next_v, ModelStage.PRODUCTION)
            elif metrics.get("r2", 0) > prod.metrics.get("r2", 0):
                self.registry.promote(model_name, next_v, ModelStage.PRODUCTION)
                log.info(f"[MLOPS] Auto-promoted v{next_v} "
                         f"(R²={metrics.get('r2', 0):.4f} > "
                         f"{prod.metrics.get('r2', 0):.4f})")

            return model, run_id

        except Exception:
            self.tracker.end_run(run_id, "failed")
            raise

    def check_and_alert(
        self,
        model_name:      str,
        reference_preds: np.ndarray,
        current_preds:   np.ndarray,
        reference_profile: dict = None,
        live_df:           pd.DataFrame = None,
        numeric_cols:      list[str] = None,
    ) -> dict:
        """
        Run all drift checks and log events.
        Returns combined drift report.
        """
        report = {"model_name": model_name, "checked_at": datetime.utcnow().isoformat()}

        # Model drift
        model_drift = ModelDriftDetector.detect_prediction_drift(
            reference_preds, current_preds
        )
        report["model_drift"] = model_drift

        if model_drift["severity"] != "none":
            self.drift_log.log_event(
                model_name, "model_drift", "psi",
                model_drift["psi"], model_drift["psi_threshold"],
                model_drift["severity"], model_drift,
            )

        # Data drift
        if reference_profile and live_df is not None and numeric_cols:
            data_drift = DataDriftDetector.detect_drift(
                reference_profile, live_df, numeric_cols
            )
            report["data_drift"] = data_drift

            if data_drift["overall_drift"]:
                self.drift_log.log_event(
                    model_name, "data_drift", "n_drifted",
                    data_drift["n_drifted"], 0,
                    "warning", data_drift,
                )

        return report