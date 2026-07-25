"""
================================================================================
CEREBRO-X |  PATH RESOLVER
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

PURPOSE
-------
Single import at the top of any entry point → ALL 18 old module names resolve.

Problem:
  The codebase uses flat imports like:
    from CEREBRO_Pipeline import CascadeDataEngine
    from cerebro_molecule_engine import analyze_molecule
  These assume all .py files live in ONE directory.

  Also: pipeline.py and enterprise_infra.py both call os.chdir(SCRIPT_DIR)
  at module level, which would change the working directory to src/core/ or
  src/dds/ — breaking all relative paths in run.py.

Solution (v2.0.0):
  1. Freezes os.chdir during module registration so sub-module imports
     cannot change the working directory.
  2. After each import, patches SCRIPT_DIR on the module so subsequent
     file operations use the project root (/app/).
  3. Restores os.chdir and working directory to project root when done.
  4. Registers all 18 module aliases in sys.modules — no code changes needed
     anywhere else.

Usage (in run.py — one line, before any pipeline imports):
    import src.path_resolver   # ← wires everything
================================================================================
"""

import importlib
import os
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Project root resolution
# ─────────────────────────────────────────────────────────────────────────────
_THIS_DIR    = Path(__file__).resolve().parent   # .../src/
PROJECT_ROOT = _THIS_DIR.parent                   # .../CEREBRO_X/
ENGINE_DIR   = PROJECT_ROOT / "engine"            # .../CEREBRO_X/engine/ — flat cerebro_*.py modules

# Ensure project root, src/, and engine/ are all importable — engine/ holds
# the flat cerebro_*.py modules (moved out of the project root for a cleaner
# layout) that are still imported by bare name everywhere, e.g.
# `import cerebro_brand`, `from cerebro_62_orchestrator import ...`.
for _p in [str(PROJECT_ROOT), str(_THIS_DIR), str(ENGINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ─────────────────────────────────────────────────────────────────────────────
# Alias map:  old_module_name → dotted.import.path
# ─────────────────────────────────────────────────────────────────────────────
_ALIASES: dict = {
    # ── Core pipeline ────────────────────────────────────────────────────────
    "CEREBRO_Pipeline":             "src.core.pipeline",
    "cerebro_pipeline_patches":     "src.core.pipeline_patches",
    "cerebro_molecule_engine":      "src.core.molecule_engine",
    "cerebro_clinical_data_engine": "src.core.clinical_data_engine",
    "cerebro_data_engineering":     "src.core.data_engineering",
    "cerebro_science_engines":      "src.core.science_engines",
    "cerebro_pbbm_engine":          "src.core.pbbm_engine",
    "cerebro_final_report":         "src.core.final_report",

    # ── Visualization ─────────────────────────────────────────────────────────
    "cerebro_advanced_viz":         "src.viz.advanced_viz",
    "cerebro_visualization_3d":     "src.viz.visualization_3d",

    # ── DDS / Infrastructure ──────────────────────────────────────────────────
    "cerebro_enterprise_infra":     "src.dds.enterprise_infra",

    # ── API + Auth ────────────────────────────────────────────────────────────
    "cerebro_api_v2":               "src.api.app",
    "cerebro_auth":                 "src.api.auth",

    # ── ML + MLOps ────────────────────────────────────────────────────────────
    "cerebro_mlops":                "src.ml.mlops",
    "cerebro_knowledge_graph":      "src.ml.knowledge_graph",

    # ── Workers ───────────────────────────────────────────────────────────────
    "cerebro_orchestrator":         "src.workers.orchestrator",

    # ── Monitoring ────────────────────────────────────────────────────────────
    "cerebro_monitoring":           "src.monitoring.monitoring",

    # ── Compliance + Cache ────────────────────────────────────────────────────
    "cerebro_compliance":           "src.compliance.privacy",
    "cerebro_cache":                "src.ml.cache",
}


def _register_aliases() -> None:
    """
    Load every module alias, register it in sys.modules.

    Key safety measures:
      1. os.chdir is frozen (no-op) for the duration of all imports.
         This prevents pipeline.py and enterprise_infra.py from changing
         the working directory to their own src/ subdirectory.
      2. After each import, SCRIPT_DIR on the module is patched to point
         to the project root so subsequent file I/O uses correct paths.
      3. Working directory is restored to project root when done.
    """
    _saved_cwd  = os.getcwd()
    _real_chdir = os.chdir

    # Freeze chdir — prevents src sub-modules from changing cwd
    os.chdir = lambda _path: None

    try:
        for alias, dotted_path in _ALIASES.items():
            # Skip if already registered (e.g. by a shim file loaded earlier)
            if alias in sys.modules:
                continue

            try:
                mod = importlib.import_module(dotted_path)

                # Patch SCRIPT_DIR and derived path variables so any future
                # file operations use the project root, not the module's own folder.
                if hasattr(mod, "SCRIPT_DIR"):
                    try:
                        mod.SCRIPT_DIR = str(PROJECT_ROOT)
                        # Also patch OUTPUT_ROOT and PATHS which are derived from SCRIPT_DIR
                        # at module import time (before our patch runs).
                        if hasattr(mod, "OUTPUT_ROOT"):
                            new_root = PROJECT_ROOT / "outputs"
                            mod.OUTPUT_ROOT = new_root
                            # Patch DB_PATH and MISSING_DATA_LOG (pipeline.py)
                            if hasattr(mod, "DB_PATH"):
                                mod.DB_PATH = str(new_root / "cerebro_knowledge.db")
                            if hasattr(mod, "MISSING_DATA_LOG"):
                                mod.MISSING_DATA_LOG = str(new_root / "Missing_Data_Log.txt")
                            # Patch PATHS dict (run.py also patches this per trial)
                            if hasattr(mod, "PATHS") and isinstance(mod.PATHS, dict):
                                for k in list(mod.PATHS.keys()):
                                    mod.PATHS[k] = new_root / mod.PATHS[k].name
                    except (AttributeError, TypeError):
                        pass

                # Register under both the alias name and the dotted path
                sys.modules[alias] = mod
                if dotted_path not in sys.modules:
                    sys.modules[dotted_path] = mod

            except ImportError:
                # Module is optional — pipeline degrades gracefully
                pass
            except Exception:
                # Never crash on individual module failures
                pass

    finally:
        # Always restore real chdir and return to project root
        os.chdir = _real_chdir
        try:
            os.chdir(_saved_cwd)
        except Exception as _exc_bare:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Runtime directories (created here, not inside sub-modules)
# ─────────────────────────────────────────────────────────────────────────────
RESULTS_ROOT = PROJECT_ROOT / "outputs"
CONFIG_DIR   = PROJECT_ROOT / "config"
DATA_DIR     = PROJECT_ROOT / "data"

for _d in (RESULTS_ROOT, CONFIG_DIR, DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Auto-register on import
# ─────────────────────────────────────────────────────────────────────────────
_register_aliases()