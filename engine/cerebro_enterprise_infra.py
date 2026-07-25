# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  cerebro_enterprise_infra.py  —  Module Shim
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Fallback shim: maps cerebro_enterprise_infra → src/dds/enterprise_infra.py
Freezes os.chdir + patches SCRIPT_DIR to project root.
================================================================================
"""
import os, sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()  # engine/ -> project root
for _sub in ("src/dds", "src/core", "src"):
    _p = str(_ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_saved_cwd  = os.getcwd()
_real_chdir = os.chdir
os.chdir = lambda _p: None

try:
    import enterprise_infra as _ei
    from enterprise_infra import *
    _ei.SCRIPT_DIR = str(_ROOT)
    app             = _ei.app
    _HAS_FASTAPI    = _ei._HAS_FASTAPI
    start_scheduler = _ei.start_scheduler
    write_autostart = _ei.write_autostart
finally:
    os.chdir = _real_chdir
    try: os.chdir(_saved_cwd)
    except Exception: pass

sys.modules.setdefault("cerebro_enterprise_infra", sys.modules[__name__])