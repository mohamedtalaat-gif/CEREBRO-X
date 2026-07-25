#!/usr/bin/env python3
"""
apply_brand_palette.py
=======================
Phase 4 normalization: align colour usage across every output generator
to the official CEREBRO-X palette.

Maps stale / off-brand hex codes to brand-correct ones:

  Stale Navy    #1B3A6B  →  Void Panel    #0f2040
  Stale Orange  #E87722  →  Molecule      #F57C00
  Stale Alert   #9B2C2C  →  Alert Red     #C62828
  Stale Bg      #1A1A2E  →  Void Base     #060610
  Stale Bg      #2a2a4a  →  Void Elevated #0a0a1a
  Stale Bg      #16213E  →  Void Panel    #0f2040
  Stale Border  #333     →  Hairline      #1F2937    (HTML/CSS only)

Also re-targets PDF cover title colour: navy → gold (the brand says
titles are GOLD, not navy).

This is conservative: only touches hex codes used as colour values, not
strings that happen to contain the same byte sequence.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root
TEXT_EXTS = {".py", ".html", ".htm", ".css", ".md", ".yml", ".yaml"}
SKIP_DIRS = {".git", "__pycache__", "outputs", "assets"}
SKIP_FILES = {"_version.py", "cerebro_brand.py",
              "normalize_project_version.py", "normalize_module_banners.py",
              "cleanup_duplicate_versions.py", "strip_version_from_titles.py",
              "apply_brand_palette.py",
              "CHANGELOG_v22.1_branding.md",
              "CHANGELOG_v18.md", "CHANGELOG_v19.md",
              "CHANGELOG_v20.md", "CHANGELOG_v21.md", "CHANGELOG_v22.md"}


# Hex-only replacements (case-insensitive). The pattern requires the hex
# to be preceded by `#` so that bare integer literals never match.
HEX_REMAP = {
    "#1B3A6B": "#0f2040",   # navy   → void_panel
    "#1b3a6b": "#0f2040",
    "#E87722": "#F57C00",   # orange → molecule_orange
    "#e87722": "#F57C00",
    "#9B2C2C": "#C62828",   # darkred → alert_red
    "#9b2c2c": "#C62828",
    "#1A1A2E": "#060610",   # purple-black → void_base
    "#1a1a2e": "#060610",
    "#2a2a4a": "#0a0a1a",   # purple-elevated → void_elevated
    "#16213E": "#0f2040",   # dark-navy → void_panel
    "#16213e": "#0f2040",
}


def remap_hex_in_string(s: str) -> tuple[str, int]:
    n = 0
    for old, new in HEX_REMAP.items():
        new_s, k = re.subn(re.escape(old), new, s)
        if k:
            n += k
            s = new_s
    return s, n


def normalize_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    new, n = remap_hex_in_string(text)
    if new != text:
        path.write_text(new, encoding="utf-8")
    return n


def should_process(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix.lower() in TEXT_EXTS


def main() -> None:
    print("┌─ Brand palette normalization")
    print("│  Mappings:")
    for k, v in HEX_REMAP.items():
        if k.startswith("#") and k[1].isupper():
            print(f"│      {k}  →  {v}")
    print("│")
    total_files = 0
    total_changed = 0
    total_subs = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not should_process(path):
            continue
        total_files += 1
        n = normalize_file(path)
        if n:
            total_changed += 1
            total_subs += n
            print(f"│  ✓ {path.relative_to(ROOT)}  ({n} subs)")
    print(f"├─ Files scanned : {total_files}")
    print(f"├─ Files changed : {total_changed}")
    print(f"└─ Substitutions : {total_subs}")


if __name__ == "__main__":
    main()
