"""
================================================================================
CEREBRO-X |  CEREBRO_Pipeline.py  —  Module Shim
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Fallback shim: maps CEREBRO_Pipeline → src/core/pipeline.py
(path_resolver handles this normally; shim activates only if path_resolver fails)

Freezes os.chdir during import to prevent pipeline.py from changing the working
directory to src/core/ when imported as a module.
================================================================================
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()  # engine/ -> project root
_CORE = str(_ROOT / "src" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

_saved_cwd  = os.getcwd()
_real_chdir = os.chdir
os.chdir = lambda _p: None   # freeze: prevent src/core chdir

try:
    import pipeline as _pl
    from pipeline import *

    # Patch SCRIPT_DIR so derived paths point to project root
    _pl.SCRIPT_DIR = str(_ROOT)
    if hasattr(_pl, "OUTPUT_ROOT"):
        _new_root = _ROOT / "outputs"
        _pl.OUTPUT_ROOT = _new_root
        _pl.DB_PATH = str(_new_root / "cerebro_knowledge.db")
        _pl.MISSING_DATA_LOG = str(_new_root / "Missing_Data_Log.txt")
        for _k in list(_pl.PATHS.keys()):
            _pl.PATHS[_k] = _new_root / _pl.PATHS[_k].name

    PATHS             = _pl.PATHS
    DB_PATH           = _pl.DB_PATH
    MISSING_DATA_LOG  = _pl.MISSING_DATA_LOG
    setup_workspace   = _pl.setup_workspace
    CascadeDataEngine = _pl.CascadeDataEngine
    AdvancedMLEngine  = _pl.AdvancedMLEngine
    ADMETEngine       = _pl.ADMETEngine
    AnalyticsEngine   = _pl.AnalyticsEngine
    ReportingEngine   = _pl.ReportingEngine
    db_upsert_drugs   = _pl.db_upsert_drugs
    try:
        CLINICAL_HL = _pl.CLINICAL_HL
        MW_REF      = _pl.MW_REF
    except AttributeError:
        CLINICAL_HL = {}
        MW_REF      = 150_000.0
finally:
    os.chdir = _real_chdir
    try: os.chdir(_saved_cwd)
    except Exception: pass

sys.modules.setdefault("CEREBRO_Pipeline", sys.modules[__name__])