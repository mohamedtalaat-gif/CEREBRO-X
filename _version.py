"""
CEREBRO-X  —  Project Identity (Single Source of Truth)
========================================================
Centralized constants for project name, version, branding strings, and
authorship metadata. Every module that emits a banner, title, header,
log line, report cell, dashboard heading, citation, or PDF-metadata
field SHOULD import from this file rather than hard-coding strings.

DESIGN RULE — Two-tier naming
─────────────────────────────
  • PROJECT_NAME       →  visible TITLES (PDF covers, HTML <h1>, chart
                          headings, Excel sheet titles, dashboard headers)
                          ::  "CEREBRO-X"
  • PROJECT_TITLE_FULL →  metadata, footers, citations, provenance lines
                          ::  "CEREBRO-X v22.1"
  • PROJECT_VERSION    →  bare version (User-Agents, FastAPI metadata,
                          report-version cells)
                          ::  "22.1"

This separation keeps the brand surface clean ("CEREBRO-X") while still
preserving versioning for traceability where it matters (audit trails,
citations, file provenance).

Created by: Muhammad Talaat (BPharm, R&D Computational Lead)
"""

# ── Tier 1: visible title (NO version) ──────────────────────────────────────
PROJECT_NAME       = "CEREBRO-X"            # the brand surface — used in TITLES
PROJECT_TAGLINE    = "Computational Pharmaceutical Pipeline for CNS DDS Optimization"

# ── Tier 2: versioning (used in metadata/footer/citation only) ──────────────
PROJECT_VERSION    = "22.1"                 # bare version number
PROJECT_TITLE_FULL = f"{PROJECT_NAME} v{PROJECT_VERSION}"   # "CEREBRO-X v22.1"

# ── Authorship & legal ──────────────────────────────────────────────────────
AUTHOR             = "Muhammad Talaat"
AUTHOR_FULL        = "Muhammad Talaat (BPharm, R&D Computational Lead)"
AUTHOR_EMAIL       = "mohamed.talaat@pharma.asu.edu.eg"

CITATION           = f"Talaat M (2026) {PROJECT_TITLE_FULL}."
COPYRIGHT          = f"© 2024–2026  {AUTHOR}  |  {PROJECT_NAME}"

# ── Convenience aliases (kept for backward compatibility) ───────────────────
# Older code reads PROJECT_TITLE / __title__ — point them at the FULL form,
# which is correct for footers and citations (their historical use).
PROJECT_TITLE      = PROJECT_TITLE_FULL     # deprecated alias
__title__          = PROJECT_TITLE_FULL
__version__        = PROJECT_VERSION
__author__         = AUTHOR
__email__          = AUTHOR_EMAIL


# ── Banner helpers ──────────────────────────────────────────────────────────
def banner(width: int = 80) -> str:
    """ASCII banner suitable for log output / console startup."""
    sep = "=" * width
    line = f"  {PROJECT_NAME}  —  {PROJECT_TAGLINE}"
    return f"{sep}\n{line}\n{sep}"


def short_banner() -> str:
    """One-line banner used at the top of console runs."""
    return f"╔══ {PROJECT_NAME} ══╗"


def footer_line() -> str:
    """Standard footer line for PDFs/HTMLs — INCLUDES version."""
    return f"{PROJECT_TITLE_FULL}  |  {AUTHOR}"


__all__ = [
    "AUTHOR",
    "AUTHOR_EMAIL",
    "AUTHOR_FULL",
    "CITATION",
    "COPYRIGHT",
    "PROJECT_NAME",
    "PROJECT_TAGLINE",
    "PROJECT_TITLE",                        # deprecated alias
    "PROJECT_TITLE_FULL",
    "PROJECT_VERSION",
    "__author__",
    "__email__",
    "__title__",
    "__version__",
    "banner",
    "footer_line",
    "short_banner",
]
