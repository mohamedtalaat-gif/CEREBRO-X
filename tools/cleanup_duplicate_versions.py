#!/usr/bin/env python3
"""
cleanup_duplicate_versions.py
==============================
Final pass: remove redundant "| v22.1" tail in module banners that already
start with "CEREBRO-X v22.1 | …".

Examples:
  CEREBRO-X v22.1 | foo.py | v22.1               → CEREBRO-X v22.1 | foo.py
  CEREBRO-X v22.1 | NOVEL ENGINE | v22.1 — NOTE  → CEREBRO-X v22.1 | NOVEL ENGINE — NOTE
  CEREBRO-X v22.1 | foo | v22.1\n                → CEREBRO-X v22.1 | foo\n
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

TEXT_EXTS = {".py", ".md", ".txt", ".html", ".htm", ".yml", ".yaml"}
SKIP_DIRS = {".git", "__pycache__", "CEREBRO_RESULTS"}
SKIP_FILES = {"normalize_project_version.py", "normalize_module_banners.py",
              "cleanup_duplicate_versions.py", "_version.py"}

# Match "CEREBRO-X v22.1 | <NAME> | v22.1[<separator>...]" → drop the redundant
# "| v22.1" middle segment but preserve any trailing descriptor.
PAT = re.compile(
    r"(CEREBRO-X v22\.1\s*\|\s*[^|\n]+?)\s*\|\s*v22\.1(\s*[—\-–]\s*[^\n]+|\s*$)",
    re.MULTILINE,
)
def _repl(m: re.Match[str]) -> str:
    head = m.group(1).rstrip()
    tail = m.group(2)
    return head + tail


def main() -> None:
    total_files = 0
    total_changed = 0
    total_subs = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new, n = PAT.subn(_repl, text)
        total_files += 1
        if n:
            path.write_text(new, encoding="utf-8")
            total_changed += 1
            total_subs += n
            print(f"  ✓ {path.relative_to(ROOT)}  ({n} subs)")
    print(f"\nFiles scanned : {total_files}")
    print(f"Files changed : {total_changed}")
    print(f"Substitutions : {total_subs}")


if __name__ == "__main__":
    main()
