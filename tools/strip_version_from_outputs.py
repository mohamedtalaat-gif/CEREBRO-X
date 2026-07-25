#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strip_version_from_outputs.py
==============================
Phase-2 directive (2026-05-08): the project name shown in EVERY user-facing
output is *just* "CEREBRO-X" — no version suffix.

The version (`v22.1`) remains as an INTERNAL constant in _version.py for:
  • log lines / startup banners (developer console)
  • API metadata (FastAPI OpenAPI version field)
  • citation strings (academic credit)
  • file metadata (PDF Author/Producer fields)
  • CHANGELOG headings (historical record)

This pass rewrites every output-facing surface — PDF cover titles, HTML
<title> tags, dashboard <h1>s, matplotlib chart titles, video frame
sup-titles, Excel sheet brand titles, FastAPI app(title=…) — to drop the
version suffix and read just "CEREBRO-X".

The script is idempotent and re-runnable.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

# ── Files that count as "output-facing" — anything that ships rendered
#    bytes or pixels to the user (HTML/PDF/PNG/MP4/XLSX content).
OUTPUT_FILES = {
    # Reports / dashboards
    "src/core/final_report.py",
    "src/core/final_report_unified.py",
    "src/core/pipeline.py",
    # Visualisation engines (matplotlib + Canvas + Plotly)
    "src/viz/advanced_viz.py",
    "src/viz/cerebro_html5_engine.py",
    "src/viz/cerebro_canvas_engine.py",
    "src/viz/cerebro_video_engine_v2.py",
    "src/viz/visualization_3d.py",
    # Excel input / output writers
    "build_input_template.py",
    "cerebro_completed_excel_writer.py",
    "cerebro_multi_drug_comparison.py",
    "cerebro_dds_principle_comparison.py",
    "cerebro_per_dds_principles.py",
    # Cinematic engine — figure titles
    "cerebro_cinematic_engine.py",
    # FastAPI surfaces (OpenAPI + dashboard endpoints)
    "src/api/app.py",
    "src/dds/enterprise_infra.py",
    # Inspector reports
    "cerebro_inspector.py",
}

# ── Patterns to strip (in priority order — most specific first) ─────────────
#
# Generic rule: any "CEREBRO-X v22.1" in an output context becomes "CEREBRO-X".
# But keep the "FastAPI(version='22.1')" metadata field (that's an API
# version, not a brand surface).
#
PATTERNS = [
    # 1. " v22.1 — Section" → " — Section"  (banner with em-dash)
    (re.compile(r"CEREBRO-X\s+v22\.1\s*—\s*"), "CEREBRO-X — "),

    # 2. " v22.1 |"  /  " v22.1   |"  →  " |"   (pipe separator banners)
    (re.compile(r"CEREBRO-X\s+v22\.1\s*\|"), "CEREBRO-X |"),

    # 3. " v22.1 ⟶ "  → " ⟶ "  (Excel sheet brand titles)
    (re.compile(r"CEREBRO-X\s+v22\.1\s*⟶"), "CEREBRO-X   ⟶"),

    # 4. " v22.1 (Generated"  → " (Generated"  (PDF footer)
    (re.compile(r"CEREBRO-X\s+v22\.1\b"), "CEREBRO-X"),

    # 5. ASCII variants seen in some scripts: "CEREBRO-X v.22.1" / "v22.1"
    (re.compile(r"CEREBRO-X\s+v\.?22\.1\b"), "CEREBRO-X"),
]

# ── Patterns that must be PRESERVED (not stripped) ──────────────────────────
# These live in _version.py / docstrings / changelogs — never user-output.
PRESERVE_FILES = {
    "_version.py",
    "CHANGELOG_v22.md",
    "CHANGELOG_v22.1_branding.md",
    "CHANGELOG_v22.1_data_binding_fix.md",
    "normalize_project_version.py",
    "normalize_module_banners.py",
    "cleanup_duplicate_versions.py",
    "strip_version_from_outputs.py",
}


def normalize_file(path: Path) -> int:
    """Apply patterns; return number of substitutions made."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    new   = text
    total = 0
    for pat, repl in PATTERNS:
        new, n = pat.subn(repl, new)
        total += n
    if new != text:
        path.write_text(new, encoding="utf-8")
    return total


def main() -> None:
    print("┌─ Stripping v22.1 from output-facing surfaces")
    print(f"│  Root: {ROOT}")
    print("│  Rule: 'CEREBRO-X v22.1' → 'CEREBRO-X' (output context only)")
    print("│  Preserved: _version.py, CHANGELOGs, normalize utilities")
    print("│")

    total_files   = 0
    total_changed = 0
    total_subs    = 0

    # Pass 1: strict whitelist (output files we definitely want stripped)
    for rel in sorted(OUTPUT_FILES):
        path = ROOT / rel
        if not path.exists():
            print(f"│  · skipped (missing): {rel}")
            continue
        total_files += 1
        n = normalize_file(path)
        if n:
            total_changed += 1
            total_subs    += n
            print(f"│  ✓ {rel}  ({n} subs)")

    # Pass 2: scan ALL .py / .html / .md and strip — but skip preserved.
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.name in PRESERVE_FILES:
            continue
        if path.suffix.lower() not in {".py", ".html", ".htm", ".md", ".css"}:
            continue
        rel = str(path.relative_to(ROOT))
        if rel in OUTPUT_FILES:
            continue                           # already handled
        # Skip changelogs and version-tracking docs
        if "CHANGELOG" in path.name or "_version" in path.name:
            continue
        n = normalize_file(path)
        if n:
            total_changed += 1
            total_subs    += n
            print(f"│  ✓ {rel}  ({n} subs)  [pass 2]")

    print("│")
    print(f"├─ Files scanned (whitelist) : {total_files}")
    print(f"├─ Files changed             : {total_changed}")
    print(f"└─ Substitutions             : {total_subs}")


if __name__ == "__main__":
    main()
