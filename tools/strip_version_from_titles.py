#!/usr/bin/env python3
"""
strip_version_from_titles.py
=============================
Phase 3 normalization: strip "v22.1" from VISIBLE TITLES (PDF covers,
HTML <h1>/<title>, chart titles, Excel sheet headings, dashboard
headers) while preserving "CEREBRO-X v22.1" in:

  • Footers / citations  (the standard `footer_line()` output)
  • Report metadata cells  (the "Report Version" row → keep "CEREBRO-X v22.1")
  • PDF document metadata  (title, subject, keywords)
  • Internal logs / banners  (provenance/audit/scientific reproducibility)
  • Internal comments and module docstrings
  • CHANGELOG titles

Strategy
────────
1.  TITLE STRIP — replace patterns that are clearly visible titles:
       fig.suptitle("CEREBRO-X v22.1 | …")    → fig.suptitle("CEREBRO-X | …")
       ax.set_title("CEREBRO-X v22.1 | …")    → ax.set_title("CEREBRO-X | …")
       <h1>CEREBRO-X v22.1</h1>               → <h1>CEREBRO-X</h1>
       <title>CEREBRO-X v22.1 …</title>       → <title>CEREBRO-X …</title>
       Paragraph("CEREBRO-X v22.1", title_s)  → Paragraph("CEREBRO-X", title_s)
       _brand_title(ws, "CEREBRO-X v22.1   ⟶  …")  → "CEREBRO-X   ⟶  …"
       <div class="title">CEREBRO-X v22.1</div>    → <div class="title">CEREBRO-X</div>
       text=f"CEREBRO-X v22.1 …"              → text=f"CEREBRO-X …"

2.  PRESERVE — strings that should keep "CEREBRO-X v22.1":
       footer_line() / footer paragraphs
       ["Report Version", "CEREBRO-X v22.1"]  ← table rows
       Paragraph("Talaat M (2026) CEREBRO-X v22.1. …")  ← citations
       PDF metadata: doc.title = "CEREBRO-X v22.1 …"
       JSON / dict values:  "_pipeline": "CEREBRO-X v22.1"
       Module docstrings / "Created by:" lines
       CHANGELOG_v22.md content

The script is conservative: it only touches lines where the version is
clearly inside a TITLE-emitting context. Anything ambiguous is left
alone for review.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # tools/ -> project root
TEXT_EXTS = {".py", ".html", ".htm", ".md", ".yml", ".yaml", ".txt"}
SKIP_DIRS = {".git", "__pycache__", "CEREBRO_RESULTS", ".pytest_cache", "assets"}
SKIP_FILES = {
    "_version.py", "cerebro_brand.py",
    "normalize_project_version.py", "normalize_module_banners.py",
    "cleanup_duplicate_versions.py", "strip_version_from_titles.py",
    "CHANGELOG_v22.1_branding.md", "CHANGELOG_v22.md",
    "CHANGELOG_v18.md", "CHANGELOG_v19.md",
    "CHANGELOG_v20.md", "CHANGELOG_v21.md",
}


def _strip(s: str) -> str:
    """Strip ' v22.1' from a captured title string."""
    return re.sub(r"\s+v22\.1", "", s)


# ── Patterns: (regex, replacement-callable | string) ───────────────────────
PATTERNS: list[tuple[re.Pattern[str], object]] = [

    # 1. matplotlib chart titles
    (re.compile(
        r'(fig\.suptitle\s*\(\s*f?["\'])CEREBRO-X v22\.1(\s*[|│┃])'),
     r'\1CEREBRO-X\2'),
    (re.compile(
        r'(ax\.set_title\s*\(\s*f?["\'])CEREBRO-X v22\.1(\s*[|│┃])'),
     r'\1CEREBRO-X\2'),
    (re.compile(
        r'(\.set_title\s*\(\s*f?["\'])CEREBRO-X v22\.1(\s+[A-Z])'),
     r'\1CEREBRO-X\2'),
    (re.compile(
        r'(ax\.text\s*\([^,]+,\s*[^,]+,\s*f?["\'])CEREBRO-X v22\.1(\s)'),
     r'\1CEREBRO-X\2'),

    # 2. Plotly title= dict
    (re.compile(
        r'(text\s*=\s*f?["\'])CEREBRO-X v22\.1(\s)'),
     r'\1CEREBRO-X\2'),

    # 3. HTML <h1> / <h2> / <title> / <div class="title">
    (re.compile(r'(<h[1-3][^>]*>[^<]*?)CEREBRO-X v22\.1', re.IGNORECASE),
     r'\1CEREBRO-X'),
    (re.compile(r'(<title[^>]*>[^<]*?)CEREBRO-X v22\.1', re.IGNORECASE),
     r'\1CEREBRO-X'),
    (re.compile(r'(<div\s+class\s*=\s*["\']title["\'][^>]*>)CEREBRO-X v22\.1'),
     r'\1CEREBRO-X'),

    # 4. ReportLab Paragraph titles  — only when used as cover title
    #    Pattern: Paragraph("CEREBRO-X v22.1", <style>) where <style> ends in
    #    title_s / cover_style / title_style (not "small" or "note")
    (re.compile(
        r'(Paragraph\s*\(\s*["\'])CEREBRO-X v22\.1(["\']\s*,\s*'
        r'(?:title|cover|h1|hero)[a-zA-Z_]*\s*\))'),
     r'\1CEREBRO-X\2'),

    # 5. Excel _brand_title(...) calls
    (re.compile(
        r'(_brand_title\s*\(\s*ws\s*,\s*\n?\s*["\'])CEREBRO-X v22\.1(\s+⟶)'),
     r'\1CEREBRO-X\2'),
    (re.compile(
        r'(_brand_title\s*\(\s*ws\s*,\s*["\'])CEREBRO-X v22\.1(\s+⟶)'),
     r'\1CEREBRO-X\2'),

    # 6. Excel openpyxl Comment author
    (re.compile(r'(Comment\s*\([^,]+,\s*["\'])CEREBRO-X v22\.1(["\'])'),
     r'\1CEREBRO-X\2'),

    # 7. <h1 id="…">⚡ CEREBRO-X v22.1</h1>
    (re.compile(r'(⚡\s*)CEREBRO-X v22\.1'),
     r'\1CEREBRO-X'),

    # 8. Comparison report HTML banners with " | " separator
    (re.compile(r'(>\s*)CEREBRO-X v22\.1(\s*[|│]\s*)', re.IGNORECASE),
     r'\1CEREBRO-X\2'),

    # 9. Capability radar / dashboard h1s like "H16 · CEREBRO-X v22.1 …"
    (re.compile(r'((?:H\d+\s*·\s*|·\s*))CEREBRO-X v22\.1(\s+[A-Z])'),
     r'\1CEREBRO-X\2'),

    # 10. Plotly dataset labels: label:'CEREBRO-X v22.1 Coverage'
    (re.compile(r"(label\s*:\s*['\"])CEREBRO-X v22\.1(\s+[A-Z])"),
     r"\1CEREBRO-X\2"),

    # 11. Generic: "CEREBRO-X v22.1 Final Report" / "Dashboard" / "Pipeline Flow"
    #     in title-like contexts (matplotlib text annotations etc.)
    (re.compile(r'(["\'])CEREBRO-X v22\.1(\s+(?:Pipeline Flow|Dashboard|'
                r'Final Report|Interactive Dashboard|Capability Radar|'
                r'DDS Rankings|BBB Crossing Simulation|DDS Ranking|'
                r'Biodistribution|Coverage)["\s])'),
     r'\1CEREBRO-X\2'),

    # 12. log.info banners that are clearly headers (not provenance)
    (re.compile(r'(log\.info\s*\(\s*["\']\s*)CEREBRO-X v22\.1(\s*—\s*[A-Z])'),
     r'\1CEREBRO-X\2'),
    # The MASTER RUNNER banner uses an f-string from _PROJ_TITLE; left alone
    # because we'll redirect the import below.
]


def normalize_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    new = text
    n_total = 0
    for pat, repl in PATTERNS:
        if callable(repl):
            new, n = pat.subn(repl, new)
        else:
            new, n = pat.subn(repl, new)
        n_total += n
    if new != text:
        path.write_text(new, encoding="utf-8")
    return n_total


def should_process(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    return path.suffix.lower() in TEXT_EXTS


def main() -> None:
    print(f"┌─ Stripping ' v22.1' from VISIBLE titles  →  '{__file__}'")
    print("│  (preserving footers, citations, metadata, internal banners)")
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
