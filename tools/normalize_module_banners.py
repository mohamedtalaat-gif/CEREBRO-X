#!/usr/bin/env python3
"""
normalize_module_banners.py
============================
Second pass — sweeps up:

  • Module-level docstring banners with per-file micro-versions
      e.g.  "CEREBRO-X  |  MONITORING & OBSERVABILITY ENGINE  v1.0.0"
      →     "CEREBRO-X v22.1  |  MONITORING & OBSERVABILITY ENGINE"

  • User-facing matplotlib / dashboard titles that still read
      "CEREBRO-X  |  ..."  (no version)
      →  "CEREBRO-X v22.1  |  ..."

Conservative: only matches the canonical "CEREBRO-X  |  …" prefix; never
touches strings like "CEREBRO-X v22.1 — Bundle Provenance Report" that
already carry the project version.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root
CANONICAL = "CEREBRO-X v22.1"

TEXT_EXTS = {".py", ".md", ".txt", ".html", ".htm", ".yml", ".yaml",
             ".json", ".sql", ".ini", ".cfg", ".sh", ".ps1"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules",
             ".venv", "venv", "outputs", ".mypy_cache"}
SKIP_FILES = {"normalize_project_version.py", "normalize_module_banners.py",
              "_version.py"}


# ── Replacement rules ───────────────────────────────────────────────────────
# Pattern A: "CEREBRO-X  |  <NAME>  v1.0.0"  (with version suffix)
#            → "CEREBRO-X v22.1  |  <NAME>"
#
#   Captures: <NAME> = anything NOT containing "|" and NOT containing the
#   word "v22.1" already. The trailing version is consumed.
#
PAT_BANNER_WITH_MICROVER = re.compile(
    r"CEREBRO-X\s*\|\s*([A-Z0-9][^|\n]*?)\s+v\d+(?:\.\d+){1,3}\b",
    re.IGNORECASE,
)
def _repl_banner_with_microver(m: re.Match[str]) -> str:
    name = m.group(1).strip().rstrip("|").strip()
    # Skip if name itself already contains v22.1
    if "v22.1" in name.lower() or "v22-1" in name.lower():
        return m.group(0)
    return f"{CANONICAL}  |  {name}"


# Pattern B: "CEREBRO-X  |  <Anything>"  with NO version, used in titles
#            → "CEREBRO-X v22.1  |  <Anything>"
# Only fires when "CEREBRO-X" is followed by "  |  " or " | " (pipe sep)
# AND no "v22.1" appears within the next ~80 chars.
#
PAT_TITLE_WITHOUT_VER = re.compile(
    r"CEREBRO-X(\s*\|\s*)(?!v22\.1)",
)
def _repl_title_without_ver(m: re.Match[str]) -> str:
    return f"{CANONICAL}{m.group(1)}"


def should_process(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix.lower() in TEXT_EXTS


def normalize_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    new = text
    n_total = 0

    new, n = PAT_BANNER_WITH_MICROVER.subn(_repl_banner_with_microver, new)
    n_total += n
    new, n = PAT_TITLE_WITHOUT_VER.subn(_repl_title_without_ver, new)
    n_total += n

    if new != text:
        path.write_text(new, encoding="utf-8")
    return n_total


def main() -> None:
    print(f"┌─ Module-banner normalization  →  '{CANONICAL}'")
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
