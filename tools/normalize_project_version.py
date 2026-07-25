#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_project_version.py
=============================
Walks the CEREBRO-X project tree and rewrites every user-facing
identity / version string to the canonical "CEREBRO-X v22.1".

Replacement rules (applied IN ORDER, longest-first to avoid partial overlaps):

  1. Composite tokens  (e.g.  "CEREBRO-X ENTERPRISE — MASTER RUNNER  v2.0.0")
  2. Parametric "CEREBRO-X Enterprise" / "ENTERPRISE PLATFORM" / "Enterprise API"
  3. Stand-alone old version mentions ("CEREBRO-X v5.0.0", "v5.1", "v22 Phase 5",
     "v21", "v20", "v19", "v18")
  4. Bare "CEREBRO-X Enterprise"  →  "CEREBRO-X v22.1"

It does NOT touch:
  • filenames (CEREBRO_X_Report_*.pdf, CEREBRO_X_Comparison_Report.html, etc.)
  • python package names (`cerebro_value_resolver`, `src.core.pipeline`, ...)
  • directory paths
  • binary files (.xlsx, .pdf, .png, .so, .pyc, .db)
  • git / venv / cache directories
"""
from __future__ import annotations
import re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root

CANONICAL = "CEREBRO-X v22.1"

# ── File-type filter ────────────────────────────────────────────────────────
TEXT_EXTS = {
    ".py", ".md", ".txt", ".html", ".htm", ".css", ".js",
    ".yml", ".yaml", ".json", ".sql", ".ini", ".cfg",
    ".sh", ".ps1", ".dockerfile", ".env", ".example",
}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules",
             ".venv", "venv", "CEREBRO_RESULTS", ".mypy_cache"}
SKIP_FILES = {"normalize_project_version.py", "_version.py"}


# ── Replacement patterns ────────────────────────────────────────────────────
# Each entry is (compiled_regex, replacement_string).
# Order matters — longer / more specific patterns must run first.
REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [

    # ── 1. Specific composite banners (master runner / pipeline / infra) ───
    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s*[—\-–]+\s*MASTER\s+RUNNER\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — MASTER RUNNER"),

    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s+PLATFORM\s*[—\-–]+\s*UNIFIED\s+EDITION\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — UNIFIED PIPELINE"),

    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s*[—\-–]+\s*UNIFIED\s+MASTER\s+REPORT\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — UNIFIED MASTER REPORT"),

    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s+INFRASTRUCTURE\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — INFRASTRUCTURE"),

    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s+API\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — API"),

    (re.compile(r"CEREBRO-X\s+ENTERPRISE\s*[—\-–]+\s*UNIFIED\s+PIPELINE\s*v\d+(?:\.\d+){0,2}",
                re.IGNORECASE),
     f"{CANONICAL} — UNIFIED PIPELINE"),

    # ── 2. "CEREBRO-X Enterprise API" (no version suffix on this one) ──────
    (re.compile(r"CEREBRO-X\s+Enterprise\s+API"),
     f"{CANONICAL} API"),

    # ── 3. "CEREBRO-X Enterprise Pipeline" / Platform ──────────────────────
    (re.compile(r"CEREBRO-X\s+Enterprise\s+(Pipeline|Platform)"),
     f"{CANONICAL} \\1"),

    # ── 4. Old version "CEREBRO-X v22 Phase 5" / "v22-PhaseX" ──────────────
    (re.compile(r"CEREBRO-X\s+v22\s+Phase\s+\d+", re.IGNORECASE),
     CANONICAL),

    # ── 5. Old explicit version mentions ("CEREBRO-X v5.0.0", "v5.1",
    #       "v21", "v20", "v19", "v18", and stand-alone "v22") ─────────────
    (re.compile(r"CEREBRO-X\s+v(?:5(?:\.\d+){0,2}|21|20|19|18|22(?!\.\d))"),
     CANONICAL),

    # ── 6. "CEREBRO-X v5 pipeline run" / "CEREBRO-X v5"  (very loose) ──────
    (re.compile(r"CEREBRO-X\s+v5(?!\.\d)"),
     CANONICAL),

    # ── 7. Bare "CEREBRO-X Enterprise" / "CEREBRO-X ENTERPRISE" ────────────
    (re.compile(r"CEREBRO-X\s+ENTERPRISE\b"),
     CANONICAL),
    (re.compile(r"CEREBRO-X\s+Enterprise\b"),
     CANONICAL),

    # ── 8. Internal report metadata fields "Version":"5.0.0 — Unified+Enterprise"
    (re.compile(r'"Version"\s*:\s*"5\.0\.0[^"]*"'),
     '"Version":"22.1"'),

    # ── 9. FastAPI app version literal ("version=\"5.1\"") ─────────────────
    (re.compile(r'(FastAPI\s*\([^)]*version\s*=\s*)["\']5(?:\.\d+){0,2}["\']'),
     r'\1"22.1"'),
]

# Patterns to verify are *gone* after the pass (sanity check)
LEFTOVER_REGEX = re.compile(
    r"CEREBRO-X\s+(?:Enterprise|ENTERPRISE|v(?:5(?:\.\d+){0,2}|18|19|20|21|22(?!\.\d)))",
    re.IGNORECASE,
)


def should_process(path: Path) -> bool:
    """Decide whether a given path is a text file we should rewrite."""
    if path.name in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in TEXT_EXTS:
        return True
    # Edge case: files like .env, .gitignore, .dockerignore
    if path.name in {".env", ".env.example", ".gitignore", ".dockerignore",
                     "Dockerfile", "Dockerfile.worker"}:
        return True
    return False


def normalize_file(path: Path) -> tuple[int, list[str]]:
    """Apply all replacements to a single file. Returns (n_changes, changed_lines)."""
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, []

    rewritten = original
    total_subs = 0
    for pat, repl in REPLACEMENTS:
        rewritten, n = pat.subn(repl, rewritten)
        total_subs += n

    if rewritten != original:
        path.write_text(rewritten, encoding="utf-8")

    # Collect leftover lines for sanity reporting
    leftover_lines: list[str] = []
    for i, line in enumerate(rewritten.splitlines(), 1):
        if LEFTOVER_REGEX.search(line):
            leftover_lines.append(f"  {path.relative_to(ROOT)}:{i}: {line.strip()[:140]}")

    return total_subs, leftover_lines


def main() -> None:
    print(f"┌─ Normalizing project version  →  '{CANONICAL}'")
    print(f"│  Root: {ROOT}")
    print("│")

    total_files = 0
    total_changed = 0
    total_subs = 0
    all_leftovers: list[str] = []

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or not should_process(path):
            continue
        total_files += 1
        n, leftovers = normalize_file(path)
        if n:
            total_changed += 1
            total_subs += n
            print(f"│  ✓ {path.relative_to(ROOT)}  ({n} subs)")
        all_leftovers.extend(leftovers)

    print("│")
    print(f"├─ Files scanned : {total_files}")
    print(f"├─ Files changed : {total_changed}")
    print(f"├─ Substitutions : {total_subs}")
    print("│")

    if all_leftovers:
        print("├─ ⚠ Leftover matches (review manually):")
        for ll in all_leftovers:
            print(ll)
    else:
        print("└─ ✓ No leftover matches — every reference normalized.")


if __name__ == "__main__":
    main()
