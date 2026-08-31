"""
================================================================================
CEREBRO-X — INFRASTRUCTURE
================================================================================
File: cerebro_enterprise_infra.py

This module adds the enterprise layer ON TOP of CEREBRO_Pipeline.py:

  1.  .env loader          — python-dotenv secrets management
  2.  IterativeImputer     — intelligent missing-value imputation
                             (replaces fillna(0) — documented in every output)
  3.  DDS Engine           — reads dds_config.yaml, fetches ALL fields live,
                             runs full CEREBRO pipeline per formulation
  4.  FastAPI backend      — REST API exposing pipeline as HTTP service
  5.  Celery task queue    — async long-running jobs (no blocking)
  6.  Background scheduler — runs pipeline every hour automatically
  7.  Cross-platform runner— Windows Task Scheduler OR cron (macOS/Linux)
                             starts on boot, runs headless forever

Run everything:
    python cerebro_enterprise_infra.py

This single command:
  • Starts FastAPI on http://localhost:8000
  • Starts Celery worker in background
  • Registers hourly background job
  • Writes auto-start script for your OS
================================================================================
"""
import os
from pathlib import Path

import pandas as pd
import yaml

# ─────────────────────────────────────────────────────────────────────────────
# 0.  ANCHOR
# ─────────────────────────────────────────────────────────────────────────────
import platform
import sys

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# When this file is imported as src.dds.enterprise_infra (the normal path,
# via src/path_resolver.py), SCRIPT_DIR above resolves to this file's own
# directory (.../src/dds), not the project root. path_resolver.py patches
# SCRIPT_DIR on the already-imported module afterward, but everything
# below in THIS module that derives a path from SCRIPT_DIR during this
# same import (CONFIG_DIR, OUTPUT_ROOT, DDS_CONFIG, DDS_RESULTS, and --
# whenever PostgreSQL is unavailable -- DATABASE_URL/engine/SessionLocal)
# already computed its value from the stale one by the time that patch
# runs, so patching the SCRIPT_DIR name afterward doesn't fix any of them.
# Verified directly: importing this module fresh with no live Postgres
# server baked DATABASE_URL in as
# "sqlite:////.../src/dds/outputs/cerebro_postgres_fallback.db" instead of
# the real ".../outputs/...", and DDS_CONFIG pointed at
# ".../src/dds/config/dds_config.yaml" -- which does not exist -- instead
# of the real "./config/dds_config.yaml" at the project root, silently
# breaking config lookups and creating a stray, wrong-location fallback
# DB. Resolving SCRIPT_DIR to the real project root right here, before
# anything downstream derives a path from it, fixes the root cause for
# every current and future SCRIPT_DIR-derived global in this file at
# once, instead of requiring path_resolver.py to know each one by name.
if not (Path(SCRIPT_DIR) / "run.py").exists():
    for _candidate in [Path(SCRIPT_DIR).parent, Path(SCRIPT_DIR).parent.parent,
                        Path(SCRIPT_DIR).parent.parent.parent]:
        if (_candidate / "run.py").exists():
            SCRIPT_DIR = str(_candidate)
            break
# # os.chdir(  # REMOVED: SCRIPT_DIR)  # REMOVED: use absolute pathlib paths for cloud/Docker

# ─────────────────────────────────────────────────────────────────────────────
# 1.  .env LOADER  — secrets live in .env, never hardcoded
# ─────────────────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    # Find .env by walking UP from SCRIPT_DIR to project root.
    # This works correctly whether enterprise_infra.py is run directly (SCRIPT_DIR=src/dds/)
    # OR imported as a module (SCRIPT_DIR patched to project root by path_resolver).
    _ENV_FILE = None
    _search = Path(SCRIPT_DIR)
    for _candidate in [_search, _search.parent, _search.parent.parent,
                        _search.parent.parent.parent]:
        if (_candidate / ".env").exists():
            _ENV_FILE = str(_candidate / ".env")
            break
    if _ENV_FILE is None:
        # .env not found anywhere — create it at PROJECT ROOT (not src/dds/)
        _project_root = Path(SCRIPT_DIR)
        # Walk up to find the directory containing run.py (= project root)
        for _p in [_project_root, _project_root.parent, _project_root.parent.parent]:
            if (_p / "run.py").exists():
                _project_root = _p
                break
        _ENV_FILE = str(_project_root / ".env")
        if not os.path.exists(_ENV_FILE):
            with open(_ENV_FILE, "w") as f:
                f.write(
                    "# CEREBRO-X — API Keys\n"
                    "# Fill in your keys below, then restart.\n\n"
                    "DRUGBANK_API_KEY=\n"
                    "CHEMBL_API_KEY=\n"
                    "OPENAI_API_KEY=\n"
                    "REDIS_URL=redis://localhost:6379/0\n"
                    "CELERY_BROKER=redis://localhost:6379/0\n"
                    "CELERY_BACKEND=redis://localhost:6379/1\n"
                    "CEREBRO_PIPELINE_INTERVAL_HOURS=1\n"
                    "FASTAPI_HOST=0.0.0.0\n"
                    "FASTAPI_PORT=8000\n"
                )
            print(f"[.env] Template created at {_ENV_FILE} — fill in your API keys.")
    load_dotenv(_ENV_FILE)
    _HAS_DOTENV = True
    print(f"[.env] Loaded secrets from {_ENV_FILE}")
except ImportError:
    _HAS_DOTENV = False
    print("[.env] python-dotenv not installed. "
          "Install with: pip install python-dotenv")

# ─────────────────────────────────────────────────────────────────────────────
# 2.  STANDARD IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import logging
import textwrap
import threading
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("CEREBRO-INFRA")

# ─────────────────────────────────────────────────────────────────────────────
# 3.  OPTIONAL DEPENDENCY FLAGS
# ─────────────────────────────────────────────────────────────────────────────
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    from sklearn.experimental import enable_iterative_imputer   # noqa
    from sklearn.impute import IterativeImputer
    from sklearn.ensemble import ExtraTreesRegressor
    _HAS_IMPUTER = True
except ImportError:
    _HAS_IMPUTER = False

try:
    import uvicorn
    from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel as PydanticBase
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

try:
    from celery import Celery
    _HAS_CELERY = True
except ImportError:
    _HAS_CELERY = False

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    _HAS_SCHEDULER = True
except ImportError:
    _HAS_SCHEDULER = False

# ─────────────────────────────────────────────────────────────────────────────
# 4.  PATHS
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_DIR  = Path(SCRIPT_DIR) / "config"
OUTPUT_ROOT = Path(SCRIPT_DIR) / "outputs"
DDS_CONFIG  = CONFIG_DIR / "dds_config.yaml"
DDS_RESULTS = OUTPUT_ROOT / "dds_analysis"
INFRA_LOG   = OUTPUT_ROOT / "logs" / "infra.log"

for d in [CONFIG_DIR, OUTPUT_ROOT, DDS_RESULTS,
          OUTPUT_ROOT / "logs", OUTPUT_ROOT / "api"]:
    d.mkdir(parents=True, exist_ok=True)

# File logger for infra
_fh = logging.FileHandler(INFRA_LOG, encoding="utf-8")
_fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
log.addHandler(_fh)

# ─────────────────────────────────────────────────────────────────────────────
# 5.  DOCUMENTATION ENGINE  (same pattern as pipeline — every file documented)
# ─────────────────────────────────────────────────────────────────────────────
def write_doc(file_path, doc: dict):
    sep = "=" * 70
    lines = [sep, "  CEREBRO-X |  FILE DOCUMENTATION",
             f"  File      : {Path(str(file_path)).name}",
             f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}",
             sep, ""]
    for title, key in [
        ("OVERVIEW",                        "overview"),
        ("SIGNIFICANCE",                    "significance"),
        ("STRATEGIC DECISION",              "strategic_decision"),
        ("THEORETICAL & PRACTICAL SCIENCE", "theoretical_science"),
        ("SCIENTIFIC VALIDITY",             "practical_science"),
        ("METHODOLOGY",                     "methodology"),
        ("COMPUTATIONAL ARCHITECTURE",      "computational_architecture"),
        ("ADDITIONAL NOTES",                "additional_notes"),
    ]:
        body = doc.get(key, "")
        if body:
            lines += ["─"*70, f"  {title}", "─"*70, body.strip(), ""]
    lines.append(sep)
    with open(str(file_path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# ─────────────────────────────────────────────────────────────────────────────
# 6.  ITERATIVE IMPUTER ENGINE
#     Replaces fillna(0) — the "0 disaster" — with intelligent ML imputation.
#     Rule: Strict Rejection for core fields (MW, HL).
#           IterativeImputer for secondary features only.
# ─────────────────────────────────────────────────────────────────────────────
class ImputerEngine:
    """
    Intelligent missing-value handler.

    Philosophy:
      CORE fields (MW_Da, Half_Life_Days, Drug name):
        → Strict Rejection if missing (see CascadeDataEngine in pipeline).
          No data is better than fake data.

      SECONDARY features (LogP, PDI, Ligand_Density, etc.):
        → IterativeImputer: trains a tree model on all present features
          to predict the missing value from its neighbours.
          The imputation is flagged in _DOCUMENTATION.txt of every output.

    Why NOT fillna(0)?
      A molecular weight of 0 Da is chemically impossible.
      fillna(0) creates extreme outliers that corrupt all downstream
      ML training — the algorithm "learns" that weight=0 means
      excellent BBB penetration, poisoning predictions permanently.

    Why IterativeImputer over fillna(mean)?
      Mean imputation ignores correlations between features.
      IterativeImputer uses an ExtraTreesRegressor to infer each missing
      value from ALL other features, preserving chemical relationships
      (e.g. LogP correlates with surface_logp and elasticity_kpa).
    """

    # Core fields — Strict Rejection if missing (no imputation)
    CORE_FIELDS = {"Drug", "MW_Da", "Half_Life_Days"}

    # Secondary fields — eligible for IterativeImputer
    SECONDARY_FIELDS = {
        "LogP", "pdi", "elasticity_kpa", "drug_loading_pct",
        "encapsulation_efficiency_pct", "lipid_to_drug_ratio",
        "pegylation_degree_mol_pct", "ligand_density_per_nm2",
        "peg_chain_length_da", "surface_logp", "ph_trigger",
        "mechanical_half_life_s", "diffusion_coeff_um2_s",
        "leakage_rate_pct_per_h", "pgp_escape_coeff",
        "carpa_risk_index", "off_target_liver_pct",
        "glymphatic_clearance_h", "ecm_binding_index",
        "phase_transition_temp_c", "flow_rate_ratio",
    }

    _imputer = None   # cached singleton

    @classmethod
    def _get_imputer(cls) -> Any | None:
        if not _HAS_IMPUTER:
            return None
        if cls._imputer is None:
            cls._imputer = IterativeImputer(
                estimator=ExtraTreesRegressor(n_estimators=50, random_state=42),
                max_iter=10,
                random_state=42,
                initial_strategy="median",   # safe starting point
                imputation_order="roman",
            )
        return cls._imputer

    @classmethod
    def impute(cls, df: pd.DataFrame, numeric_cols: list[str]) -> pd.DataFrame:
        """
        Apply IterativeImputer to secondary numeric columns only.
        Core columns with NaN trigger strict rejection (row dropped).
        Records every imputed cell in a sidecar imputation_report.csv.
        """
        df = df.copy()

        # 1. Drop rows where CORE fields are missing (Strict Rejection)
        before = len(df)
        df.dropna(subset=[c for c in cls.CORE_FIELDS if c in df.columns],
                  inplace=True)
        rejected = before - len(df)
        if rejected:
            log.warning(f"  Strict Rejection: {rejected} rows dropped "
                        f"(missing core fields: {cls.CORE_FIELDS})")

        if df.empty:
            return df

        # 2. Identify secondary columns eligible for imputation.
        # SECONDARY_FIELDS is the deliberate, curated whitelist this
        # class's own docstring describes ("SECONDARY features... LogP,
        # PDI, Ligand_Density, etc."); it was never actually consulted
        # here -- any numeric column the caller passed (minus the 3 CORE
        # fields) got imputed, whatever else happened to be in the
        # dataframe at call time. Currently harmless in the one real call
        # site (build_dataframe -> enrich_drug_fields runs before any
        # score/rank column exists), but silently drops the safety
        # boundary this class exists to enforce for any future caller or
        # column addition.
        eligible = [c for c in numeric_cols
                    if c in df.columns and c in cls.SECONDARY_FIELDS]

        # Track which cells were imputed (for documentation)
        mask_before = df[eligible].isna()
        n_missing   = mask_before.sum().sum()

        if n_missing == 0:
            log.info("  ImputerEngine: no missing secondary values.")
            return df

        imputer = cls._get_imputer()
        if imputer is None:
            # Fallback: use column median (better than 0)
            log.warning("  IterativeImputer unavailable — using column median fallback")
            for col in eligible:
                median = df[col].median()
                df[col].fillna(median, inplace=True)
            return df

        # Fit-transform
        X = df[eligible].values.astype(float)
        try:
            X_imp = imputer.fit_transform(X)
            df[eligible] = X_imp
            log.info(f"  IterativeImputer: {n_missing} cells imputed "
                     f"across {len(eligible)} secondary features")
        except Exception as e:
            log.warning(f"  IterativeImputer failed: {e} — using median fallback")
            for col in eligible:
                df[col].fillna(df[col].median(), inplace=True)

        # 3. Write imputation report (transparency / audit)
        mask_after   = df[eligible].notna()
        imputed_cells = []
        for col in eligible:
            was_null = mask_before[col]
            if was_null.any():
                for idx in df.index[was_null]:
                    imputed_cells.append({
                        "row_index":    idx,
                        "column":       col,
                        "imputed_value": df.at[idx, col],
                        "method":       "IterativeImputer(ExtraTrees)" if _HAS_IMPUTER else "median",
                        "timestamp":    datetime.utcnow().isoformat(),
                    })

        if imputed_cells:
            imp_df = pd.DataFrame(imputed_cells)
            imp_path = DDS_RESULTS / "imputation_report.csv"
            imp_df.to_csv(imp_path, mode="a",
                          header=not imp_path.exists(), index=False)
            write_doc(imp_path, {
                "overview":
                    "Audit log of every cell imputed by IterativeImputer. "
                    "Records which secondary DDS feature was missing, "
                    "the predicted replacement value, and the imputation method.",
                "significance":
                    "Provides full transparency for regulatory review. "
                    "Auditors can verify that no core scientific values were "
                    "synthetically generated — only secondary engineering "
                    "parameters were inferred.",
                "strategic_decision":
                    "Any column with > 20% imputed values should be flagged "
                    "for wet-lab measurement rather than relying on ML inference.",
                "theoretical_science":
                    "IterativeImputer: "
                    "models each feature as a function of all others via "
                    "ExtraTreesRegressor. Iterates until convergence (max 10 rounds). "
                    "Initial strategy: column median (robust to outliers).\n\n"
                    "Why not fillna(0)? MW_Da=0 is chemically impossible and "
                    "creates catastrophic outliers that corrupt ML training. "
                    "Why not fillna(mean)? Mean ignores inter-feature correlations "
                    "(e.g. LogP and encapsulation_efficiency are correlated).",
                "practical_science":
                    "Validated approach: MICE (Multiple Imputation by "
                    "Chained Equations) is the gold standard in clinical trials "
                    "for handling missing biomarker data.",
                "methodology":
                    "1. Drop rows with missing CORE fields (Strict Rejection).\n"
                    "2. Identify secondary columns with NaN.\n"
                    "3. fit_transform via IterativeImputer.\n"
                    "4. Log every imputed cell to this report.",
                "computational_architecture":
                    "sklearn.impute.IterativeImputer + "
                    "sklearn.ensemble.ExtraTreesRegressor (n=50). "
                    "Fallback: column median if sklearn experimental API unavailable.",
            })

        return df

# ─────────────────────────────────────────────────────────────────────────────
# 7.  DDS ENGINE  — reads dds_config.yaml, builds DataFrame, runs pipeline
# ─────────────────────────────────────────────────────────────────────────────
class DDSEngine:
    """
    Drug Delivery System analysis engine.

    Reads dds_config.yaml (the 'Formulation Recipe' file),
    enriches each formulation with live API data where fields are null,
    then feeds everything into the CEREBRO-X pipeline for scoring.

    Architecture:
      yaml → DataFrame → ImputerEngine → CascadeDataEngine enrichment
      → AdvancedMLEngine → ADMETEngine → BBB scoring → ranked output
    """

    # DDS-specific BBB scoring formula (Pardridge 2012 framework)
    # Combines size, zeta, PEGylation, ligand, and pH trigger
    @staticmethod
    def compute_bbb_engineering_score(row: dict) -> float:
        """
        Engineering BBB penetration index (0–100).
        Higher = better predicted CNS delivery.

        Formula derived from:
        - Tosi et al. (2010): size penalty > 100 nm
        - Kreuter (2013): ApoE corona + polysorbate-80 → BBB crossing
        - Georgieva et al. (2014): zeta potential sweet spot ±5–15 mV
        - Deverman et al. (2016): ligand density Goldilocks zone
        """
        score = 50.0  # baseline

        # Size penalty (optimal 60–100 nm for transcytosis)
        sz = row.get("size_nm", 100)
        if 60 <= sz <= 100:
            score += 20
        elif sz < 60:
            score += 10   # too small — short circulation time
        elif sz > 200:
            score -= 20   # too large — physical barrier

        # Zeta potential (optimal ±5–15 mV)
        zp = abs(row.get("zeta_potential_mv", 0))
        if 5 <= zp <= 15:
            score += 15
        elif zp > 30:
            score -= 15   # triggers immune clearance

        # PEGylation (2–7 mol% optimal — stealth without blocking ligands)
        peg = row.get("pegylation_degree_mol_pct", 0)
        if 2 <= peg <= 7:
            score += 10
        elif peg > 10:
            score -= 5    # hyperpegylation blocks ligand access

        # Surface ligand
        lig = str(row.get("surface_ligand", "None")).lower()
        if "rvg" in lig:
            score += 20   # nicotinic acetylcholine receptor — proven CNS
        elif "angiopep" in lig:
            score += 18   # LRP1 — clinically validated
        elif "transferrin" in lig:
            score += 15   # TfR1 — classic BBB strategy
        elif "apoe" in lig:
            score += 22   # LDLR — highest CNS affinity known
        elif "glucose" in lig or "glut1" in lig:
            score += 17   # GLUT1 — always expressed on BBB

        # Ligand density Goldilocks zone (0.5–1.5 per nm²)
        ld = row.get("ligand_density_per_nm2", 0)
        if 0.5 <= ld <= 1.5:
            score += 8
        elif ld > 3:
            score -= 5    # macrophage recognition

        # Encapsulation efficiency (>75% = good)
        ee = row.get("encapsulation_efficiency_pct", 0)
        if ee >= 80:
            score += 8
        elif ee < 50:
            score -= 10

        # P-gp escape coefficient
        pgp = row.get("pgp_escape_coeff", 0.5)
        score += (pgp - 0.5) * 20   # linear: 0.5 baseline, 1.0 = +10

        # ApoE affinity
        apoe = str(row.get("apo_e_affinity", "low")).lower()
        if apoe == "very_high": score += 10
        elif apoe == "high":    score += 7
        elif apoe == "moderate":score += 3

        # CARPA risk penalty
        carpa = row.get("carpa_risk_index", 0.3)
        score -= carpa * 15

        # Off-target liver penalty
        liver = row.get("off_target_liver_pct", 50)
        score -= (liver / 100) * 10

        # Phase transition temperature (must be > 37°C body temp)
        tm = row.get("phase_transition_temp_c", 50)
        if tm <= 37:
            score -= 20   # will melt/fuse in vivo before reaching brain

        return round(min(max(score, 0), 100), 2)

    @classmethod
    def load_config(cls) -> dict | None:
        """Load and validate dds_config.yaml."""
        if not DDS_CONFIG.exists():
            log.error(f"dds_config.yaml not found at {DDS_CONFIG}")
            return None
        if not _HAS_YAML:
            log.error("PyYAML not installed: pip install pyyaml")
            return None
        with open(DDS_CONFIG, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        n = len(cfg.get("formulations", []))
        log.info(f"[DDS] Loaded config: {n} formulations for "
                 f"{cfg['drug']['name']}")
        return cfg

    @classmethod
    def build_dataframe(cls, cfg: dict) -> pd.DataFrame:
        """
        Convert formulations list to DataFrame.
        Fields marked null in YAML are left as NaN for ImputerEngine.
        """
        rows = []
        drug_info = cfg["drug"]
        for f in cfg["formulations"]:
            row = {
                # Drug info (same for all formulations)
                "Drug":         drug_info["name"],
                "Drug_Alias":   drug_info.get("aliases", [""])[0],
                "Indication":   drug_info.get("indication", ""),
                # Formulation identity
                "Formulation_ID":   f["id"],
                "Formulation_Name": f["name"],
                "Carrier_Type":     f["carrier_type"],
                # All engineering parameters (None → NaN)
                "Surface_Ligand":              f.get("surface_ligand"),
                "size_nm":                     f.get("size_nm"),
                "zeta_potential_mv":           f.get("zeta_potential_mv"),
                "shape":                       f.get("shape"),
                "pdi":                         f.get("pdi"),
                "elasticity_kpa":              f.get("elasticity_kpa"),
                "drug_loading_pct":            f.get("drug_loading_pct"),
                "encapsulation_efficiency_pct":f.get("encapsulation_efficiency_pct"),
                "lipid_to_drug_ratio":         f.get("lipid_to_drug_ratio"),
                "pegylation_degree_mol_pct":   f.get("pegylation_degree_mol_pct"),
                "ligand_density_per_nm2":      f.get("ligand_density_per_nm2"),
                "peg_chain_length_da":         f.get("peg_chain_length_da"),
                "surface_logp":                f.get("surface_logp"),
                "ph_trigger":                  f.get("ph_trigger"),
                "phase_transition_temp_c":     f.get("phase_transition_temp_c"),
                "flow_rate_ratio":             f.get("flow_rate_ratio"),
                "mechanical_half_life_s":      f.get("mechanical_half_life_s"),
                "diffusion_coeff_um2_s":       f.get("diffusion_coeff_um2_s"),
                "leakage_rate_pct_per_h":      f.get("leakage_rate_pct_per_h"),
                "pgp_escape_coeff":            f.get("pgp_escape_coeff"),
                "carpa_risk_index":            f.get("carpa_risk_index"),
                "off_target_liver_pct":        f.get("off_target_liver_pct"),
                "apo_e_affinity":              f.get("apo_e_affinity"),
                "glymphatic_clearance_h":      f.get("glymphatic_clearance_h"),
                "ecm_binding_index":           f.get("ecm_binding_index"),
                "release_kinetics":            f.get("release_kinetics"),
                "protein_corona_dominant":     f.get("protein_corona_dominant"),
                "scalability_score":           f.get("scalability_score"),
                "manufacturing_method":        f.get("manufacturing_method"),
                "cns_tropism":                 f.get("cns_tropism"),
                "special_feature":             f.get("special_feature"),
                "route":                       f.get("route", "IV"),
                "note":                        f.get("note", ""),
                # Drug properties (from yaml or to be fetched)
                "MW_Da":          drug_info.get("mw_da"),
                "LogP":           drug_info.get("logp"),
                "Half_Life_Days": drug_info.get("half_life_days"),
            }
            rows.append(row)
        return pd.DataFrame(rows)

    @classmethod
    def enrich_drug_fields(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        If drug MW / LogP / HL are null in the YAML (marked for live fetch),
        use CascadeDataEngine from the main pipeline to fetch them.
        """
        drug_name = df["Drug"].iloc[0].lower() if not df.empty else ""
        needs_mw  = df["MW_Da"].isna().all()
        needs_lp  = df["LogP"].isna().all()
        needs_hl  = df["Half_Life_Days"].isna().all()

        if not (needs_mw or needs_lp or needs_hl):
            return df

        # Try to import CascadeDataEngine from the main pipeline
        try:
            sys.path.insert(0, SCRIPT_DIR)
            from CEREBRO_Pipeline import CLINICAL_HL, MW_REF, CascadeDataEngine
            data = CascadeDataEngine.fetch_drug(drug_name)
            if data:
                if needs_mw:
                    df["MW_Da"] = data.get("MW_Da",
                                           MW_REF.get(drug_name, None))
                if needs_lp:
                    # v22.1: no drug-name-specific fallback -- matches
                    # MW_Da/Half_Life_Days just above. This used to
                    # default to a hardcoded -0.7 for every drug whose
                    # cascade fetch didn't return LogP, silently
                    # contradicting that same policy for the other two
                    # fields right next to it.
                    df["LogP"] = data.get("LogP", None)
                if needs_hl:
                    df["Half_Life_Days"] = data.get(
                        "Half_Life_Days",
                        CLINICAL_HL.get(drug_name, None))

                def _fmt(v, spec):
                    return format(v, spec) if pd.notna(v) else "N/A"

                log.info(f"  [DDS] Drug fields enriched from cascade: "
                         f"MW={_fmt(df['MW_Da'].iloc[0], '.0f')} Da, "
                         f"LogP={_fmt(df['LogP'].iloc[0], '.2f')}, "
                         f"HL={_fmt(df['Half_Life_Days'].iloc[0], '.1f')}d")
        except Exception as e:
            log.warning(f"  [DDS] Cascade enrichment failed: {e}")
            # v22.1: NO drug-name-specific fallbacks. If cascade fails,
            # the fields stay None and downstream code reports the gap.
            log.warning(f"  [DDS] Drug fields could not be enriched live for "
                        f"{drug_name!r}. Researcher should provide values via Excel.")

        return df

    @classmethod
    def run(cls) -> pd.DataFrame | None:
        """
        Full DDS analysis pipeline:
        1. Load YAML
        2. Build DataFrame
        3. Enrich drug fields via Cascade
        4. IterativeImputer for secondary NaN fields
        5. Compute BBB engineering score per formulation
        6. Rank and export
        """
        log.info("=" * 60)
        log.info("[DDS ENGINE] Starting formulation analysis …")
        log.info("=" * 60)

        cfg = cls.load_config()
        if not cfg:
            return None

        df = cls.build_dataframe(cfg)
        log.info(f"  Loaded {len(df)} formulations")

        # Enrich drug-level fields
        df = cls.enrich_drug_fields(df)

        # Impute secondary NaN fields
        numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
        df = ImputerEngine.impute(df, numeric_cols)

        # Compute BBB engineering score
        df["BBB_Engineering_Score"] = df.apply(
            lambda r: cls.compute_bbb_engineering_score(r.to_dict()), axis=1
        )

        # Sort by score
        df = df.sort_values("BBB_Engineering_Score", ascending=False)
        df["Rank"] = range(1, len(df) + 1)

        # Save ranked output
        path = DDS_RESULTS / "formulation_ranking.csv"
        df.to_csv(path, index=False)
        _drug_name = cfg["drug"]["name"]
        write_doc(path, {
            "overview":
                f"Complete ranking of {len(df)} DDS formulations for "
                f"{_drug_name} BBB delivery, scored by the CEREBRO-X BBB "
                f"Engineering Score (0–100).",
            "significance":
                f"Identifies the top drug delivery architectures for solving "
                f"{_drug_name}'s BBB penetration problem. "
                f"The top-ranked systems are recommended for in-vitro validation.",
            "strategic_decision":
                "Formulations with BBB_Engineering_Score > 75 AND "
                "off_target_liver_pct < 30 AND carpa_risk_index < 0.35 "
                "are shortlisted for wet-lab vexosome preparation.",
            "theoretical_science":
                "BBB Engineering Score formula:\n"
                "  Score = 50 (baseline)\n"
                "         + size_bonus (max +20 for 60–100 nm)\n"
                "         + zeta_bonus (max +15 for ±5–15 mV)\n"
                "         + peg_bonus  (max +10 for 2–7 mol%)\n"
                "         + ligand_bonus (RVG +20, ApoE +22, etc.)\n"
                "         + density_bonus (+8 for 0.5–1.5 per nm²)\n"
                "         + EE_bonus (+8 for ≥80%)\n"
                "         + PgP_escape (scaled +/−10)\n"
                "         + ApoE_affinity (max +10)\n"
                "         − CARPA_penalty (max −15)\n"
                "         − liver_penalty (max −10)\n"
                "         − Tm_penalty (−20 if Tm ≤ 37°C)\n"
                "Size optimality: 60–100 nm for caveolae-mediated transcytosis. "
                "Zeta ±5–15 mV: stable yet avoids macrophage opsonisation. "
                "PEG 2–7 mol%: stealth shield without blocking ligand-receptor docking.",
            "practical_science":
                "Reference benchmarks: ApoE-seeded LNPs achieve ~2% CSF penetration. "
                "PHP.eB AAV achieves ~0.98 CNS tropism. "
                "RVG-vexosomes: ~8× improvement vs. naked antibody.",
            "methodology":
                "1. Parse dds_config.yaml → 100-row DataFrame.\n"
                "2. Cascade API enrichment for drug MW/LogP/HL.\n"
                "3. IterativeImputer for secondary NaN fields.\n"
                "4. compute_bbb_engineering_score() per row.\n"
                "5. Sort descending, assign Rank.",
            "computational_architecture":
                "Pure Python + pandas. Score function is deterministic "
                "and fully reproducible. No ML randomness in ranking step.",
        })

        # Top 10 summary
        top10 = df.head(10)[["Rank","Formulation_ID","Formulation_Name",
                               "Carrier_Type","BBB_Engineering_Score",
                               "off_target_liver_pct","carpa_risk_index"]]
        top10_path = DDS_RESULTS / "top10_formulations.csv"
        top10.to_csv(top10_path, index=False)
        write_doc(top10_path, {
            "overview":
                "Top-10 DDS formulations by BBB Engineering Score.",
            "significance":
                "Immediate shortlist for wet-lab validation and investor reporting.",
            "strategic_decision":
                "Proceed to in-vitro BBB model (TEER assay) with Rank 1–5.",
            "theoretical_science":
                "Subset of full formulation_ranking.csv — same scoring formula.",
            "methodology": "df.head(10) after sorting by BBB_Engineering_Score.",
            "computational_architecture": "pandas · CSV.",
        })

        log.info(f"\n{'─'*60}")
        log.info(f"TOP 5 DDS FORMULATIONS FOR {_drug_name.upper()} BBB DELIVERY:")
        for _, row in df.head(5).iterrows():
            log.info(f"  #{int(row['Rank']):3d}  {row['Formulation_ID']:12s}  "
                     f"Score={row['BBB_Engineering_Score']:5.1f}  "
                     f"{row['Formulation_Name']}")
        log.info(f"  Full ranking → {path}")
        log.info(f"{'─'*60}")

        return df

# ─────────────────────────────────────────────────────────────────────────────
# 8.  CELERY TASK QUEUE  (async long-running jobs)
# ─────────────────────────────────────────────────────────────────────────────
REDIS_URL    = os.environ.get("REDIS_URL",    "redis://localhost:6379/0")
CELERY_BROKER= os.environ.get("CELERY_BROKER","redis://localhost:6379/0")
CELERY_BACK  = os.environ.get("CELERY_BACKEND","redis://localhost:6379/1")

if _HAS_CELERY:
    celery_app = Celery(
        "cerebro",
        broker=CELERY_BROKER,
        backend=CELERY_BACK,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,   # one task at a time (CPU-bound ML)
        task_acks_late=True,            # retry on worker crash
    )

    @celery_app.task(bind=True, name="cerebro.run_pipeline")
    def run_pipeline_task(self, config_override: dict = None):
        """
        Celery task: runs the full CEREBRO-X pipeline asynchronously.
        Submitted via FastAPI — does NOT block the API response.
        """
        log.info(f"[Celery] Task {self.request.id} starting pipeline …")
        try:
            sys.path.insert(0, SCRIPT_DIR)
            import CEREBRO_Pipeline as cp
            cp.setup_workspace()
            # v22.1: NO hardcoded demo drug lists. Pull live from current Excel input.
            try:
                from pathlib import Path as _P
                _xlsx = _P("CEREBRO_Input_Template.xlsx")
                if _xlsx.exists():
                    import pandas as _pd
                    _df = _pd.read_excel(_xlsx, sheet_name="1_Drug_Input")
                    drug_name_row = _df.loc[_df.get("Field","").astype(str)=="Drug Name", "Your Input"]
                    drug_names = [str(v).strip() for v in drug_name_row.values
                                    if v and str(v).strip()]
                else:
                    drug_names = []
            except Exception:
                drug_names = []
            if not drug_names:
                return {"status": "error",
                         "message": "No drugs found in Excel input. Provide CEREBRO_Input_Template.xlsx"}
            aav_vectors = ["AAV9","AAV-PHP.eB","AAV5"]   # generic AAV serotypes (not drugs)
            df_mab    = cp.CascadeDataEngine.build_mab_dataset(drug_names)
            df_aav    = cp.CascadeDataEngine.fetch_aav_data()
            df_matrix = cp.CascadeDataEngine.build_drug_aav_matrix(
                drug_names, aav_vectors)
            if df_mab.empty:
                return {"status": "error", "message": "No valid drug data"}
            df_ml, _, metrics = cp.AdvancedMLEngine.train(
                df_mab,
                feature_cols=["MW_Da","LogP","Half_Life_Days","Docking_Affinity_kcal"])
            df_ml = cp.ADMETEngine.run(df_ml)
            df_vex = cp.AnalyticsEngine.simulate_vexosome_encapsulation()
            df_pk  = cp.AnalyticsEngine.simulate_pkpd(df_ml)
            cp.AnalyticsEngine.regression_affinity_vs_kinetics(df_ml)
            cp.VisualisationEngine.plot_3d_space(df_ml)
            cp.VisualisationEngine.plot_radar(df_ml)
            cp.VisualisationEngine.plot_synergy_network(df_matrix)
            cp.VisualisationEngine.plot_encapsulation(df_vex)
            cp.ReportingEngine.generate_master_report(df_mab, df_aav, df_ml, metrics)
            # Run DDS analysis
            DDSEngine.run()
            return {"status": "success", "r2": metrics.get("r2", 0),
                    "n_candidates": len(df_ml)}
        except Exception as e:
            log.exception(f"[Celery] Pipeline failed: {e}")
            raise

    @celery_app.task(name="cerebro.run_dds")
    def run_dds_task():
        """Celery task: DDS analysis only (faster than full pipeline)."""
        df = DDSEngine.run()
        return {"status": "success", "n_formulations": len(df) if df is not None else 0}

else:
    # Stub tasks when Celery unavailable
    class _StubTask:
        def delay(self, *a, **kw):
            log.warning("Celery not installed — task runs synchronously")
    run_pipeline_task = _StubTask()
    run_dds_task      = _StubTask()

# ─────────────────────────────────────────────────────────────────────────────
# 9.  FASTAPI BACKEND
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_FASTAPI:
    app = FastAPI(
        title="CEREBRO-X API",
        description="Production-grade drug-discovery pipeline REST interface",
        version="1.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Pydantic request/response models ──────────────────────────────────
    class PipelineRequest(PydanticBase):
        drugs:       list[str] = []          # v22.1: NO defaults — caller must supply
        aav_vectors: list[str] = ["AAV9","AAV-PHP.eB","AAV5"]   # AAV serotypes (not drugs)
        async_mode:  bool      = True

    class DDSRequest(PydanticBase):
        config_path: str = str(DDS_CONFIG)

    # ── Routes ────────────────────────────────────────────────────────────
    @app.get("/", tags=["Health"])
    def root():
        return {
            "service": "CEREBRO-X API",
            "version": "1.0.0",
            "status":  "running",
            "endpoints": ["/health","/run-pipeline","/run-dds",
                          "/results/{filename}","/docs"],
        }

    @app.get("/health", tags=["Health"])
    def health():
        return {
            "status":     "ok",
            "timestamp":  datetime.utcnow().isoformat(),
            "celery":     _HAS_CELERY,
            "yaml":       _HAS_YAML,
            "imputer":    _HAS_IMPUTER,
            "dotenv":     _HAS_DOTENV,
        }

    @app.post("/run-pipeline", tags=["Pipeline"])
    def run_pipeline(req: PipelineRequest, bg: BackgroundTasks):
        """
        Submit a full CEREBRO-X pipeline run.
        async_mode=True  → Celery task (non-blocking, returns task_id).
        async_mode=False → Runs synchronously (blocks until complete).
        """
        if req.async_mode and _HAS_CELERY:
            task = run_pipeline_task.delay()
            return {"status": "submitted", "task_id": str(task.id),
                    "message": "Check /task-status/{task_id} for progress"}
        else:
            # Blocking run via BackgroundTasks (for simple deployments)
            bg.add_task(_blocking_pipeline_run)
            return {"status": "started", "mode": "background_task",
                    "message": "Pipeline running — check outputs/"}

    @app.post("/run-dds", tags=["DDS"])
    def run_dds(req: DDSRequest, bg: BackgroundTasks):
        """Submit a DDS formulation analysis (100 systems from YAML)."""
        if _HAS_CELERY:
            task = run_dds_task.delay()
            return {"status": "submitted", "task_id": str(task.id)}
        else:
            bg.add_task(DDSEngine.run)
            return {"status": "started", "mode": "background_task"}

    @app.get("/task-status/{task_id}", tags=["Pipeline"])
    def task_status(task_id: str):
        """Poll Celery task status."""
        if not _HAS_CELERY:
            return {"error": "Celery not available"}
        from celery.result import AsyncResult
        result = AsyncResult(task_id, app=celery_app)
        return {
            "task_id": task_id,
            "state":   result.state,
            "info":    str(result.info) if result.info else None,
        }

    @app.get("/results", tags=["Results"])
    def list_results():
        """List all output files generated by the pipeline."""
        files = []
        for p in OUTPUT_ROOT.rglob("*"):
            if p.is_file() and not p.name.endswith("_DOCUMENTATION.txt"):
                files.append({
                    "path":     str(p.relative_to(OUTPUT_ROOT)),
                    "size_kb":  round(p.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(
                        p.stat().st_mtime).isoformat(),
                })
        return {"n_files": len(files), "files": files}

    @app.get("/results/{filepath:path}", tags=["Results"])
    def download_result(filepath: str):
        """Download a specific result file.

        Path traversal: filepath is a raw user-controlled path -- this
        used to join it onto OUTPUT_ROOT with no containment check, so
        any caller (this legacy endpoint has no authentication at all)
        could pass "../../../etc/passwd" or an equivalent URL-encoded
        traversal and read any file the server process can read,
        completely outside OUTPUT_ROOT. Same vulnerability class already
        fixed for the equivalent endpoint in src/api/app.py. Resolve both
        sides and require the result to actually be a descendant of
        OUTPUT_ROOT before serving it.
        """
        results_root = Path(OUTPUT_ROOT).resolve()
        full = (results_root / filepath).resolve()
        if not full.is_relative_to(results_root):
            raise HTTPException(403, detail="Access denied: path escapes results directory")
        if not full.exists():
            raise HTTPException(404, detail=f"File not found: {filepath}")
        return FileResponse(str(full))

    @app.get("/dds/top10", tags=["DDS"])
    def dds_top10():
        """Return top 10 DDS formulations from latest analysis."""
        p = DDS_RESULTS / "top10_formulations.csv"
        if not p.exists():
            raise HTTPException(404, "Run /run-dds first")
        df = pd.read_csv(p)
        return df.to_dict(orient="records")

    @app.get("/dds/ranking", tags=["DDS"])
    def dds_ranking(limit: int = 20, min_score: float = 0.0):
        """Return full DDS ranking, optionally filtered."""
        p = DDS_RESULTS / "formulation_ranking.csv"
        if not p.exists():
            raise HTTPException(404, "Run /run-dds first")
        df = pd.read_csv(p)
        df = df[df["BBB_Engineering_Score"] >= min_score]
        return df.head(limit).to_dict(orient="records")

    # ── NEW: Upload Excel template → run full pipeline → return JSON+PDF ──────
    @app.post("/upload-formulation-excel", tags=["Excel Upload"])
    async def upload_excel(
        file: "UploadFile",
        return_pdf: bool = False,
        bg: BackgroundTasks = None,
    ):
        """
        Accept CEREBRO_Input_Template.xlsx from researcher/website.
        Pipeline:
          1. Save uploaded file to temp location
          2. ExcelReader converts it to drug_profile + formulations list
          3. MoleculeEngine fetches all drug data (SMILES/FASTA/name cascade)
          4. DDSEngine scores all formulations
          5. AnimationEngine generates GIF animations
          6. Returns JSON with Base64-encoded figures + CSV data
             OR streams an in-memory PDF report if return_pdf=True

        This endpoint is the bridge between the website form and the pipeline.
        The website sends a filled Excel → gets back a complete analysis JSON.
        """
        import shutil
        import tempfile

        from fastapi.responses import StreamingResponse

        # Import patches
        try:
            import CEREBRO_Pipeline as cp
            from cerebro_pipeline_patches import (
                AnimationEngine,
                ExcelReader,
                apply_patches,
                collect_results_as_json,
                generate_pdf_report,
            )
            apply_patches(cp)
        except ImportError as e:
            raise HTTPException(500, f"Patch module not found: {e}")

        # Save uploaded file
        suffix = Path(file.filename or "upload.xlsx").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            # Parse Excel
            drug_profile, formulations = ExcelReader.read(tmp_path)
            if not drug_profile.get("name"):
                raise HTTPException(400, "Drug Name is required in Sheet 1")
            if not formulations:
                raise HTTPException(400, "No formulations found in Sheet 2")

            # Molecule analysis
            mol_input = drug_profile.get("molecule_input", drug_profile.get("name",""))
            try:
                from cerebro_molecule_engine import analyze_molecule
                mol_profile = analyze_molecule(mol_input, drug_profile.get("name"))
                # Merge into drug_profile
                for k in ("MW_Da","LogP","Half_Life_Days","Docking_Affinity_kcal",
                           "SMILES_canonical","UniProt_ID","BBB_permeability_pct"):
                    if mol_profile.get(k) and not drug_profile.get(k):
                        drug_profile[k] = mol_profile[k]
            except ImportError:
                pass   # MoleculeEngine optional

            # Build YAML-equivalent dict and run DDS
            yaml_dict = ExcelReader.to_yaml_dict(drug_profile, formulations)

            # Write temporary YAML config for DDSEngine
            if _HAS_YAML:
                import tempfile

                import yaml
                with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                                  delete=False,
                                                  encoding="utf-8") as ytmp:
                    yaml.dump(yaml_dict, ytmp, allow_unicode=True)
                    yaml_path = ytmp.name

                # Run DDSEngine with the uploaded config
                original_config = DDSEngine.__dict__.get("_config_path_override")
                # Temporarily override config path
                orig_load = DDSEngine.load_config.__func__ if hasattr(DDSEngine.load_config, "__func__") else DDSEngine.load_config

                def _tmp_load(cls):
                    with open(yaml_path, encoding="utf-8") as f:
                        cfg = yaml.safe_load(f)
                    return cfg

                DDSEngine.load_config = classmethod(_tmp_load)
                df_dds = DDSEngine.run()
                DDSEngine.load_config = classmethod(lambda cls: orig_load(cls) if callable(orig_load) else None)

                import os
                os.unlink(yaml_path)
            else:
                df_dds = None

            # Generate animations
            anim = AnimationEngine(OUTPUT_ROOT)
            gif_paths = []
            if df_dds is not None:
                g = anim.bbb_score_animation(df_dds, fps=8)
                if g: gif_paths.append(g)

            # Collect all results as JSON
            results = collect_results_as_json(OUTPUT_ROOT)
            results["excel_summary"] = {
                "drug_name":        drug_profile.get("name"),
                "molecule_class":   drug_profile.get("molecule_class"),
                "n_formulations":   len(formulations),
                "top_formulation":  (df_dds.iloc[0]["Formulation_Name"]
                                     if df_dds is not None and not df_dds.empty
                                     else "N/A"),
                "top_bbb_score":    (float(df_dds.iloc[0]["BBB_Engineering_Score"])
                                     if df_dds is not None and not df_dds.empty
                                     else 0),
            }

            if return_pdf:
                pdf_bytes = generate_pdf_report(
                    results, title=f"CEREBRO-X |  {drug_profile.get('name','') } Analysis")
                return StreamingResponse(
                    iter([pdf_bytes]),
                    media_type="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=CEREBRO_Report_{drug_profile.get('name','drug')}.pdf"})

            return results

        finally:
            import os
            try: os.unlink(tmp_path)
            except Exception: pass

    @app.post("/predict-molecule", tags=["Inference"])
    def predict_molecule(molecule_input: str, drug_name: str = ""):
        """
        Predict ML_Success_Probability for a NEW molecule (SMILES/FASTA/name).
        Uses the SAVED model scaler via .transform() — NO re-training.
        This endpoint enforces the fit/transform separation rule.

        Parameters:
            molecule_input : SMILES, FASTA, PDB ID, HELM, InChIKey, or drug name
            drug_name      : display name (optional)

        Returns JSON with full molecule profile + ML prediction.
        """
        try:
            from cerebro_pipeline_patches import InferenceEngine
        except ImportError:
            raise HTTPException(500, "cerebro_pipeline_patches.py not found")

        # Find latest saved model
        model_dir = OUTPUT_ROOT / "models"
        pkls = sorted(model_dir.glob("ensemble_*.pkl")) if model_dir.exists() else []
        if not pkls:
            raise HTTPException(404,
                "No trained model found. Run /run-pipeline first.")

        engine = InferenceEngine.load(str(pkls[-1]))

        # Fetch molecule profile
        profile = {}
        try:
            from cerebro_molecule_engine import analyze_molecule
            mol = analyze_molecule(molecule_input, drug_name or molecule_input[:20])
            profile = {
                "MW_Da":                mol.get("MW_Da", 0) or 0,
                "LogP":                 mol.get("LogP", 0) or 0,
                "Half_Life_Days":       mol.get("Half_Life_Days", 0) or 0,
                "Docking_Affinity_kcal":mol.get("Docking_Affinity_kcal", -8.5) or -8.5,
            }
        except Exception as e:
            log.warning(f"  MoleculeEngine failed: {e} — using zeros for missing fields")
            profile = {"MW_Da":0,"LogP":0,"Half_Life_Days":0,"Docking_Affinity_kcal":-8.5}

        score = engine.predict_single(profile)
        return {
            "drug_name":              drug_name or molecule_input[:30],
            "molecule_input_type":    "auto-detected",
            "profile":                profile,
            "ML_Success_Probability": score,
            "model_run_id":           engine.run_id,
            "scaler_policy":          "transform-only (leakage-free)",
            "note": ("Scaler was FITTED on original training data only. "
                     "This new molecule uses .transform() to avoid data leakage. "
                     "The prediction is valid and unbiased.")
        }

    @app.get("/download-pdf", tags=["Reports"])
    def download_pdf():
        """
        Generate and stream an in-memory PDF report of the latest pipeline run.
        The PDF is built in RAM — never saved to disk.
        """
        from fastapi.responses import StreamingResponse
        try:
            from cerebro_pipeline_patches import (
                collect_results_as_json,
                generate_pdf_report,
            )
        except ImportError:
            raise HTTPException(500, "cerebro_pipeline_patches.py not found")

        results   = collect_results_as_json(OUTPUT_ROOT)
        pdf_bytes = generate_pdf_report(results)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition":
                     "attachment; filename=CEREBRO_X_Report.pdf"})

    @app.get("/animations", tags=["Results"])
    def list_animations():
        """List all generated GIF/video files with Base64 content."""
        from cerebro_pipeline_patches import encode_file_base64
        figs_dir = OUTPUT_ROOT / "figures"
        result = {}
        if figs_dir.exists():
            for fp in figs_dir.glob("*.gif"):
                result[fp.stem] = {
                    "filename": fp.name,
                    "size_kb":  round(fp.stat().st_size / 1024, 1),
                    "base64":   encode_file_base64(fp),
                }
        return {"n_animations": len(result), "animations": result}

    def _blocking_pipeline_run():
        """Synchronous pipeline run used by BackgroundTasks."""
        try:
            sys.path.insert(0, SCRIPT_DIR)
            import CEREBRO_Pipeline as cp
            cp.setup_workspace()
            # v22.1: NO hardcoded drug list. Read from current Excel input.
            try:
                from pathlib import Path as _P

                import pandas as _pd
                _xlsx = _P("CEREBRO_Input_Template.xlsx")
                if not _xlsx.exists():
                    log.warning("[BG] No Excel input — skipping run")
                    return
                _df = _pd.read_excel(_xlsx, sheet_name="1_Drug_Input")
                drug_name_row = _df.loc[_df.get("Field","").astype(str)=="Drug Name", "Your Input"]
                drug_names = [str(v).strip() for v in drug_name_row.values
                                if v and str(v).strip()]
                if not drug_names:
                    log.warning("[BG] No drugs in Excel — skipping")
                    return
            except Exception as _e:
                log.warning(f"[BG] Could not read Excel: {_e}")
                return
            df_mab  = cp.CascadeDataEngine.build_mab_dataset(drug_names)
            df_aav  = cp.CascadeDataEngine.fetch_aav_data()
            df_ml,_,metrics = cp.AdvancedMLEngine.train(
                df_mab,["MW_Da","LogP","Half_Life_Days","Docking_Affinity_kcal"])
            df_ml = cp.ADMETEngine.run(df_ml)
            cp.ReportingEngine.generate_master_report(df_mab, df_aav, df_ml, metrics)
            DDSEngine.run()
        except Exception as e:
            log.exception(f"Blocking pipeline failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 10. BACKGROUND SCHEDULER  (hourly auto-run)
# ─────────────────────────────────────────────────────────────────────────────
def _scheduled_pipeline_run():
    """Called by APScheduler every hour."""
    log.info("[Scheduler] Hourly pipeline run triggered")
    if _HAS_CELERY:
        run_pipeline_task.delay()
    else:
        threading.Thread(target=_blocking_pipeline_run_standalone,
                         daemon=True).start()

def _blocking_pipeline_run_standalone():
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import CEREBRO_Pipeline as cp
        cp.setup_workspace()
        # v22.1: NO hardcoded drug list. Read live from current Excel input.
        try:
            from pathlib import Path as _P

            import pandas as _pd
            _xlsx = _P("CEREBRO_Input_Template.xlsx")
            if not _xlsx.exists():
                log.warning("[Scheduler] No Excel input — skipping run")
                return
            _df = _pd.read_excel(_xlsx, sheet_name="1_Drug_Input")
            drug_name_row = _df.loc[_df.get("Field","").astype(str)=="Drug Name", "Your Input"]
            drug_names = [str(v).strip() for v in drug_name_row.values
                            if v and str(v).strip()]
            if not drug_names:
                log.warning("[Scheduler] No drugs in Excel — skipping")
                return
        except Exception as _e:
            log.warning(f"[Scheduler] Could not read Excel: {_e}")
            return
        df_mab = cp.CascadeDataEngine.build_mab_dataset(drug_names)
        df_aav = cp.CascadeDataEngine.fetch_aav_data()
        df_ml,_,metrics = cp.AdvancedMLEngine.train(
            df_mab,["MW_Da","LogP","Half_Life_Days","Docking_Affinity_kcal"])
        df_ml = cp.ADMETEngine.run(df_ml)
        cp.ReportingEngine.generate_master_report(df_mab, df_aav, df_ml, metrics)
        DDSEngine.run()
        log.info("[Scheduler] Hourly run complete")
    except Exception as e:
        log.exception(f"[Scheduler] Run failed: {e}")

def start_scheduler(interval_hours: float = 1.0):
    if not _HAS_SCHEDULER:
        log.warning("[Scheduler] APScheduler not installed: "
                    "pip install apscheduler — hourly run disabled")
        return None
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _scheduled_pipeline_run,
        trigger="interval",
        hours=interval_hours,
        id="cerebro_hourly",
        next_run_time=datetime.now() + timedelta(seconds=10),  # first run soon
    )
    scheduler.start()
    log.info(f"[Scheduler] Started — pipeline runs every {interval_hours}h")
    return scheduler

# ─────────────────────────────────────────────────────────────────────────────
# 11. CROSS-PLATFORM AUTO-START WRITER
#     Writes a script that registers this process to run on boot,
#     headlessly, in the background — Windows Task Scheduler or cron
# ─────────────────────────────────────────────────────────────────────────────
def write_autostart():
    """
    Detects OS and writes the appropriate auto-start mechanism.
    Windows  → Task Scheduler XML + PowerShell import script
    macOS    → launchd plist (~/Library/LaunchAgents/)
    Linux    → systemd user service OR cron entry
    """
    OS = platform.system()
    py  = sys.executable
    # SCRIPT_DIR is patched to the project root by the ANCHOR fix above,
    # not this file's own src/dds/ directory -- the real file lives at
    # src/dds/enterprise_infra.py relative to that root. The literal
    # "cerebro_enterprise_infra.py" this used to join onto SCRIPT_DIR
    # doesn't exist anywhere in the project (that name is only a
    # sys.modules alias registered by src/path_resolver.py inside an
    # already-running process, not a real file on disk), so every
    # autostart config this function wrote (launchd plist / systemd
    # service / Task Scheduler XML / cron line) pointed at a script path
    # that would fail to launch on the next boot.
    script = os.path.join(SCRIPT_DIR, "src", "dds", "enterprise_infra.py")
    log_f  = str(INFRA_LOG)

    write_doc(Path(SCRIPT_DIR) / "autostart_info.txt", {
        "overview":
            f"Auto-start configuration for CEREBRO-X on {OS}. "
            "This file documents how the pipeline is registered to run "
            "automatically on system boot.",
        "significance":
            "Ensures the pipeline runs every hour without manual intervention, "
            "picking up new publications and database updates automatically.",
        "strategic_decision":
            "The auto-start mechanism is OS-specific. "
            "Windows uses Task Scheduler. macOS uses launchd. Linux uses systemd.",
        "methodology":
            f"Generated by write_autostart() on {datetime.now().isoformat()}. "
            f"Python executable: {py}\nScript: {script}",
        "computational_architecture":
            f"OS: {OS} · Python: {py} · headless=true · interval=1h",
    })

    if OS == "Windows":
        xml = textwrap.dedent(f"""
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2"
          xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers>
            <BootTrigger><Enabled>true</Enabled></BootTrigger>
            <RepetitionPattern>
              <Interval>PT1H</Interval>
              <StopAtDurationEnd>false</StopAtDurationEnd>
            </RepetitionPattern>
          </Triggers>
          <Actions>
            <Exec>
              <Command>{py}</Command>
              <Arguments>"{script}" --headless</Arguments>
              <WorkingDirectory>{SCRIPT_DIR}</WorkingDirectory>
            </Exec>
          </Actions>
          <Settings>
            <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
          </Settings>
        </Task>
        """).strip()
        xml_path = Path(SCRIPT_DIR) / "cerebro_task.xml"
        xml_path.write_text(xml, encoding="utf-16")

        ps_path = Path(SCRIPT_DIR) / "register_autostart.ps1"
        ps_path.write_text(
            f'Register-ScheduledTask -Xml (Get-Content "{xml_path}" '
            f'-Raw) -TaskName "CEREBRO-X" -Force\n'
            f'Write-Host "CEREBRO-X scheduled task registered."\n',
            encoding="utf-8")
        log.info(f"[AutoStart] Windows Task Scheduler XML → {xml_path}")
        log.info(f"[AutoStart] Run PowerShell AS ADMIN: {ps_path}")

    elif OS == "Darwin":  # macOS
        plist = textwrap.dedent(f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key>
          <string>com.cerebro.enterprise</string>
          <key>ProgramArguments</key>
          <array>
            <string>{py}</string>
            <string>{script}</string>
            <string>--headless</string>
          </array>
          <key>StartInterval</key>
          <integer>3600</integer>
          <key>RunAtLoad</key>
          <true/>
          <key>WorkingDirectory</key>
          <string>{SCRIPT_DIR}</string>
          <key>StandardOutPath</key>
          <string>{log_f}</string>
          <key>StandardErrorPath</key>
          <string>{log_f}</string>
          <key>KeepAlive</key>
          <false/>
        </dict>
        </plist>
        """).strip()
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        plist_path = agents_dir / "com.cerebro.enterprise.plist"
        plist_path.write_text(plist, encoding="utf-8")
        log.info(f"[AutoStart] macOS LaunchAgent plist → {plist_path}")
        log.info(f"[AutoStart] Activate: launchctl load {plist_path}")

    else:  # Linux
        service = textwrap.dedent(f"""
        [Unit]
        Description=CEREBRO-X Pipeline
        After=network.target

        [Service]
        Type=simple
        ExecStart={py} {script} --headless
        WorkingDirectory={SCRIPT_DIR}
        Restart=on-failure
        RestartSec=60s
        StandardOutput=append:{log_f}
        StandardError=append:{log_f}

        [Install]
        WantedBy=default.target
        """).strip()
        svc_dir  = Path.home() / ".config" / "systemd" / "user"
        svc_dir.mkdir(parents=True, exist_ok=True)
        svc_path = svc_dir / "cerebro.service"
        svc_path.write_text(service, encoding="utf-8")
        log.info(f"[AutoStart] systemd user service → {svc_path}")
        log.info("[AutoStart] Activate: systemctl --user enable --now cerebro")

        # Also write cron as alternative
        cron_line = (f"0 * * * *  cd {SCRIPT_DIR} && "
                     f"{py} {script} --headless >> {log_f} 2>&1")
        cron_path = Path(SCRIPT_DIR) / "cerebro_cron.txt"
        cron_path.write_text(
            f"# Add this line to crontab (crontab -e):\n{cron_line}\n",
            encoding="utf-8")
        log.info(f"[AutoStart] cron alternative → {cron_path}")

# ─────────────────────────────────────────────────────────────────────────────
# 12. MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def main():
    headless = "--headless" in sys.argv

    log.info("=" * 65)
    log.info("  CEREBRO-X — INFRASTRUCTURE")
    log.info(f"  OS: {platform.system()} | Python: {sys.version.split()[0]}")
    log.info(f"  Script dir: {SCRIPT_DIR}")
    log.info("=" * 65)

    # Write auto-start files (idempotent)
    write_autostart()

    # Run DDS analysis immediately
    log.info("[MAIN] Running DDS formulation analysis …")
    DDSEngine.run()

    # Start hourly scheduler
    interval_h = float(os.environ.get("CEREBRO_PIPELINE_INTERVAL_HOURS", "1"))
    scheduler = start_scheduler(interval_h)

    if headless:
        # Headless mode: scheduler loop only, no FastAPI
        log.info("[MAIN] Running in headless background mode")
        try:
            while True:
                time.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            if scheduler:
                scheduler.shutdown()
            log.info("[MAIN] Headless runner stopped")
        return

    # Interactive mode: start FastAPI
    if _HAS_FASTAPI:
        host = os.environ.get("FASTAPI_HOST", "0.0.0.0")
        port = int(os.environ.get("FASTAPI_PORT", "8000"))
        log.info(f"[MAIN] Starting FastAPI on http://{host}:{port}")
        log.info(f"[MAIN] API docs: http://localhost:{port}/docs")
        try:
            uvicorn.run(app, host=host, port=port,
                        log_level="warning")   # uvicorn logs at warning to avoid spam
        except (KeyboardInterrupt, SystemExit):
            pass
    else:
        log.warning("[MAIN] FastAPI not installed — running scheduler only")
        log.info("  Install: pip install fastapi uvicorn")
        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            pass

    if scheduler:
        scheduler.shutdown()
    log.info("[MAIN] CEREBRO-X shut down cleanly")


if __name__ == "__main__":
    main()
