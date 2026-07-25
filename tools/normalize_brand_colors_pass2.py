#!/usr/bin/env python3
"""
normalize_brand_colors_pass2.py
================================
Second-pass colour normalisation — covers the long tail of off-brand hexes
that the first pass didn't know about (deep greens, reds, oranges, blues,
purples, golds-not-quite-gold).

Scope rules:
  • REPLACE   any clearly-semantic off-brand hex (e.g. a green, a red,
              an orange, a purple) with its brand canonical equivalent.
  • PRESERVE  PDF-friendly light backgrounds (#F5F5F5, #F8F9FA, #FFFFFF,
              and the pastel highlight tints) — those are deliberately
              chosen for printability on white pages.
  • PRESERVE  neutral greys used for text/borders (#888, #333, #DDD, …).

Idempotent and re-runnable.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

# ── Mapping table (case-insensitive) ────────────────────────────────────────
COLOR_MAP = {
    # Off-brand GREENS  →  NEURO_POSITIVE  #0D6E6E
    "#1B7A4A": "#0D6E6E",
    "#1A7A4A": "#0D6E6E",
    "#1A4A1A": "#0D6E6E",
    "#2E7D32": "#0D6E6E",
    "#2ECC71": "#0D6E6E",

    # Off-brand REDS  →  ALERT_RED  #C62828
    "#E74C3C": "#C62828",
    "#C0392B": "#C62828",
    "#8B1A1A": "#C62828",

    # Off-brand ORANGES  →  MOLECULE_ORANGE  #F57C00
    "#E67E22": "#F57C00",

    # Off-brand YELLOWS / DULL-GOLDS  →  GOLD  #C9A84C
    "#F1C40F": "#C9A84C",
    "#C68A00": "#C9A84C",

    # Off-brand BLUES (heavy navy / accent blue)  →  VOID_PANEL #0f2040
    "#4A6FE3": "#C9A84C",     # accent blue → gold (it was used as a series colour)
    "#4A90D9": "#C9A84C",
    "#1565C0": "#0f2040",
    "#1F4E78": "#0f2040",
    "#0D1A3A": "#0f2040",
    "#0D2340": "#0f2040",
    "#0A1520": "#0a0a1a",     # deep blue-black → VOID_ELEVATED

    # Off-brand DARK BACKGROUNDS  →  VOID layers
    "#0D1117": "#0a0a1a",
    "#0A0F1A": "#0a0a1a",
    "#252545": "#0f2040",

    # Off-brand WARNING BG TINTS  →  alert-red dark wash (kept consistent)
    "#2A0A0A": "#1A0808",     # narrow shift toward brand-aligned dark red
    "#2A1A1A": "#1A0808",
    "#1A0505": "#1A0808",

    # Off-brand PURPLE  →  CATEGORICAL[3]  #7C4DFF
    "#5C2D91": "#7C4DFF",

    # Beige / off-cream  →  GOLD_LIGHT
    "#E8D5B7": "#D4B563",

    # Note: PDF light backgrounds (#F5F5F5, #FFFFFF, #F8F9FA) and pastel
    # highlight tints (#FFF3F3, #FFEBEE, #FFE4CC, #FFF8E1, #E8F5E9, #F1F8E9,
    # #E8F4F8, #D4E8F0, #B0D0E8, #F7F9FC) are preserved — they're chosen
    # for printability on white pages.
}

# Files where we apply the mapping
TARGETS = [
    "run.py",
    "src/viz/cerebro_html5_engine.py",
    "src/viz/cerebro_canvas_engine.py",
    "src/viz/cerebro_video_engine_v2.py",
    "src/viz/advanced_viz.py",
    "src/viz/visualization_3d.py",
    "src/core/final_report.py",
    "src/core/final_report_unified.py",
    "src/core/pipeline.py",
]


def normalize(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return {}
    new = text
    counts: dict[str, int] = {}
    for old_hex, new_hex in COLOR_MAP.items():
        if old_hex == new_hex:
            continue
        pat = re.compile(re.escape(old_hex), re.IGNORECASE)
        new, n = pat.subn(new_hex, new)
        if n:
            counts[old_hex] = n
    if new != text:
        path.write_text(new, encoding="utf-8")
    return counts


def main() -> None:
    print("┌─ Pass-2 brand colour normalisation")
    total_files = 0
    total_changed = 0
    total_subs = 0
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        total_files += 1
        c = normalize(p)
        n = sum(c.values())
        if n:
            total_changed += 1
            total_subs += n
            tag = ", ".join(f"{k}×{v}" for k,v in c.items())
            print(f"│  ✓ {rel}  ({tag})")
    print(f"├─ Files scanned : {total_files}")
    print(f"├─ Files changed : {total_changed}")
    print(f"└─ Substitutions : {total_subs}")


if __name__ == "__main__":
    main()
