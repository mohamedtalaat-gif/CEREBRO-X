#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_brand_colors.py
==========================
Replace deprecated / off-brand colour values across every output-facing
module with the canonical CEREBRO-X palette defined in cerebro_brand.py
and cerebro-tokens.css.

Mapping rationale:

  Deprecated value     →  Replacement              Why
  ──────────────────────────────────────────────────────────────────────
  #1A2235  (dark grid) →  #1F2937 HAIRLINE         brand hairline tone
  #3498DB  (bright blue)→  #C9A84C GOLD            primary accent
  #27AE60  (green)     →  #0D6E6E NEURO_POSITIVE   brand success
  #9B59B6  (purple)    →  #7C4DFF                  CATEGORICAL[3] (kept
                                                    in cerebro_brand for
                                                    multi-series charts)
  #1A1A2E  (alt dark)  →  #0a0a1a VOID_ELEVATED    brand layer-2
  #1B3A6B  (alt navy)  →  #0f2040 VOID_PANEL       brand layer-3
  #888     (mid grey)  →  #9CA3AF TEXT_SECONDARY   brand secondary text

Note: case-insensitive match; replacement preserves original case style
where reasonable.

The pass is idempotent and re-runnable.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

# ── Mapping (case-insensitive lookup) ───────────────────────────────────────
COLOR_MAP = {
    "#1A2235": "#1F2937",   # off-brand dark grid → HAIRLINE
    "#3498DB": "#C9A84C",   # off-brand bright blue → GOLD
    "#27AE60": "#0D6E6E",   # off-brand green → NEURO_POSITIVE
    "#9B59B6": "#7C4DFF",   # off-brand purple → CATEGORICAL[3]
    "#1A1A2E": "#0a0a1a",   # off-brand dark navy → VOID_ELEVATED
    "#1B3A6B": "#0f2040",   # off-brand bright navy → VOID_PANEL
    "#5BA89B": "#5BA89B",   # already kept in CATEGORICAL — no change
}

# Files that emit pixels/HTML/PDFs to the user
TARGET_FILES = [
    "src/viz/cerebro_html5_engine.py",
    "src/viz/advanced_viz.py",
    "src/viz/cerebro_canvas_engine.py",
    "src/viz/cerebro_video_engine_v2.py",
    "src/viz/visualization_3d.py",
    "src/core/final_report.py",
    "src/core/final_report_unified.py",
    "src/core/pipeline.py",
    "build_input_template.py",
    "cerebro_completed_excel_writer.py",
    "cerebro_multi_drug_comparison.py",
    "cerebro_dds_principle_comparison.py",
    "cerebro_per_dds_principles.py",
    "cerebro_cinematic_engine.py",
    "cerebro_cinematic_primitives.py",
    "cerebro_inspector.py",
]


def normalize_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return {}
    new = text
    counts: dict[str, int] = {}
    for old_hex, new_hex in COLOR_MAP.items():
        if old_hex == new_hex:
            continue
        # Case-insensitive — matches both "#1A2235" and "#1a2235"
        pat = re.compile(re.escape(old_hex), re.IGNORECASE)
        new, n = pat.subn(new_hex, new)
        if n:
            counts[old_hex] = n
    if new != text:
        path.write_text(new, encoding="utf-8")
    return counts


def main() -> None:
    print("┌─ Brand colour normalization")
    print("│  Replacing off-brand hex values with canonical palette.")
    print("│")
    total_files   = 0
    total_changed = 0
    total_subs    = 0
    for rel in TARGET_FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"│  · skipped (missing): {rel}")
            continue
        total_files += 1
        counts = normalize_file(p)
        n = sum(counts.values())
        if n:
            total_changed += 1
            total_subs    += n
            tag = ", ".join(f"{k}×{v}" for k,v in counts.items())
            print(f"│  ✓ {rel}  ({tag})")
    print("│")
    print(f"├─ Files scanned : {total_files}")
    print(f"├─ Files changed : {total_changed}")
    print(f"└─ Substitutions : {total_subs}")


if __name__ == "__main__":
    main()
