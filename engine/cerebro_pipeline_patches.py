# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  cerebro_pipeline_patches.py  —  Module Shim
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Fallback shim: maps cerebro_pipeline_patches → src/core/pipeline_patches.py
================================================================================
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()  # engine/ -> project root
_CORE = str(_ROOT / "src" / "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from pipeline_patches import *
from pipeline_patches import apply_patches

sys.modules.setdefault("cerebro_pipeline_patches", sys.modules[__name__])
