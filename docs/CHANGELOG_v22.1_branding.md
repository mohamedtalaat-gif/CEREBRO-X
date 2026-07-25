# CEREBRO-X v22.1 — Branding & Identity Normalization Patch

**Patch Date:** 2026-05-03
**Author:** Muhammad Talaat (BPharm, R&D Computational Lead)
**Type:** Branding/identity unification — no scientific or pipeline-logic changes

---

## 🎯 Headline Change

The project name is now **CEREBRO-X** (no suffixes, no "Enterprise", no
"Platform"), and every output, log line, banner, report, dashboard, PDF
cover, HTML title, FastAPI endpoint, and HTTP User-Agent now reads
**"CEREBRO-X v22.1"** consistently.

A new module `_version.py` is the **single source of truth** for the
project name and version. Every banner is now wired (or wireable) through
this constant, so the next bump (v22.2, v23, …) requires editing exactly
one file.

---

## 🔧 What Changed (Mechanically)

Three normalization passes (`normalize_project_version.py`,
`normalize_module_banners.py`, `cleanup_duplicate_versions.py`) plus a
small set of manual edits rewrote **94 substitutions across 65 files**.

### Strings that disappeared from the codebase
| Stale token | Where it lived | Replaced with |
|---|---|---|
| `CEREBRO-X ENTERPRISE` | run.py, enterprise_infra.py, banners | `CEREBRO-X v22.1` |
| `CEREBRO-X Enterprise` | report covers, README, dashboards | `CEREBRO-X v22.1` |
| `CEREBRO-X v5.0.0` / `v5.1` | pipeline.py, final_report.py, advanced_modules_2.py | `CEREBRO-X v22.1` |
| `CEREBRO-X v22 Phase 5` | inspector, cinematic, 62-engines | `CEREBRO-X v22.1` |
| `CEREBRO-X v18` / `v19` / `v20` / `v21` | "Created by" lines | `CEREBRO-X v22.1` |
| `CEREBRO-X | <NAME> v1.0.0` (module banners) | every `src/` and root file | `CEREBRO-X v22.1 \| <NAME>` |
| `CEREBRO-X/1.0` (HTTP User-Agent) | docking, PDB, QSAR, ADMET resolvers | `CEREBRO-X/22.1` |
| `FastAPI(title=…, version="5.1")` | enterprise_infra.py | `version="22.1"` |

### Specific user-facing surfaces now branded "CEREBRO-X v22.1"
- **PDF cover pages** — `final_report.py`, `final_report_unified.py`, `run.py` PDF builder
- **Master-runner log banner** — pulls from `_version.PROJECT_TITLE`
- **HTML5 dashboards** — `cerebro_html5_engine.py` `<h1>`, capability radar, `<title>`
- **Plotly interactive dashboards** — `advanced_viz.py` title field and HTML `<title>`
- **Matplotlib video frames** — `cerebro_video_engine_v2.py` `suptitle()` / `set_title()`
- **Excel input template** — DDS Formulations / Instructions / Material Library titles
- **FastAPI OpenAPI docs** — title + version metadata
- **Bundle Provenance Report** (cerebro_inspector) — already correct
- **CHANGELOG_v22.md** — header now reads "CEREBRO-X v22.1 Changelog"

### What was deliberately NOT changed
- Stable OS-level identifiers: macOS launchd label `com.cerebro.enterprise`,
  Windows scheduled task name `CEREBRO-X` (renaming would orphan existing
  installations on upgrade).
- Historical changelog filenames: `CHANGELOG_v18.md` … `CHANGELOG_v21.md` —
  these document *past* releases and intentionally retain their version IDs.
- Output filenames: `CEREBRO_X_Report_*.pdf`, `CEREBRO_X_Comparison_Report.html`,
  `CEREBRO_X_Completed_Data_*.xlsx` — filenames intentionally use the
  underscore-form for filesystem portability.
- Python package directory name `cerebro_value_resolver` — it's an import
  path, not a brand surface.

---

## 📦 New Files

| File | Purpose |
|---|---|
| `_version.py` | **Single source of truth.** Defines `PROJECT_TITLE`, `PROJECT_VERSION`, `__version__`, `banner()`, `short_banner()`, citation, copyright. |
| `normalize_project_version.py` | Pass 1 utility. Re-runnable; idempotent. |
| `normalize_module_banners.py` | Pass 2 utility. Re-runnable; idempotent. |
| `cleanup_duplicate_versions.py` | Pass 3 utility. Re-runnable; idempotent. |

The three normalize utilities are kept in the repo so future version
bumps can be applied with one edit to `_version.py` plus one re-run.

---

## ✅ Verification

| Check | Result |
|---|---|
| Stale tokens (`Enterprise`, `v5.x`, `v18-21`, `v22 Phase 5`) | **0** matches |
| Canonical `CEREBRO-X v22.1` references | **201** matches across 65 files |
| Python syntax errors after rewrite | **0** (all 94 .py files parse) |
| `from _version import …` round-trip | ✓ works |
| `from src import __version__` round-trip | ✓ works |

---

## 🧭 How to Bump the Version Next Time

1. Edit `_version.py`:
   ```python
   PROJECT_VERSION = "22.2"
   PROJECT_TITLE   = "CEREBRO-X v22.2"
   ```
2. (Optional) Re-run the three normalize scripts — they'll catch any
   strings that weren't yet wired through `_version.py`.
3. Update README.md and add a new `CHANGELOG_v22.2.md`.

That's it. No grep-and-replace marathon required.
