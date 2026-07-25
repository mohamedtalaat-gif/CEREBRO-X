#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_excel_brand_colors.py
================================
openpyxl uses hex colour strings WITHOUT the leading '#' (e.g. '1F4E78'
instead of '#1F4E78'), which means the standard `#XXXXXX` regex sweep
misses every Excel cell-fill / font-colour. This pass closes that gap.

Mapping covers ONLY the foreground colours used as branding accents.
Light pastel cell-highlight tints (good=#C6EFCE, medium=#FFEB9C,
bad=#FFC7CE) are intentionally preserved — they're chosen for
print-ability on white pages and remain compliant with the conditional-
formatting convention pharma reviewers expect.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

# Mapping (openpyxl hex form — no leading '#'):
COLOR_MAP = {
    # Off-brand navy header → VOID_PANEL
    "1F4E78": "0f2040",
    # Off-brand medium grey → TEXT_SECONDARY
    "606060": "9CA3AF",
    # Off-brand alert dark-red text → ALERT_RED
    "9C0006": "C62828",
    # Slightly off gold → canonical GOLD
    "C68A00": "C9A84C",
    # Off-brand purple section separator → CATEGORICAL[3] purple
    "6A1B9A": "7C4DFF",
}

TARGETS = [
    "cerebro_completed_excel_writer.py",
    "cerebro_multi_drug_comparison.py",
    "build_input_template.py",
]


def normalize(p: Path) -> dict:
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return {}
    new = text
    counts: dict[str, int] = {}
    for old, new_val in COLOR_MAP.items():
        # Match the hex inside a quoted string (color="…" or fgColor="…")
        # case-insensitively, but DO NOT touch occurrences in docstrings or
        # comments that happen to contain similar tokens.
        pat = re.compile(rf'(["\'])({re.escape(old)})\1', re.IGNORECASE)
        new, n = pat.subn(lambda m: f'{m.group(1)}{new_val}{m.group(1)}', new)
        if n:
            counts[old] = n
    if new != text:
        p.write_text(new, encoding="utf-8")
    return counts


def main() -> None:
    print("┌─ Excel-format brand colour normalisation")
    print("│  (matches hex inside quoted strings — openpyxl PatternFill / Font format)")
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
