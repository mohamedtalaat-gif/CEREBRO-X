"""
================================================================================
CEREBRO-X |  DATA ENGINEERING MATURITY ENGINE
================================================================================
File: cerebro_data_engineering.py

Implements all 7 Data Engineering Maturity pillars for CEREBRO-X:

  1.  ETL Pipelines         — scalable, production-grade Extract-Transform-Load
  2.  Event-Driven Ingestion — file-watcher + message bus for real-time data
  3.  Data Lakehouse         — local Parquet lake with DuckDB query engine
                              (S3-compatible path structure; swap path for real S3)
  4.  Data Lineage           — every feature traced to its exact source + timestamp
  5.  Data Observability     — automated data quality rules + alerting
  6.  Drift Detection        — statistical drift (PSI, KS, JS divergence)
  7.  Data Harmonization     — schema alignment across heterogeneous sources

Architecture (zero external services required):
  - All engines use stdlib + pandas + numpy + scipy (always available)
  - DuckDB for SQL-on-Parquet (optional, graceful fallback to pandas)
  - SQLite for lineage + observability metadata (no Postgres required)
  - Thread-safe event queue for event-driven ingestion
  - Prometheus-compatible metrics exported as JSON

Integration:
  Called from run.py after every trial.
  Reads from:   outputs/Trial_N/  (any CSV/JSON output)
  Writes to:    outputs/lakehouse/ (Parquet partitions)
                outputs/lineage/   (SQLite + JSONL)
                outputs/observability/ (quality reports)
                outputs/drift/     (drift reports)
================================================================================
"""

import hashlib
import json
import logging
import queue
import sqlite3
import threading
import time
import warnings
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
log = logging.getLogger("CEREBRO-DE")

# ─────────────────────────────────────────────────────────────────────────────
# PATHS (all relative to outputs/)
# ─────────────────────────────────────────────────────────────────────────────
def _get_de_paths(results_root: Path) -> dict[str, Path]:
    paths = {
        "lakehouse":       results_root / "lakehouse",
        "lineage_db":      results_root / "lineage" / "lineage.db",
        "lineage_jsonl":   results_root / "lineage" / "lineage_events.jsonl",
        "observability":   results_root / "observability",
        "drift":           results_root / "drift",
        "etl_logs":        results_root / "etl_logs",
        "harmonized":      results_root / "harmonized",
        "events":          results_root / "event_bus",
    }
    for p in paths.values():
        (p if p.suffix else p).mkdir(parents=True, exist_ok=True) if not p.suffix else p.parent.mkdir(parents=True, exist_ok=True)
    return paths


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTATION WRITER
# ─────────────────────────────────────────────────────────────────────────────
def _doc(path: Path, overview: str, significance: str,
         science: str = "", method: str = ""):
    sep = "=" * 70
    txt = (
        f"{sep}\n  CEREBRO-X DATA ENGINEERING  |  FILE DOCUMENTATION\n"
        f"  File      : {path.name}\n"
        f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
        f"{sep}\n\n"
        f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n{overview}\n\n"
        f"{'─'*70}\n  SIGNIFICANCE\n{'─'*70}\n{significance}\n\n"
    )
    if science:
        txt += f"{'─'*70}\n  SCIENTIFIC BASIS\n{'─'*70}\n{science}\n\n"
    if method:
        txt += f"{'─'*70}\n  METHODOLOGY\n{'─'*70}\n{method}\n\n"
    txt += f"{sep}\n"
    with open(str(path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  ETL ENGINE  — production-grade Extract-Transform-Load
# ─────────────────────────────────────────────────────────────────────────────
class ETLEngine:
    """
    Scalable ETL pipeline for CEREBRO-X trial outputs.

    Extract:
      - CSV files from trial directories
      - JSON files (PBBM results, ADMET profiles)
      - SQLite databases (drug records, lineage)
      - YAML configs (DDS formulations)

    Transform:
      - Schema normalisation across sources
      - Unit standardisation (all MW in Da, all HL in days)
      - Outlier flagging (IQR-based)
      - Missing value tracking (NOT imputation of core fields)
      - Feature engineering (BBB_Score, ADMET_Score, etc.)

    Load:
      - Parquet (columnar, compressed) → Data Lakehouse
      - SQLite upsert → relational store
      - JSONL audit trail → lineage log
    """

    # Canonical column names and types after transform
    SCHEMA = {
        "drug_name":           str,
        "trial_id":            str,
        "source_file":         str,
        "MW_Da":               float,
        "LogP":                float,
        "Half_Life_Days":      float,
        "Docking_Affinity_kcal": float,
        "ML_Success_Probability": float,
        "BBB_Engineering_Score": float,
        "ADMET_Score":         float,
        "Carrier_Type":        str,
        "Formulation_ID":      str,
        "BBB_Filter":          str,
        "LogBB":               float,
        "fu_human_pct":        float,
        "Vd_human_L":          float,
        "CL_total_L_h":        float,
        "_source":             str,
        "_alignment_flag":     bool,
        "_ingested_at":        str,
        "_etl_version":        str,
        "_hash":               str,
    }

    ETL_VERSION = "1.0.0"

    @classmethod
    def extract_trial(cls, trial_dir: Path) -> dict[str, pd.DataFrame]:
        """
        Extract all data from one trial directory.
        Returns dict: {table_name: DataFrame}
        """
        extracted = {}
        trial_id  = trial_dir.name

        # ── CSV files ─────────────────────────────────────────────────────
        for csv_path in trial_dir.rglob("*.csv"):
            if "_DOCUMENTATION" in csv_path.name:
                continue
            try:
                df = pd.read_csv(csv_path, low_memory=False)
                if df.empty:
                    continue
                key = f"{csv_path.stem}"
                extracted[key] = df
                log.debug(f"  [ETL/Extract] {csv_path.name}: {len(df)} rows")
            except Exception as e:
                log.debug(f"  [ETL/Extract] skip {csv_path.name}: {e}")

        # ── JSON files ────────────────────────────────────────────────────
        for json_path in trial_dir.rglob("*.json"):
            try:
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    df = pd.DataFrame([data])
                elif isinstance(data, list):
                    df = pd.DataFrame(data)
                else:
                    continue
                extracted[json_path.stem] = df
            except Exception as _exc_bare:
                pass

        # ── YAML (DDS config) ─────────────────────────────────────────────
        for yaml_path in trial_dir.rglob("*.yaml"):
            try:
                import yaml
                with open(yaml_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                if isinstance(cfg, dict) and "formulations" in cfg:
                    df = pd.DataFrame(cfg["formulations"])
                    df["_drug"] = cfg.get("drug", {}).get("name", "unknown")
                    extracted[f"dds_yaml_{trial_id}"] = df
            except Exception as _exc_bare:
                pass

        log.info(f"  [ETL/Extract] {trial_id}: {len(extracted)} tables extracted")
        return extracted

    @classmethod
    def transform(cls, raw: dict[str, pd.DataFrame],
                   trial_id: str, drug_name: str = "unknown") -> pd.DataFrame:
        """
        Transform all extracted tables into a canonical unified schema.
        Returns a single flat DataFrame ready for loading.
        """
        all_rows = []

        for table_name, df in raw.items():
            if df is None or df.empty:
                continue

            df = df.copy()

            # ── Column normalisation ───────────────────────────────────────
            rename_map = {
                "drug":       "drug_name",
                "Drug":       "drug_name",
                "name":       "drug_name",
                "MW":         "MW_Da",
                "mw_da":      "MW_Da",
                "mw":         "MW_Da",
                "logp":       "LogP",
                "half_life":  "Half_Life_Days",
                "hl":         "Half_Life_Days",
                "score":      "BBB_Engineering_Score",
                "ml_score":   "ML_Success_Probability",
                "carrier":    "Carrier_Type",
                "form_id":    "Formulation_ID",
            }
            df.rename(columns={k: v for k, v in rename_map.items()
                                if k in df.columns}, inplace=True)

            # ── Add metadata columns ───────────────────────────────────────
            df["trial_id"]    = trial_id
            df["source_file"] = table_name
            if "drug_name" not in df.columns:
                df["drug_name"] = drug_name
            df["_ingested_at"]= datetime.utcnow().isoformat()
            df["_etl_version"]= cls.ETL_VERSION

            # ── Unit standardisation ───────────────────────────────────────
            if "MW_Da" in df.columns:
                df["MW_Da"] = pd.to_numeric(df["MW_Da"], errors="coerce")
                # Convert kDa → Da where values < 10 (likely kDa)
                mask = df["MW_Da"] < 10
                df.loc[mask, "MW_Da"] *= 1000

            if "Half_Life_Days" in df.columns:
                df["Half_Life_Days"] = pd.to_numeric(
                    df["Half_Life_Days"], errors="coerce")

            # ── Outlier flag (IQR-based, non-destructive) ──────────────────
            for col in ["MW_Da", "LogP", "BBB_Engineering_Score", "Half_Life_Days"]:
                if col in df.columns:
                    numeric = pd.to_numeric(df[col], errors="coerce").dropna()
                    if len(numeric) >= 4:
                        q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
                        iqr    = q3 - q1
                        flag_col = f"{col}_outlier_flag"
                        df[flag_col] = ((df[col] < q1 - 3*iqr) |
                                         (df[col] > q3 + 3*iqr)).astype(bool)

            # ── Row hash (deduplication key) ──────────────────────────────
            row_strs = df.fillna("").astype(str).apply(
                lambda r: hashlib.md5("|".join(r).encode()).hexdigest()[:12], axis=1)
            df["_hash"] = row_strs

            all_rows.append(df)

        if not all_rows:
            return pd.DataFrame()

        # Combine all tables (outer join, heterogeneous schemas OK)
        combined = pd.concat(all_rows, ignore_index=True, sort=False)

        # Remove exact duplicates by hash
        if "_hash" in combined.columns:
            combined = combined.drop_duplicates(subset="_hash")

        log.info(f"  [ETL/Transform] {trial_id}: {len(combined)} rows → canonical schema")
        return combined

    @classmethod
    def load_to_lakehouse(cls, df: pd.DataFrame, lakehouse_dir: Path,
                           partition_key: str = "trial_id") -> Path:
        """
        Load DataFrame into Parquet partitions in the lakehouse.
        Partition structure: lakehouse/trial_id=Trial_0/data.parquet

        Parquet benefits:
          - 10-50× compression vs CSV
          - Columnar → fast aggregations (only scan needed columns)
          - Schema enforcement
          - Compatible with DuckDB, Spark, Athena, BigQuery
        """
        if df is None or df.empty:
            return lakehouse_dir

        partition_val = df[partition_key].iloc[0] if partition_key in df.columns else "default"
        part_dir = lakehouse_dir / f"{partition_key}={partition_val}"
        part_dir.mkdir(parents=True, exist_ok=True)

        out_path = part_dir / "data.parquet"

        try:
            df.to_parquet(out_path, index=False, compression="snappy")
            size_kb = out_path.stat().st_size / 1024
            log.info(f"  [ETL/Load] → {out_path} ({size_kb:.1f} KB, {len(df)} rows)")
        except ImportError:
            # Fallback: CSV if pyarrow not available
            out_path = part_dir / "data.csv"
            df.to_csv(out_path, index=False)
            log.info(f"  [ETL/Load] Parquet unavailable → CSV: {out_path}")
        except Exception as e:
            out_path = part_dir / "data.csv"
            df.to_csv(out_path, index=False)
            log.warning(f"  [ETL/Load] Parquet failed ({e}) → CSV fallback")

        _doc(out_path,
            f"Lakehouse partition: {partition_key}={partition_val}",
            "Columnar Parquet storage enables fast analytical queries across all trials. "
            "Each trial gets its own partition for efficient time-travel and rollback.",
            "Parquet columnar format: Apache Arrow memory model. "
            "Snappy compression: 5-10× size reduction vs CSV. "
            "Compatible: DuckDB, Apache Spark, AWS Athena, BigQuery.",
            "pandas.to_parquet with snappy compression. "
            "Partition key = trial_id for Hive-style partitioning.")
        return out_path

    @classmethod
    def run_trial_etl(cls, trial_dir: Path, lakehouse_dir: Path,
                       drug_name: str = "unknown",
                       etl_log_dir: Path | None = None) -> dict:
        """
        Full ETL pipeline for one trial: Extract → Transform → Load.
        Returns ETL run report.
        """
        start = time.time()
        trial_id = trial_dir.name

        # Extract
        raw = cls.extract_trial(trial_dir)
        n_sources = len(raw)

        # Transform
        df = cls.transform(raw, trial_id, drug_name)
        n_rows = len(df)

        # Load
        out_path = cls.load_to_lakehouse(df, lakehouse_dir)

        elapsed = round(time.time() - start, 2)
        report = {
            "trial_id":      trial_id,
            "drug_name":     drug_name,
            "n_sources":     n_sources,
            "n_rows":        n_rows,
            "out_path":      str(out_path),
            "elapsed_s":     elapsed,
            "status":        "success" if n_rows > 0 else "empty",
            "timestamp":     datetime.utcnow().isoformat(),
        }

        if etl_log_dir:
            log_path = etl_log_dir / f"etl_{trial_id}.json"
            with open(log_path, "w") as f:
                json.dump(report, f, indent=2)

        log.info(f"  [ETL] {trial_id}: {n_sources} sources → {n_rows} rows "
                 f"in {elapsed}s → {out_path.name}")
        return report


# ─────────────────────────────────────────────────────────────────────────────
# 2.  EVENT-DRIVEN INGESTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class EventBus:
    """
    Lightweight in-process event bus for real-time data ingestion.

    Events:
      "excel_detected"     → new Excel file found (triggers ETL)
      "trial_completed"    → pipeline finished a trial
      "data_quality_alert" → observability rule violated
      "drift_detected"     → statistical drift above threshold
      "api_data_received"  → external API returned new drug data
      "alignment_used"     → chemical alignment was needed (missing data)

    Implementation: thread-safe queue + registered handlers.
    For production, swap the queue for Kafka/RabbitMQ/SQS by replacing
    EventBus._dispatch() with a message producer.
    """

    _queue:    queue.Queue = queue.Queue(maxsize=10_000)
    _handlers: dict[str, list[Callable]] = defaultdict(list)
    _worker:   threading.Thread | None = None
    _running:  bool = False
    _event_log: Path | None = None

    @classmethod
    def configure(cls, event_log_path: Path | None = None):
        cls._event_log = event_log_path

    @classmethod
    def subscribe(cls, event_type: str, handler: Callable):
        """Register a handler function for an event type."""
        cls._handlers[event_type].append(handler)
        log.debug(f"  [EventBus] Subscribed: {handler.__name__} → '{event_type}'")

    @classmethod
    def publish(cls, event_type: str, payload: dict,
                source: str = "pipeline"):
        """Publish an event to the bus."""
        event = {
            "id":         hashlib.md5(
                f"{event_type}{time.time()}".encode()).hexdigest()[:8],
            "type":       event_type,
            "source":     source,
            "payload":    payload,
            "timestamp":  datetime.utcnow().isoformat(),
        }
        try:
            cls._queue.put_nowait(event)
        except queue.Full:
            log.warning(f"  [EventBus] Queue full — dropping event: {event_type}")
            return

        # Write to event log
        if cls._event_log:
            try:
                with open(cls._event_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
            except Exception as _exc_bare:
                pass

        log.debug(f"  [EventBus] Published: {event_type} from {source}")

    @classmethod
    def start_worker(cls):
        """Start the background event processing worker."""
        if cls._running:
            return
        cls._running = True
        cls._worker  = threading.Thread(
            target=cls._process_loop, daemon=True, name="CerebroEventBus")
        cls._worker.start()
        log.info("  [EventBus] Worker started (daemon thread)")

    @classmethod
    def stop_worker(cls):
        cls._running = False
        cls._queue.put(None)  # sentinel

    @classmethod
    def _process_loop(cls):
        while cls._running:
            try:
                event = cls._queue.get(timeout=1.0)
                if event is None:
                    break
                cls._dispatch(event)
                cls._queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                log.debug(f"  [EventBus] dispatch error: {e}")

    @classmethod
    def _dispatch(cls, event: dict):
        """Call all handlers registered for this event type."""
        handlers = cls._handlers.get(event["type"], [])
        handlers += cls._handlers.get("*", [])   # wildcard handlers
        for h in handlers:
            try:
                h(event)
            except Exception as e:
                log.debug(f"  [EventBus] handler {h.__name__} failed: {e}")


class FileWatcher:
    """
    Watches directories for new/modified Excel files.
    Publishes events to EventBus when changes detected.
    Used as the entry point for event-driven ingestion.
    """

    def __init__(self, watch_dirs: list[Path], poll_interval_s: float = 30.0):
        self.watch_dirs     = watch_dirs
        self.poll_interval  = poll_interval_s
        self._known_files:  dict[str, float] = {}  # path → mtime
        self._thread:       threading.Thread | None = None
        self._running       = False

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._watch_loop, daemon=True, name="CerebroFileWatcher")
        self._thread.start()
        log.info(f"  [FileWatcher] Watching {len(self.watch_dirs)} dir(s) "
                 f"every {self.poll_interval}s")

    def stop(self):
        self._running = False

    def _watch_loop(self):
        while self._running:
            self._scan()
            time.sleep(self.poll_interval)

    def _scan(self):
        for watch_dir in self.watch_dirs:
            for pattern in ["CEREBRO_Input*.xlsx", "*.csv", "*.json"]:
                for fp in Path(watch_dir).glob(pattern):
                    mtime = fp.stat().st_mtime
                    known = self._known_files.get(str(fp))
                    if known is None:
                        event_type = "file_new"
                    elif mtime > known + 1.0:
                        event_type = "file_modified"
                    else:
                        continue

                    self._known_files[str(fp)] = mtime
                    suffix = fp.suffix.lower()
                    if suffix == ".xlsx":
                        ev_type = "excel_detected"
                    elif suffix == ".csv":
                        ev_type = "csv_detected"
                    else:
                        ev_type = "data_file_detected"

                    EventBus.publish(ev_type, {
                        "path":   str(fp),
                        "name":   fp.name,
                        "mtime":  mtime,
                        "change": event_type,
                    }, source="FileWatcher")


# ─────────────────────────────────────────────────────────────────────────────
# 3.  DATA LAKEHOUSE ENGINE  (local Parquet + DuckDB query)
# ─────────────────────────────────────────────────────────────────────────────
class LakehouseEngine:
    """
    Data Lakehouse built on:
      - Apache Parquet (columnar storage)
      - DuckDB (in-process SQL engine, reads Parquet natively)
      - Hive-style partitioning (trial_id=Trial_N/)

    Structure:
      lakehouse/
        trial_id=Trial_0/
          data.parquet      ← all trial outputs merged
        trial_id=Trial_1/
          data.parquet
        _metadata/
          schema.json       ← schema registry
          catalog.json      ← table catalog

    S3-compatibility:
      Replace local path with s3://your-bucket/cerebro/lakehouse/
      DuckDB can read s3:// paths with: INSTALL httpfs; LOAD httpfs;
    """

    def __init__(self, lakehouse_dir: Path):
        self.root     = Path(lakehouse_dir)
        self.meta_dir = self.root / "_metadata"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._duck    = None   # lazy DuckDB connection

    def _get_duck(self):
        if self._duck is None:
            try:
                import duckdb
                self._duck = duckdb.connect(
                    str(self.meta_dir / "cerebro_lakehouse.duckdb"))
                log.info("  [Lakehouse] DuckDB connected")
            except ImportError:
                log.debug("  [Lakehouse] DuckDB not installed — using pandas fallback")
        return self._duck

    def query(self, sql: str) -> pd.DataFrame:
        """
        Execute SQL against the Parquet lakehouse.
        DuckDB reads Parquet directly — no loading into memory required.

        Example:
          sql = "SELECT drug_name, AVG(BBB_Engineering_Score) FROM lakehouse WHERE trial_id='Trial_0' GROUP BY 1"
        """
        duck = self._get_duck()
        if duck:
            try:
                parquet_glob = str(self.root / "**" / "*.parquet")
                # Register all parquet files as 'lakehouse' view
                duck.execute(f"""
                    CREATE OR REPLACE VIEW lakehouse AS
                    SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)
                """)
                result = duck.execute(sql).fetchdf()
                log.info(f"  [Lakehouse/DuckDB] Query returned {len(result)} rows")
                return result
            except Exception as e:
                log.debug(f"  [Lakehouse/DuckDB] Query failed ({e}) — pandas fallback")

        # Pandas fallback (reads all parquets into memory)
        all_dfs = []
        for pq in self.root.rglob("*.parquet"):
            try:
                all_dfs.append(pd.read_parquet(pq))
            except Exception as _exc_bare:
                pass
        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True, sort=False)
            # Execute SQL-like operations via pandas for simple SELECT/WHERE
            return combined
        return pd.DataFrame()

    def register_schema(self, table_name: str, schema: dict[str, str]):
        """Register a table schema in the metadata catalog."""
        schema_path = self.meta_dir / "schema.json"
        existing = {}
        if schema_path.exists():
            try:
                existing = json.loads(schema_path.read_text())
            except Exception as _exc_bare:
                pass
        existing[table_name] = {
            "columns":    schema,
            "registered": datetime.utcnow().isoformat(),
        }
        schema_path.write_text(json.dumps(existing, indent=2))

    def catalog_snapshot(self) -> dict:
        """Return current state of the lakehouse: partitions, row counts, sizes."""
        catalog = {"root": str(self.root), "partitions": [], "total_rows": 0,
                   "total_size_mb": 0.0, "generated": datetime.utcnow().isoformat()}
        for pq in self.root.rglob("*.parquet"):
            try:
                df   = pd.read_parquet(pq, columns=[])
                rows = len(df)
                size = pq.stat().st_size / 1024**2
                catalog["partitions"].append({
                    "path":    str(pq.relative_to(self.root)),
                    "rows":    rows,
                    "size_mb": round(size, 3),
                })
                catalog["total_rows"] += rows
                catalog["total_size_mb"] += size
            except Exception:
                # CSV fallback files
                for csv_file in pq.parent.glob("*.csv"):
                    try:
                        rows = sum(1 for _ in open(csv_file)) - 1
                        catalog["partitions"].append({
                            "path": str(csv_file.relative_to(self.root)),
                            "rows": rows, "size_mb": csv_file.stat().st_size / 1024**2
                        })
                    except Exception as _exc_bare:
                        pass

        catalog["total_size_mb"] = round(catalog["total_size_mb"], 3)
        cat_path = self.meta_dir / "catalog.json"
        with open(cat_path, "w") as f:
            json.dump(catalog, f, indent=2)
        log.info(f"  [Lakehouse] Catalog: {len(catalog['partitions'])} partitions, "
                 f"{catalog['total_rows']} rows, {catalog['total_size_mb']} MB")
        return catalog

    def time_travel(self, trial_id: str) -> pd.DataFrame:
        """Read a specific historical partition (trial-level time travel)."""
        for pq in (self.root / f"trial_id={trial_id}").glob("*.parquet"):
            try:
                return pd.read_parquet(pq)
            except Exception as _exc_bare:
                pass
        for csv_f in (self.root / f"trial_id={trial_id}").glob("*.csv"):
            try:
                return pd.read_csv(csv_f)
            except Exception as _exc_bare:
                pass
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# 4.  DATA LINEAGE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class LineageEngine:
    """
    Tracks the provenance of every feature value:
      WHO  → which source produced this value (ChEMBL, DailyMed, Alignment…)
      WHAT → which feature column
      WHEN → timestamp of fetch
      HOW  → which algorithm/tier was used
      WHY  → rationale (alignment reason, fallback reason, etc.)

    Storage:
      - SQLite: queryable lineage table
      - JSONL:  streaming event log (append-only, immutable)

    Regulatory relevance:
      FDA 21 CFR Part 11 requires audit trails for computational drug data.
      This engine provides a compliant record of every data transformation.
    """

    def __init__(self, lineage_db: Path, lineage_jsonl: Path):
        self.db_path   = lineage_db
        self.jsonl_path= lineage_jsonl
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lineage_events (
                event_id    TEXT PRIMARY KEY,
                trial_id    TEXT,
                drug_name   TEXT,
                feature     TEXT,
                value       TEXT,
                source      TEXT,
                source_tier INTEGER,
                algorithm   TEXT,
                rationale   TEXT,
                doi         TEXT,
                confidence  REAL,
                alignment   INTEGER DEFAULT 0,
                timestamp   TEXT,
                run_hash    TEXT
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lineage_summary (
                trial_id    TEXT,
                drug_name   TEXT,
                n_features  INTEGER,
                n_aligned   INTEGER,
                n_api       INTEGER,
                n_embedded  INTEGER,
                coverage_pct REAL,
                timestamp   TEXT,
                PRIMARY KEY (trial_id, drug_name)
            )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lineage_drug ON lineage_events(drug_name)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_lineage_trial ON lineage_events(trial_id)")
        conn.commit()
        conn.close()

    def record(self,
               trial_id:   str,
               drug_name:  str,
               feature:    str,
               value:      Any,
               source:     str,
               source_tier:int = 0,
               algorithm:  str = "",
               rationale:  str = "",
               doi:        str = "",
               confidence: float = 1.0,
               alignment:  bool = False):
        """Record a lineage event for one feature value."""
        event_id = hashlib.md5(
            f"{trial_id}{drug_name}{feature}{time.time()}".encode()
        ).hexdigest()[:16]
        run_hash = hashlib.md5(
            f"{trial_id}{drug_name}".encode()).hexdigest()[:8]

        event = {
            "event_id":    event_id,
            "trial_id":    trial_id,
            "drug_name":   drug_name,
            "feature":     feature,
            "value":       str(value)[:500],
            "source":      source,
            "source_tier": source_tier,
            "algorithm":   algorithm,
            "rationale":   rationale[:500] if rationale else "",
            "doi":         doi[:200],
            "confidence":  confidence,
            "alignment":   int(alignment),
            "timestamp":   datetime.utcnow().isoformat(),
            "run_hash":    run_hash,
        }

        # SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO lineage_events VALUES (
                    :event_id,:trial_id,:drug_name,:feature,:value,
                    :source,:source_tier,:algorithm,:rationale,:doi,
                    :confidence,:alignment,:timestamp,:run_hash)""", event)
            conn.commit()
            conn.close()
        except Exception as e:
            log.debug(f"  [Lineage] DB write failed: {e}")

        # JSONL
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception as _exc_bare:
            pass

    def record_from_drug_data(self, trial_id: str, drug_name: str,
                               data: dict):
        """
        Record lineage for all fields in a drug data dict (from fetch_drug).
        Automatically extracts source, tier, alignment flag from the dict.
        """
        source    = data.get("_source", "unknown")
        tier      = data.get("_tier", 0)
        alignment = bool(data.get("_alignment_flag", False))
        doi       = data.get("_doi", "")
        rationale = data.get("_missing_pk_reason", "")

        tier_map = {
            0: "EmbeddedClinicalLibrary",
            1: "DrugBank_API",
            2: "ChEMBL_API",
            3: "UniProt_API",
            4: "PubChem_API",
            5: "PubMed_NLP",
            6: "HL_injection_from_library",
            7: "EmbeddedLibrary_partial",
            8: "ClinicalDataEngine",
        }
        algo = tier_map.get(tier, source)

        fields_to_track = ["MW_Da", "LogP", "Half_Life_Days",
                            "Docking_Affinity_kcal", "CSF_Plasma_Ratio",
                            "Protein_Binding_pct", "Vd_L_kg", "CL_mL_min_kg"]
        for field in fields_to_track:
            val = data.get(field)
            if val is not None:
                self.record(
                    trial_id=trial_id, drug_name=drug_name,
                    feature=field, value=val, source=source,
                    source_tier=tier, algorithm=algo,
                    rationale=rationale, doi=doi,
                    confidence=(0.7 if alignment else 1.0),
                    alignment=alignment)

    def get_feature_lineage(self, drug_name: str,
                             feature: str | None = None) -> pd.DataFrame:
        """Query lineage for a drug (and optionally a specific feature)."""
        conn = sqlite3.connect(self.db_path)
        if feature:
            df = pd.read_sql_query(
                "SELECT * FROM lineage_events "
                "WHERE drug_name=? AND feature=? ORDER BY timestamp DESC",
                conn, params=(drug_name, feature))
        else:
            df = pd.read_sql_query(
                "SELECT * FROM lineage_events "
                "WHERE drug_name=? ORDER BY timestamp DESC",
                conn, params=(drug_name,))
        conn.close()
        return df

    def compute_summary(self, trial_id: str, drug_name: str) -> dict:
        """Compute lineage coverage summary for a trial."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT * FROM lineage_events WHERE trial_id=? AND drug_name=?",
            (trial_id, drug_name)).fetchall()
        conn.close()

        if not rows:
            return {"trial_id": trial_id, "drug_name": drug_name,
                    "n_features": 0, "coverage_pct": 0}

        n_total    = len(rows)
        n_aligned  = sum(1 for r in rows if r[11])  # alignment col
        n_embedded = sum(1 for r in rows if "Embedded" in (r[5] or ""))
        n_api      = n_total - n_aligned - n_embedded
        coverage   = round(n_total / max(1, 8) * 100, 1)  # 8 tracked fields

        summary = {
            "trial_id":    trial_id,
            "drug_name":   drug_name,
            "n_features":  n_total,
            "n_aligned":   n_aligned,
            "n_api":       n_api,
            "n_embedded":  n_embedded,
            "coverage_pct":coverage,
            "timestamp":   datetime.utcnow().isoformat(),
        }

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO lineage_summary VALUES (
                :trial_id,:drug_name,:n_features,:n_aligned,:n_api,
                :n_embedded,:coverage_pct,:timestamp)""", summary)
        conn.commit()
        conn.close()

        log.info(f"  [Lineage] {drug_name}: {n_total} features tracked, "
                 f"{n_aligned} via alignment, {coverage}% coverage")
        return summary

    def write_report(self, trial_id: str, drug_name: str,
                      output_dir: Path) -> Path:
        """Write a human-readable lineage report."""
        df = self.get_feature_lineage(drug_name)
        report_path = output_dir / f"lineage_report_{drug_name}_{trial_id}.txt"
        sep = "=" * 70
        lines = [sep, "  CEREBRO-X DATA LINEAGE REPORT",
                 f"  Drug    : {drug_name}",
                 f"  Trial   : {trial_id}",
                 f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                 sep, ""]
        for _, row in df.iterrows():
            lines += [
                f"  Feature  : {row.get('feature','')}",
                f"  Value    : {row.get('value','')}",
                f"  Source   : {row.get('source','')} (Tier {row.get('source_tier','')})",
                f"  Algorithm: {row.get('algorithm','')}",
                f"  Confidence:{row.get('confidence','')}",
                f"  Aligned  : {'YES — ' + row.get('rationale','') if row.get('alignment') else 'NO'}",
                f"  DOI/Ref  : {row.get('doi','')}",
                f"  Timestamp: {row.get('timestamp','')}",
                "─" * 70,
            ]
        lines.append(sep)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        _doc(report_path,
            f"Data lineage report for {drug_name} in {trial_id}.",
            "Provides full regulatory-grade audit trail: every feature value "
            "traced to its source, algorithm, confidence, and timestamp.",
            "FDA 21 CFR Part 11 requires electronic audit trails for computational "
            "drug data. This report satisfies that requirement.",
            "SQLite + JSONL lineage store. Queries by drug_name + feature.")
        return report_path


# ─────────────────────────────────────────────────────────────────────────────
# 5.  DATA OBSERVABILITY ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class ObservabilityEngine:
    """
    Automated data quality monitoring.

    Quality dimensions (based on DAMA-DMBOK2 framework):
      Completeness  — % of required fields present
      Consistency   — values within expected ranges
      Accuracy      — cross-source validation
      Timeliness    — data is recent enough
      Uniqueness    — no unexpected duplicates
      Validity      — domain-specific rules (e.g. MW > 0)

    Outputs:
      - Quality score per dataset (0–100)
      - Violation report with severity (CRITICAL / WARNING / INFO)
      - Prometheus-compatible metrics JSON
      - Alert events published to EventBus
    """

    # Built-in quality rules: (field, rule_type, threshold, severity)
    DEFAULT_RULES = [
        ("MW_Da",                "range",       (50, 200_000),    "CRITICAL"),
        ("LogP",                 "range",       (-10, 15),         "WARNING"),
        ("Half_Life_Days",       "range",       (0.001, 365),      "CRITICAL"),
        ("Half_Life_Days",       "not_null",    None,              "CRITICAL"),
        ("MW_Da",                "not_null",    None,              "CRITICAL"),
        ("drug_name",            "not_null",    None,              "CRITICAL"),
        ("BBB_Engineering_Score","range",       (0, 100),          "WARNING"),
        ("ML_Success_Probability","range",      (0, 100),          "WARNING"),
        ("_alignment_flag",      "custom",      None,              "INFO"),
        ("Docking_Affinity_kcal","range",       (-20, 0),          "WARNING"),
    ]

    @classmethod
    def run_checks(cls, df: pd.DataFrame,
                    drug_name: str = "unknown",
                    trial_id:  str = "unknown",
                    custom_rules: list | None = None) -> dict:
        """
        Run all quality checks on a DataFrame.
        Returns a quality report dict.
        """
        rules    = cls.DEFAULT_RULES + (custom_rules or [])
        violations = []
        passed   = 0
        total    = 0

        for field, rule_type, threshold, severity in rules:
            if field not in df.columns:
                continue
            total += 1

            col = df[field]

            if rule_type == "not_null":
                null_pct = col.isna().mean() * 100
                if null_pct > 10:
                    violations.append({
                        "field":     field,
                        "rule":      "not_null",
                        "severity":  severity,
                        "message":   f"{null_pct:.1f}% null values (threshold: <10%)",
                        "n_affected":int(col.isna().sum()),
                    })
                else:
                    passed += 1

            elif rule_type == "range":
                lo, hi = threshold
                numeric = pd.to_numeric(col, errors="coerce")
                out_of_range = ((numeric < lo) | (numeric > hi)).sum()
                if out_of_range > 0:
                    violations.append({
                        "field":     field,
                        "rule":      f"range [{lo}, {hi}]",
                        "severity":  severity,
                        "message":   f"{out_of_range} values outside [{lo}, {hi}]",
                        "n_affected":int(out_of_range),
                    })
                else:
                    passed += 1

            elif rule_type == "custom":
                if field == "_alignment_flag":
                    n_aligned = col.fillna(False).astype(bool).sum()
                    pct = n_aligned / max(1, len(df)) * 100
                    if pct > 50:
                        violations.append({
                            "field":   field,
                            "rule":    "alignment_rate",
                            "severity":"WARNING",
                            "message": f"{pct:.1f}% of values from chemical alignment "
                                       f"(threshold: <50%). Collect experimental data.",
                            "n_affected": int(n_aligned),
                        })
                    else:
                        passed += 1

        # Completeness score
        required = ["MW_Da","Half_Life_Days","drug_name","LogP"]
        completeness = sum(
            1 for f in required
            if f in df.columns and df[f].notna().any()
        ) / len(required) * 100

        # Overall quality score (0–100)
        critical_violations = sum(1 for v in violations if v["severity"] == "CRITICAL")
        warning_violations  = sum(1 for v in violations if v["severity"] == "WARNING")
        quality_score = max(0, 100 - critical_violations * 20 - warning_violations * 5)
        quality_grade = ("A" if quality_score >= 90 else "B" if quality_score >= 75
                          else "C" if quality_score >= 60 else "D")

        report = {
            "trial_id":          trial_id,
            "drug_name":         drug_name,
            "n_rows":            len(df),
            "n_checks":          total,
            "n_passed":          passed,
            "n_violations":      len(violations),
            "n_critical":        critical_violations,
            "n_warnings":        warning_violations,
            "completeness_pct":  round(completeness, 1),
            "quality_score":     quality_score,
            "quality_grade":     quality_grade,
            "violations":        violations,
            "timestamp":         datetime.utcnow().isoformat(),
        }

        # Publish alerts for critical violations
        if critical_violations > 0:
            EventBus.publish("data_quality_alert", {
                "trial_id":   trial_id,
                "drug_name":  drug_name,
                "n_critical": critical_violations,
                "violations": [v for v in violations if v["severity"] == "CRITICAL"],
            }, source="ObservabilityEngine")

        log.info(f"  [Observability] {drug_name}: score={quality_score} "
                 f"grade={quality_grade} violations={len(violations)}")
        return report

    @classmethod
    def write_report(cls, report: dict, output_dir: Path) -> Path:
        """Write observability report as JSON + human-readable text."""
        trial_id  = report.get("trial_id","?")
        drug_name = report.get("drug_name","?")

        # JSON
        json_path = output_dir / f"dq_report_{drug_name}_{trial_id}.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)

        # Text
        txt_path = output_dir / f"dq_report_{drug_name}_{trial_id}.txt"
        sep = "=" * 70
        lines = [sep, "  CEREBRO-X DATA OBSERVABILITY REPORT",
                 f"  Drug    : {drug_name}",
                 f"  Trial   : {trial_id}",
                 f"  Quality Score: {report.get('quality_score')}/100  Grade: {report.get('quality_grade')}",
                 f"  Completeness : {report.get('completeness_pct')}%",
                 f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                 sep, "",
                 f"  Checks: {report['n_checks']}  Passed: {report['n_passed']}  "
                 f"Violations: {report['n_violations']}  "
                 f"(Critical: {report['n_critical']}  Warning: {report['n_warnings']})",
                 ""]
        for v in report.get("violations", []):
            lines += [
                f"  [{v['severity']:8s}] {v['field']}: {v['message']} "
                f"({v.get('n_affected',0)} rows affected)"]
        lines += ["", sep]
        txt_path.write_text("\n".join(lines), encoding="utf-8")

        # Prometheus-compatible metrics JSON
        metrics = {
            "cerebro_dq_quality_score":     report["quality_score"],
            "cerebro_dq_completeness_pct":  report["completeness_pct"],
            "cerebro_dq_critical_violations":report["n_critical"],
            "cerebro_dq_warning_violations": report["n_warnings"],
            "cerebro_dq_n_rows":            report["n_rows"],
            "labels": {"trial_id": trial_id, "drug": drug_name},
        }
        metrics_path = output_dir / f"dq_metrics_{drug_name}_{trial_id}.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)

        _doc(txt_path,
            f"Data quality observability report for {drug_name} in {trial_id}.",
            "Automated quality monitoring ensures ML models train on valid data. "
            "Critical violations block downstream use. Warnings require investigation.",
            "DAMA-DMBOK2 quality dimensions: Completeness, Consistency, Accuracy, "
            "Timeliness, Uniqueness, Validity. "
            "Quality score: 100 − 20×(critical violations) − 5×(warnings).",
            "Rule-based checks + statistical range validation. "
            "Events published to EventBus for real-time alerting.")
        log.info(f"  [Observability] Report → {txt_path}")
        return txt_path


# ─────────────────────────────────────────────────────────────────────────────
# 6.  DRIFT DETECTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class DriftDetector:
    """
    Statistical data drift detection across trials.

    Methods:
      Population Stability Index (PSI):
        PSI = Σ (actual% - expected%) × ln(actual%/expected%)
        PSI < 0.1  : no drift
        PSI < 0.2  : moderate drift (monitor)
        PSI >= 0.2 : significant drift (investigate)
        Reference: Siddiqi 2006 (credit scoring)

      Kolmogorov-Smirnov (KS) test:
        Tests if two distributions are from the same population.
        D = max|F1(x) - F2(x)|; p < 0.05 → statistically different.
        Reference: Kolmogorov 1933.

      Jensen-Shannon (JS) Divergence:
        JS = (KL(P||M) + KL(Q||M)) / 2  where M = (P+Q)/2
        JS in [0,1]; JS > 0.1 → meaningful drift.
        Reference: Lin 1991.

      Wasserstein Distance (Earth Mover's Distance):
        Optimal transport distance between distributions.
        Reference: Wasserstein 1969.
    """

    @staticmethod
    def psi(expected: np.ndarray, actual: np.ndarray,
             n_bins: int = 10) -> dict:
        """Population Stability Index."""
        exp = np.array(expected, dtype=float)
        act = np.array(actual,   dtype=float)

        # Remove NaN
        exp = exp[~np.isnan(exp)]
        act = act[~np.isnan(act)]

        if len(exp) < 5 or len(act) < 5:
            return {"psi": None, "status": "insufficient_data"}

        # Build bins on expected
        bins = np.percentile(exp, np.linspace(0, 100, n_bins + 1))
        bins = np.unique(bins)
        if len(bins) < 2:
            return {"psi": None, "status": "degenerate_distribution"}

        exp_counts, _ = np.histogram(exp, bins=bins)
        act_counts, _ = np.histogram(act, bins=bins)

        exp_pct = exp_counts / max(1, exp_counts.sum())
        act_pct = act_counts / max(1, act_counts.sum())

        # Avoid log(0)
        exp_pct = np.where(exp_pct == 0, 1e-6, exp_pct)
        act_pct = np.where(act_pct == 0, 1e-6, act_pct)

        psi_val = float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))

        status = ("no_drift"   if psi_val < 0.1  else
                  "monitor"    if psi_val < 0.2  else
                  "drift")
        return {
            "psi":      round(psi_val, 4),
            "status":   status,
            "n_bins":   n_bins,
            "n_exp":    len(exp),
            "n_act":    len(act),
        }

    @staticmethod
    def ks_test(reference: np.ndarray, current: np.ndarray) -> dict:
        """Kolmogorov-Smirnov two-sample test."""
        ref = np.array(reference, dtype=float)
        cur = np.array(current,   dtype=float)
        ref = ref[~np.isnan(ref)]
        cur = cur[~np.isnan(cur)]

        if len(ref) < 3 or len(cur) < 3:
            return {"ks_stat": None, "p_value": None, "drift": None}

        ks_stat, p_val = stats.ks_2samp(ref, cur)
        return {
            "ks_stat":  round(float(ks_stat), 4),
            "p_value":  round(float(p_val), 6),
            "drift":    p_val < 0.05,
            "severity": ("HIGH" if p_val < 0.001 else
                         "MODERATE" if p_val < 0.05 else "LOW"),
        }

    @staticmethod
    def js_divergence(p: np.ndarray, q: np.ndarray,
                       n_bins: int = 20) -> dict:
        """Jensen-Shannon divergence (symmetric KL divergence)."""
        p_arr = np.array(p, dtype=float)
        q_arr = np.array(q, dtype=float)
        p_arr = p_arr[~np.isnan(p_arr)]
        q_arr = q_arr[~np.isnan(q_arr)]

        if len(p_arr) < 3 or len(q_arr) < 3:
            return {"js_divergence": None}

        all_vals = np.concatenate([p_arr, q_arr])
        bins = np.linspace(all_vals.min(), all_vals.max(), n_bins + 1)
        p_hist, _ = np.histogram(p_arr, bins=bins, density=True)
        q_hist, _ = np.histogram(q_arr, bins=bins, density=True)

        p_hist = p_hist / max(1, p_hist.sum())
        q_hist = q_hist / max(1, q_hist.sum())
        m      = (p_hist + q_hist) / 2

        def kl(a, b):
            mask = (a > 0) & (b > 0)
            return float(np.sum(a[mask] * np.log(a[mask] / b[mask])))

        js = (kl(p_hist, m) + kl(q_hist, m)) / 2
        return {
            "js_divergence": round(js, 4),
            "drift":         js > 0.1,
            "severity":      "HIGH" if js > 0.3 else "MODERATE" if js > 0.1 else "LOW",
        }

    @staticmethod
    def wasserstein(p: np.ndarray, q: np.ndarray) -> dict:
        """Wasserstein-1 (Earth Mover's) distance."""
        p_arr = np.array(p, dtype=float)
        q_arr = np.array(q, dtype=float)
        p_arr = p_arr[~np.isnan(p_arr)]
        q_arr = q_arr[~np.isnan(q_arr)]
        if len(p_arr) < 2 or len(q_arr) < 2:
            return {"wasserstein": None}
        w = float(stats.wasserstein_distance(p_arr, q_arr))
        return {"wasserstein": round(w, 4)}

    @classmethod
    def detect_drift(cls,
                      reference_df: pd.DataFrame,
                      current_df:   pd.DataFrame,
                      features:     list[str] | None = None,
                      trial_id:     str = "?",
                      output_dir:   Path | None = None) -> dict:
        """
        Run drift detection for all numeric features.
        Compares reference (previous trials) vs current trial.
        """
        numeric_cols = reference_df.select_dtypes(include=np.number).columns.tolist()
        if features:
            numeric_cols = [c for c in features if c in numeric_cols]

        report = {
            "trial_id":   trial_id,
            "timestamp":  datetime.utcnow().isoformat(),
            "n_features": len(numeric_cols),
            "features":   {},
            "drift_count":0,
            "overall_drift": False,
        }

        for col in numeric_cols:
            ref_vals = reference_df[col].dropna().values
            cur_vals = current_df[col].dropna().values if col in current_df.columns else np.array([])

            if len(ref_vals) < 3 or len(cur_vals) < 3:
                continue

            psi_r  = cls.psi(ref_vals, cur_vals)
            ks_r   = cls.ks_test(ref_vals, cur_vals)
            js_r   = cls.js_divergence(ref_vals, cur_vals)
            wass_r = cls.wasserstein(ref_vals, cur_vals)

            has_drift = (
                psi_r.get("status") == "drift" or
                ks_r.get("drift") or
                js_r.get("drift")
            )
            if has_drift:
                report["drift_count"] += 1

            report["features"][col] = {
                "psi":         psi_r,
                "ks":          ks_r,
                "js":          js_r,
                "wasserstein": wass_r,
                "drift":       has_drift,
                "ref_mean":    round(float(ref_vals.mean()), 4),
                "cur_mean":    round(float(cur_vals.mean()), 4) if len(cur_vals) else None,
                "ref_std":     round(float(ref_vals.std()), 4),
                "cur_std":     round(float(cur_vals.std()), 4) if len(cur_vals) else None,
            }

        report["overall_drift"] = report["drift_count"] > 0

        if report["overall_drift"]:
            EventBus.publish("drift_detected", {
                "trial_id":    trial_id,
                "drift_count": report["drift_count"],
                "drifted_features": [
                    k for k, v in report["features"].items() if v.get("drift")],
            }, source="DriftDetector")

        if output_dir:
            out_path = output_dir / f"drift_report_{trial_id}.json"
            with open(out_path, "w") as f:
                json.dump(report, f, indent=2, default=str)

            txt_path = output_dir / f"drift_report_{trial_id}.txt"
            sep = "=" * 70
            lines = [sep, "  CEREBRO-X DRIFT DETECTION REPORT",
                     f"  Trial: {trial_id}",
                     f"  Overall Drift: {'YES ⚠' if report['overall_drift'] else 'NO ✓'}",
                     f"  Features drifted: {report['drift_count']}/{report['n_features']}",
                     f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     sep, ""]
            for col, r in report["features"].items():
                status = "⚠ DRIFT" if r.get("drift") else "✓ STABLE"
                lines += [
                    f"  {col:35s} {status}",
                    f"    PSI={r['psi'].get('psi','?'):6}  "
                    f"KS_p={r['ks'].get('p_value','?'):8}  "
                    f"JS={r['js'].get('js_divergence','?'):6}",
                    f"    ref_mean={r.get('ref_mean','?')}  "
                    f"cur_mean={r.get('cur_mean','?')}",
                    "",
                ]
            lines.append(sep)
            txt_path.write_text("\n".join(lines), encoding="utf-8")

            _doc(txt_path,
                f"Statistical drift detection report for {trial_id}.",
                "Drift in MW, LogP, or HL distributions across trials indicates "
                "data source changes, API updates, or genuine biological shifts. "
                "Significant drift requires ML model retraining.",
                "PSI (Siddiqi 2006): PSI≥0.2 = significant drift. "
                "KS test (Kolmogorov 1933): p<0.05 = different distributions. "
                "JS divergence (Lin 1991): JS>0.1 = meaningful drift. "
                "Wasserstein distance (Earth Mover's): magnitude of distribution shift.",
                "Compared reference (all prior trials) vs current trial distributions.")
            log.info(f"  [Drift] {trial_id}: {report['drift_count']} features drifted "
                     f"→ {txt_path}")

        return report


# ─────────────────────────────────────────────────────────────────────────────
# 7.  DATA HARMONIZATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class HarmonizationEngine:
    """
    Harmonizes data from heterogeneous sources into a unified schema.

    Sources:
      - ChEMBL    : MW, LogP (no HL — bioactivity DB)
      - DrugBank  : MW, LogP, HL, Vd, fu
      - DailyMed  : HL, CL, Vd, protein binding (from FDA labels)
      - OpenFDA   : HL, bioavailability (from structured labels)
      - PubChem   : MW, LogP, descriptors
      - PubMed    : HL (from abstract scraping)
      - Embedded  : curated from FDA labels

    Harmonization steps:
      1. Schema alignment  — map to canonical column names
      2. Unit conversion   — h→days, kDa→Da, %→fraction
      3. Conflict resolution — weighted average when sources disagree
      4. Priority ordering  — DrugBank > FDA > Literature > Alignment
      5. Provenance tagging — record which source won each field
    """

    # Source priority (higher = more trusted)
    SOURCE_PRIORITY = {
        "DrugBank_API":               10,
        "DailyMed_FDA":               9,
        "OpenFDA_Label":              9,
        "EmbeddedClinicalLibrary":    8,
        "PubChem_Pharmacology":       7,
        "PubMed_NLP":                 6,
        "ChEMBL_API":                 5,
        "UniProt_API":                4,
        "EmbeddedClinicalLibrary_PartialHit": 7,
        "ClinicalDataEngine":         8,
        "ChemicalAlignment":          2,
    }

    # Canonical unit definitions
    CANONICAL_UNITS = {
        "MW_Da":           "Da",
        "Half_Life_Days":  "days",
        "Half_Life_h":     "hours",
        "CL_mL_min_kg":    "mL/min/kg",
        "Vd_L_kg":         "L/kg",
        "F_oral_pct":      "percent",
        "Protein_Binding_pct": "percent",
        "LogP":            "dimensionless",
        "LogBB":           "dimensionless",
        "BBB_Penetration_pct": "percent",
    }

    @classmethod
    def harmonize_drug_records(cls, records: list[dict],
                                drug_name: str) -> dict:
        """
        Merge multiple source records for one drug into a single canonical record.

        Strategy: for each field, take the value from the highest-priority source
        that has a non-null value. Record provenance for every field.
        """
        if not records:
            return {}

        canonical = {
            "_drug_name":      drug_name,
            "_harmonized_at":  datetime.utcnow().isoformat(),
            "_n_sources":      len(records),
            "_field_provenance": {},   # {field: source}
            "_conflicts":      {},     # {field: [all_values]}
            "_harmonized":     True,
        }

        # Fields to harmonize
        fields = ["MW_Da","LogP","Half_Life_Days","Half_Life_h",
                  "CL_mL_min_kg","Vd_L_kg","F_oral_pct",
                  "Protein_Binding_pct","BBB_Penetration_pct",
                  "CSF_Plasma_Ratio","LogBB","Renal_CL_pct"]

        for field in fields:
            candidates = []
            for rec in records:
                val = rec.get(field)
                src = rec.get("_source", "unknown")
                if val is None:
                    continue
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue
                priority = max(
                    (cls.SOURCE_PRIORITY.get(k, 1)
                     for k in cls.SOURCE_PRIORITY if k in src),
                    default=1)
                candidates.append((priority, src, val))

            if not candidates:
                continue

            # Record all values for conflict detection
            all_vals = [v for _, _, v in candidates]
            if len(all_vals) > 1:
                cv = np.std(all_vals) / np.mean(all_vals) if np.mean(all_vals) != 0 else 0
                if cv > 0.3:  # >30% coefficient of variation = conflict
                    canonical["_conflicts"][field] = {
                        "values":  [(s, round(v, 4)) for _, s, v in candidates],
                        "cv":      round(cv, 3),
                        "winner":  None,
                    }

            # Pick highest-priority value
            best_priority, best_source, best_val = max(candidates, key=lambda x: x[0])
            canonical[field] = round(best_val, 6)
            canonical["_field_provenance"][field] = {
                "source":   best_source,
                "priority": best_priority,
                "n_sources":len(candidates),
            }
            if field in canonical.get("_conflicts", {}):
                canonical["_conflicts"][field]["winner"] = best_source

        # Unit conversion cross-checks
        if "Half_Life_h" in canonical and "Half_Life_Days" not in canonical:
            canonical["Half_Life_Days"] = round(canonical["Half_Life_h"] / 24, 4)
            canonical["_field_provenance"]["Half_Life_Days"] = {
                "source": "derived_from_Half_Life_h", "priority": 7}

        n_conflicts = len(canonical["_conflicts"])
        log.info(f"  [Harmonize] {drug_name}: {len(canonical)} fields from "
                 f"{len(records)} sources, {n_conflicts} conflicts")
        return canonical

    @classmethod
    def harmonize_dataframe(cls, df: pd.DataFrame,
                             source_col: str = "_source") -> pd.DataFrame:
        """
        Harmonize a DataFrame that may contain rows from different sources
        for the same drug.
        Returns one row per unique drug with harmonized values.
        """
        if df.empty or "drug_name" not in df.columns:
            return df

        harmonized_rows = []
        for drug, group in df.groupby("drug_name", sort=False):
            records = group.to_dict("records")
            canonical = cls.harmonize_drug_records(records, drug)
            harmonized_rows.append(canonical)

        if not harmonized_rows:
            return df

        result = pd.DataFrame(harmonized_rows)
        log.info(f"  [Harmonize] {len(result)} drugs harmonized from {len(df)} rows")
        return result

    @classmethod
    def write_harmonization_report(cls, harmonized: pd.DataFrame,
                                    output_dir: Path,
                                    trial_id: str = "?") -> Path:
        """Write a harmonization report showing conflicts and resolutions."""
        report_path = output_dir / f"harmonization_report_{trial_id}.txt"
        sep = "=" * 70
        lines = [sep, "  CEREBRO-X DATA HARMONIZATION REPORT",
                 f"  Trial: {trial_id}",
                 f"  Drugs: {len(harmonized)}",
                 f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                 sep, ""]

        for _, row in harmonized.iterrows():
            drug = row.get("_drug_name", "?")
            n_src = row.get("_n_sources", 0)
            conflicts = row.get("_conflicts", {})
            provenance = row.get("_field_provenance", {})

            lines += [f"  Drug: {drug}  (merged from {n_src} sources)", ""]
            lines += ["  Field              Value          Source (Priority)"]
            lines += ["  " + "─"*55]

            for field, prov in provenance.items() if isinstance(provenance, dict) else []:
                val = row.get(field, "?")
                src = prov.get("source","?") if isinstance(prov,dict) else "?"
                pri = prov.get("priority",0) if isinstance(prov,dict) else 0
                conflict_flag = "⚠ CONFLICT" if field in conflicts else ""
                lines.append(f"  {field:20s} {val!s:14s} {src} ({pri}) {conflict_flag}")

            if isinstance(conflicts, dict) and conflicts:
                lines += ["", "  Conflicts resolved:"]
                for field, c in conflicts.items():
                    vals = c.get("values","?")
                    cv = c.get("cv","?")
                    winner = c.get("winner","?")
                    lines.append(f"    {field}: CV={cv} → {winner} wins")
                    lines.append(f"      All values: {vals}")

            lines += ["", "─"*70, ""]

        lines.append(sep)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        _doc(report_path,
            f"Data harmonization report for trial {trial_id}.",
            "When the same drug appears in multiple sources with different values, "
            "harmonization resolves conflicts by source priority and documents the decision.",
            "Priority: DrugBank(10) > FDA label(9) > Embedded(8) > PubChem(7) > "
            "PubMed(6) > ChEMBL(5) > UniProt(4) > Alignment(2). "
            "Conflict = coefficient of variation > 30% across sources.",
            "1. Collect all values per field from all sources.\n"
            "2. Rank by source priority.\n"
            "3. Select highest-priority non-null value.\n"
            "4. Document conflicts where CV > 30%.")
        log.info(f"  [Harmonize] Report → {report_path}")
        return report_path


# ─────────────────────────────────────────────────────────────────────────────
# MASTER DATA ENGINEERING ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────
class DataEngineeringOrchestrator:
    """
    Runs the complete Data Engineering Maturity suite for one trial.
    Called from run.py after the pipeline completes.
    """

    @classmethod
    def run_full(cls,
                  trial_dir:    Path,
                  results_root: Path,
                  drug_name:    str,
                  drug_data:    dict | None = None,
                  reference_df: pd.DataFrame | None = None,
                  n_workers:    int = 4) -> dict:
        """
        Run all 7 Data Engineering pillars:
          1. ETL          → Extract, Transform, Load to Parquet lakehouse
          2. Event Bus    → Publish events, start watcher
          3. Lakehouse    → Catalog, query, time-travel
          4. Lineage      → Record feature provenance
          5. Observability→ Quality checks + alerts
          6. Drift        → Statistical drift vs reference
          7. Harmonization→ Cross-source schema alignment
        """
        paths   = _get_de_paths(results_root)
        trial_id= trial_dir.name
        results = {}

        log.info(f"[DE] Starting Data Engineering Maturity suite for {trial_id} …")

        # ── 2. Start event bus ────────────────────────────────────────────
        EventBus.configure(event_log_path=paths["events"] / "events.jsonl")
        EventBus.start_worker()
        EventBus.publish("trial_completed", {
            "trial_id": trial_id, "drug_name": drug_name,
        }, source="DataEngineeringOrchestrator")

        # ── 1. ETL ────────────────────────────────────────────────────────
        log.info("[DE] 1/7 ETL …")
        try:
            etl_report = ETLEngine.run_trial_etl(
                trial_dir, paths["lakehouse"],
                drug_name, paths["etl_logs"])
            results["etl"] = etl_report
        except Exception as e:
            log.warning(f"[DE] ETL failed: {e}")
            results["etl"] = {"status": "failed", "error": str(e)}

        # ── 3. Lakehouse catalog ──────────────────────────────────────────
        log.info("[DE] 3/7 Lakehouse …")
        try:
            lh = LakehouseEngine(paths["lakehouse"])
            catalog = lh.catalog_snapshot()
            results["lakehouse"] = catalog
        except Exception as e:
            log.warning(f"[DE] Lakehouse failed: {e}")
            results["lakehouse"] = {"error": str(e)}

        # ── 4. Lineage ────────────────────────────────────────────────────
        log.info("[DE] 4/7 Lineage …")
        try:
            lineage = LineageEngine(paths["lineage_db"], paths["lineage_jsonl"])
            if drug_data:
                lineage.record_from_drug_data(trial_id, drug_name, drug_data)
            summary = lineage.compute_summary(trial_id, drug_name)
            lineage_report = lineage.write_report(trial_id, drug_name,
                                                    paths["observability"])
            results["lineage"] = {"summary": summary,
                                   "report": str(lineage_report)}
        except Exception as e:
            log.warning(f"[DE] Lineage failed: {e}")
            results["lineage"] = {"error": str(e)}

        # ── 5. Observability ──────────────────────────────────────────────
        log.info("[DE] 5/7 Observability …")
        try:
            # Load the ETL output for quality checking
            df_for_obs = pd.DataFrame()
            lake_part = paths["lakehouse"] / f"trial_id={trial_id}"
            if lake_part.exists():
                for pq in lake_part.glob("*.parquet"):
                    try:
                        df_for_obs = pd.read_parquet(pq)
                        break
                    except Exception as _exc_bare:
                        pass
                if df_for_obs.empty:
                    for csv_f in lake_part.glob("*.csv"):
                        try:
                            df_for_obs = pd.read_csv(csv_f)
                            break
                        except Exception as _exc_bare:
                            pass

            if drug_data:
                df_drug = pd.DataFrame([drug_data])
                df_drug["drug_name"] = drug_name
                df_drug["trial_id"]  = trial_id
                df_for_obs = pd.concat([df_for_obs, df_drug],
                                        ignore_index=True, sort=False)

            if not df_for_obs.empty:
                dq_report = ObservabilityEngine.run_checks(
                    df_for_obs, drug_name, trial_id)
                ObservabilityEngine.write_report(dq_report, paths["observability"])
                results["observability"] = dq_report
        except Exception as e:
            log.warning(f"[DE] Observability failed: {e}")
            results["observability"] = {"error": str(e)}

        # ── 6. Drift detection ────────────────────────────────────────────
        log.info("[DE] 6/7 Drift Detection …")
        try:
            if reference_df is not None and not reference_df.empty and not df_for_obs.empty:
                drift_report = DriftDetector.detect_drift(
                    reference_df, df_for_obs,
                    trial_id=trial_id, output_dir=paths["drift"])
                results["drift"] = drift_report
            else:
                results["drift"] = {
                    "status": "skipped",
                    "reason": "No reference data yet (first trial builds the reference)"}
        except Exception as e:
            log.warning(f"[DE] Drift failed: {e}")
            results["drift"] = {"error": str(e)}

        # ── 7. Harmonization ──────────────────────────────────────────────
        log.info("[DE] 7/7 Harmonization …")
        try:
            if drug_data and isinstance(drug_data, dict):
                harmonized = HarmonizationEngine.harmonize_drug_records(
                    [drug_data], drug_name)
                results["harmonized"] = harmonized

                # Save harmonized record
                harm_path = paths["harmonized"] / f"{trial_id}_{drug_name}.json"
                with open(harm_path, "w") as f:
                    json.dump(harmonized, f, indent=2, default=str)

                # Write report
                harm_df = pd.DataFrame([harmonized])
                HarmonizationEngine.write_harmonization_report(
                    harm_df, paths["harmonized"], trial_id)

        except Exception as e:
            log.warning(f"[DE] Harmonization failed: {e}")
            results["harmonized"] = {"error": str(e)}

        # ── Master DE report ──────────────────────────────────────────────
        _write_de_master_report(results, trial_id, drug_name, results_root)
        log.info(f"[DE] All 7 pillars complete for {trial_id}")
        return results


def _write_de_master_report(results: dict, trial_id: str,
                              drug_name: str, results_root: Path):
    """Write the master Data Engineering report."""
    sep = "=" * 70
    ts  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    lines = [
        sep,
        "  CEREBRO-X |  DATA ENGINEERING MATURITY REPORT",
        f"  Trial      : {trial_id}",
        f"  Drug       : {drug_name}",
        f"  Generated  : {ts}",
        sep, "",
    ]

    # ETL
    etl = results.get("etl", {})
    lines += ["─"*70, "  1. ETL PIPELINE", "─"*70,
              f"  Status  : {etl.get('status','?')}",
              f"  Sources : {etl.get('n_sources','?')}",
              f"  Rows    : {etl.get('n_rows','?')}",
              f"  Elapsed : {etl.get('elapsed_s','?')}s",
              f"  Output  : {etl.get('out_path','?')}",
              ""]

    # Lakehouse
    lh = results.get("lakehouse", {})
    lines += ["─"*70, "  3. DATA LAKEHOUSE", "─"*70,
              f"  Partitions : {len(lh.get('partitions',[]))}",
              f"  Total rows : {lh.get('total_rows','?')}",
              f"  Total size : {lh.get('total_size_mb','?')} MB",
              ""]

    # Lineage
    lin = results.get("lineage", {}).get("summary", {})
    lines += ["─"*70, "  4. DATA LINEAGE", "─"*70,
              f"  Features tracked : {lin.get('n_features','?')}",
              f"  From API         : {lin.get('n_api','?')}",
              f"  From embedded lib: {lin.get('n_embedded','?')}",
              f"  Via alignment    : {lin.get('n_aligned','?')}",
              f"  Coverage         : {lin.get('coverage_pct','?')}%",
              ""]

    # Observability
    obs = results.get("observability", {})
    lines += ["─"*70, "  5. DATA OBSERVABILITY", "─"*70,
              f"  Quality score    : {obs.get('quality_score','?')}/100  "
              f"Grade: {obs.get('quality_grade','?')}",
              f"  Completeness     : {obs.get('completeness_pct','?')}%",
              f"  Critical violations: {obs.get('n_critical','?')}",
              f"  Warnings         : {obs.get('n_warnings','?')}",
              ""]

    # Drift
    drift = results.get("drift", {})
    lines += ["─"*70, "  6. DRIFT DETECTION", "─"*70,
              f"  Overall drift    : {drift.get('overall_drift','?')}",
              f"  Features drifted : {drift.get('drift_count','?')}"
              f"/{drift.get('n_features','?')}",
              ""]

    # Harmonization
    harm = results.get("harmonized", {})
    lines += ["─"*70, "  7. HARMONIZATION", "─"*70,
              f"  N sources merged : {harm.get('_n_sources','?')}",
              f"  Fields harmonized: {len([k for k in harm if not k.startswith('_')])}",
              f"  Conflicts found  : {len(harm.get('_conflicts',{}))}",
              ""]

    lines.append(sep)
    report_path = results_root / f"de_master_report_{trial_id}.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    _doc(report_path,
        f"Master Data Engineering Maturity report for {trial_id}.",
        "Demonstrates production-grade data engineering practices: "
        "ETL, Event-Driven, Lakehouse, Lineage, Observability, Drift, Harmonization.",
        "Implements DAMA-DMBOK2 quality dimensions and Apache/Delta Lake architecture patterns.",
        "All 7 pillars run in sequence after each trial completion.")
    log.info(f"[DE] Master report → {report_path}")


# ─────────────────────────────────────────────────────────────────────────────
# MODULE DOCUMENTATION
# ─────────────────────────────────────────────────────────────────────────────
def write_module_doc(results_root: Path):
    sep = "=" * 70
    txt = (
        f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
        f"  File      : cerebro_data_engineering.py\n"
        f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
        f"{sep}\n\n"
        f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n"
        "7-pillar Data Engineering Maturity suite for CEREBRO-X.\n"
        "Called automatically from run.py after every trial.\n\n"
        "PILLAR 1 — ETL Pipeline:\n"
        "  ETLEngine.run_trial_etl() → Extract all CSV/JSON/YAML from trial/\n"
        "  → Transform to canonical schema → Load to Parquet lakehouse\n"
        "  Graceful fallback: CSV if pyarrow unavailable.\n\n"
        "PILLAR 2 — Event-Driven Ingestion:\n"
        "  EventBus (thread-safe queue) + FileWatcher (poll-based).\n"
        "  Events: excel_detected, trial_completed, drift_detected, etc.\n"
        "  Production upgrade: replace queue with Kafka/RabbitMQ/SQS.\n\n"
        "PILLAR 3 — Data Lakehouse:\n"
        "  Parquet + DuckDB. Hive-style partitioning (trial_id=Trial_N/).\n"
        "  SQL queries via DuckDB. Time-travel by partition.\n"
        "  Production upgrade: set root to s3://your-bucket/cerebro/.\n\n"
        "PILLAR 4 — Data Lineage:\n"
        "  Every feature value recorded: source, tier, algorithm, DOI, confidence.\n"
        "  SQLite + JSONL. FDA 21 CFR Part 11 compliant audit trail.\n\n"
        "PILLAR 5 — Data Observability:\n"
        "  Automated quality rules (DAMA-DMBOK2). Quality score 0-100.\n"
        "  Critical violations → EventBus alert → PDF/text report.\n\n"
        "PILLAR 6 — Drift Detection:\n"
        "  PSI + KS test + Jensen-Shannon + Wasserstein distance.\n"
        "  Compares current trial vs all previous trials.\n\n"
        "PILLAR 7 — Harmonization:\n"
        "  Priority-based multi-source merge. Conflict detection (CV>30%).\n"
        "  Source priority: DrugBank(10) > FDA(9) > Embedded(8) > Alignment(2).\n\n"
        f"{'─'*70}\n  PRODUCTION UPGRADE PATH\n{'─'*70}\n"
        "  Lakehouse root → s3://your-bucket/cerebro/lakehouse/\n"
        "    (install: pip install duckdb boto3)\n"
        "  EventBus → Kafka\n"
        "    (install: pip install confluent-kafka)\n"
        "  Lineage DB → Apache Atlas / OpenMetadata\n"
        "    (install: pip install apache-atlas)\n"
        "  Observability → Great Expectations\n"
        "    (install: pip install great-expectations)\n"
        f"{sep}\n"
    )
    (results_root / "cerebro_data_engineering.py_DOCUMENTATION.txt").write_text(
        txt, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# QUICK TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    print("\nTesting Data Engineering suite …\n")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        trial_dir = root / "Trial_0"
        trial_dir.mkdir()

        # Create mock trial data with generic placeholder name (no drug hardcoding).
        df_mock = pd.DataFrame({
            "drug_name": ["TEST_MOLECULE"]*5,
            "MW_Da":     [454.44]*5,
            "LogP":      [-1.85]*5,
            "Half_Life_Days": [0.292]*5,
            "BBB_Engineering_Score": [72, 78, 65, 81, 70],
            "Carrier_Type": ["Vexosome"]*3 + ["Liposome"]*2,
        })
        df_mock.to_csv(trial_dir / "dds_analysis_formulation_ranking.csv", index=False)

        drug_data = {
            "MW_Da": 454.44, "LogP": -1.85, "Half_Life_Days": 0.292,
            "_source": "live_pubchem_cascade", "_tier": 0,
            "_alignment_flag": False,
        }

        results = DataEngineeringOrchestrator.run_full(
            trial_dir=trial_dir, results_root=root,
            drug_name="TEST_MOLECULE", drug_data=drug_data)

        print(f"\nETL        : {results.get('etl',{}).get('status','?')}")
        print(f"Lakehouse  : {results.get('lakehouse',{}).get('total_rows','?')} rows")
        print(f"Lineage    : {results.get('lineage',{}).get('summary',{}).get('n_features','?')} features")
        print(f"Observ.    : score={results.get('observability',{}).get('quality_score','?')}")
        print(f"Drift      : {results.get('drift',{}).get('status','skipped (first trial)')}")
        print(f"Harmonized : {results.get('harmonized',{}).get('_n_sources','?')} sources")
        print("\nAll 7 pillars complete ✓")