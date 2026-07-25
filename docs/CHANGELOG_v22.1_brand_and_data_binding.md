# CEREBRO-X — v22.1 Brand & Data-Binding Patch

**Patch Date:** 2026-05-08
**Author:** Muhammad Talaat (BPharm, R&D Computational Lead)
**Type:** Bug-fix + brand identity unification + dependency stack refresh

---

## 🎯 Headline

Three critical changes:

1. **The H11 Efficiency Heatmap data bug is fixed.** Cells used to render
   `0%` everywhere because the visualizer was looking up dict keys that
   the DataFrame doesn't produce. Now resolved through a centralized
   metric extractor with alias lookup + derivation rules.
2. **Every user-facing output reads just `CEREBRO-X`** — the version
   `v22.1` is no longer printed in PDF covers, HTML titles, dashboard
   headers, chart titles, video frames, or Excel sheet brand titles.
   Version remains internal only (logs, FastAPI metadata, citations).
3. **The full Python scientific stack is bumped to current stable
   (May 2026):** Python 3.13, NumPy 2.x, pandas 2.3+, scikit-learn 1.7+,
   matplotlib 3.10+, with Inter font baked into the Docker image.

---

## 🐛 The H11 Heatmap Bug

### Symptom

In every interactive HTML5 dashboard, the H11 Efficiency Heatmap rendered
all cells as `0%` regardless of the underlying DDS data — making the
"Top 8 DDS × Performance Matrix" view useless.

### Root Cause

The H-functions `h05_dds_ranking`, `h10_regression_docking`,
`h11_efficiency_heatmap`, `h13_radar`, and `h20_bootstrap` were looking
up dict keys that **do not exist** in the DataFrame produced by
`_run_dds_from_yaml`:

| Looked up by H-functions      | Actually produced by `_run_dds_from_yaml`    |
| ----------------------------- | -------------------------------------------- |
| `BBB_Enhanced_Pct`            | `BBB_Engineering_Score` (0–100)              |
| `CNS_Bioavailability_Pct`     | (not computed — must be derived)             |
| `Endosomal_Escape_Eff`        | `PgP_Escape_Coeff` (0–1)                     |
| `Stealth_Index`               | (not computed — must be derived from PEG %)  |
| `Payload_Efficiency_Pct`      | `encapsulation_efficiency_pct`               |
| `Composite_Score`             | `Principle_Composite_Score` or `Composite_Score_Raw` |

Because every `d.get(missing_key) or 0` returned `0`, every cell rendered
as `0%`.

### Fix

A new module **`src/viz/_dds_metrics.py`** provides the single source of
truth for extracting normalised metrics from any DDS record. Each metric
has an *alias list* tried in priority order, plus a *derivation rule*
that synthesises a value from related columns when no direct alias hits:

```python
"BBB%":      _derive_bbb       # BBB_Engineering_Score → BBB_Enhanced_Pct
"CNS BA%":   _derive_cns_bioavail   # = BBB% × (1 − Off_Target_Liver_pct/100)
"Escape":    _derive_escape    # PgP_Escape_Coeff × 100
"Stealth":   _derive_stealth   # triangular profile peaking at PEG=5%
"Payload%":  _derive_payload   # encapsulation_efficiency_pct
"Score":     _derive_score     # Principle_Composite_Score → BBB_Engineering_Score
```

All five H-functions now call `extract_metric()` / `normalize_row()`
instead of doing direct dict lookups. The fix is therefore robust to
future schema changes — a column rename only requires adding the new
alias to the metric definition.

A `diagnose()` helper additionally inspects a batch of DDS records and
reports coverage. Each H-function calls it and shows a small warning
subtitle if avg-coverage is < 3/6 metrics — making it easy to spot
upstream pipeline failures.

### Verification

A unit test on a realistic DDS record produces:

```
BBB%      = 78.40   (from BBB_Engineering_Score)
CNS BA%   = 56.21   (derived: 78.4 × (1 − 28.3/100))
Escape    = 81.00   (from PgP_Escape_Coeff × 100)
Stealth   = 97.72   (derived from PEGylation 5.2%)
Payload%  = 82.50   (from encapsulation_efficiency_pct)
Score     = 81.20   (from Principle_Composite_Score)
Coverage  = 6/6 metrics populated
```

### Bonus catches

- A JavaScript syntax error in H10 (`'BBB: '+regBBB[i].toFixed(1)+'%`,`Escape: ...`)
  was rewritten with consistent string concatenation.
- The heatmap colour ramp now uses brand-aligned diverging colours
  (`#C62828` → `#0D6E6E`) instead of the previous off-brand
  `rgb(220-220×v, 180×v, 60)` formula.

---

## 🏷️ Brand: "CEREBRO-X" only — no version in titles

### Rule

```
Visible TITLES                 →  "CEREBRO-X"        (no version, ever)
Internal METADATA / FOOTERS    →  "CEREBRO-X v22.1"  (citations, audit trail)
INTERNAL constants             →  PROJECT_VERSION = "22.1"
```

`_version.py` is now organised in two tiers:

```python
PROJECT_NAME       = "CEREBRO-X"            # ← used in all visible TITLES
PROJECT_VERSION    = "22.1"                 # ← internal use only
PROJECT_TITLE_FULL = "CEREBRO-X v22.1"      # ← citations, audit, footers
```

### What was changed

A single normalisation pass `strip_version_from_outputs.py` rewrote 58
substitutions across 33 files. Output-facing surfaces now read just
`CEREBRO-X`:

- PDF cover pages (`final_report.py`, `final_report_unified.py`)
- HTML5 dashboard `<title>` and `<h1>`
- Plotly interactive dashboard titles
- Matplotlib video frame `suptitle()`s
- Excel input/output sheet brand titles
- FastAPI app `title=` field
- HTML report headers

### What was preserved

- `_version.py` (the single source of truth)
- All `CHANGELOG_v*.md` historical records
- FastAPI `version="22.1"` field (that's API metadata, not a brand surface)
- HTTP User-Agent strings (`CEREBRO-X/22.1` — versioned for ChEMBL/PubChem
  rate-limit attribution)
- PDF metadata fields (Author, Producer)

---

## 🎨 Brand Identity Application

### Colour palette canonicalised

A 3-pass colour normalisation across all 9 output-generating modules
plus 3 Excel writers replaced **291 off-brand hex values** with the
canonical CEREBRO-X palette defined in `cerebro_brand.py`:

| Was (off-brand)         | Now (brand)               | Where               |
|-------------------------|---------------------------|---------------------|
| `#1A2235` ×42           | `#1F2937` HAIRLINE        | grid lines          |
| `#3498DB` ×20           | `#C9A84C` GOLD            | accent series       |
| `#27AE60`/`#2ECC71` ×33 | `#0D6E6E` NEURO_POSITIVE  | success / good      |
| `#9B59B6`/`#5C2D91` ×20 | `#7C4DFF` CATEGORICAL[3]  | multi-series purple |
| `#1B7A4A`/`#1A7A4A` ×7  | `#0D6E6E` NEURO_POSITIVE  | rank #1 highlight   |
| `#E74C3C`/`#C0392B` ×16 | `#C62828` ALERT_RED       | danger / warning    |
| `#E67E22` ×6            | `#F57C00` MOLECULE_ORANGE | small-molecule tag  |
| `#F1C40F`/`#C68A00` ×4  | `#C9A84C` GOLD            | premium accent      |
| `#1F4E78` ×48           | `#0f2040` VOID_PANEL      | Excel table headers |
| `#606060` ×31           | `#9CA3AF` TEXT_SECONDARY  | Excel italic notes  |
| `#9C0006` ×13           | `#C62828` ALERT_RED       | Excel alert text    |
| `#5C2D91` etc.          | `#7C4DFF` brand purple    | Excel separators    |

### Typography wired

`run.py` now applies `cerebro_brand.matplotlib_style()` at startup —
21 rcParams covering figure/axes/text/legend colours and `Inter`
font-family fall-backs. Every chart produced anywhere in the pipeline
now inherits the deep-space-and-gold theme automatically.

The Dockerfile installs `fonts-inter` so headless containers render the
canonical typography without per-process font downloads.

### Preserved on purpose

PDF reports retain their light backgrounds (`#FFFFFF`, `#F5F5F5`,
`#F8F9FA`) and pastel highlight tints (`#C6EFCE`, `#FFEB9C`, `#FFC7CE`)
because pharma reviewers expect printable conditional-formatting
conventions on white pages.

---

## 📦 Dependency Stack — Up-to-date

### Python

```
3.11.x   ✓ supported  (lower bound — security through Oct-2027)
3.12.x   ✓ supported
3.13.x   ★ recommended (current stable; latest 3.13.13)
3.14.x   ✓ supported  (upper bound — released Oct-2025)
```

### Scientific stack (verified compatibility, May 2026)

| Package          | Pinned (Docker) | Range (requirements.txt) |
|------------------|-----------------|--------------------------|
| numpy            | 2.2.0           | `>=1.26,<2.5`           |
| pandas           | 2.3.0           | `>=2.1,<3.1`            |
| scipy            | 1.17.0          | `>=1.13,<1.18`          |
| scikit-learn     | 1.8.0           | `>=1.4,<1.9`            |
| matplotlib       | 3.10.0          | `>=3.8,<3.11`           |
| rdkit            | 2024.9.4        | `>=2024.3,<2026.0`      |
| reportlab        | 4.2.5           | `>=4.1,<5.0`            |
| openpyxl         | 3.1.5           | `>=3.1,<4.0`            |
| fastapi          | 0.115.6         | `>=0.110,<0.120`        |
| pydantic         | 2.10.4          | `>=2.6,<3.0`            |

### NumPy 2 compatibility audit

A scan of all 102 .py files found **zero** legacy `np.float_`, `np.int_`,
`np.NaN`, `np.alltrue`, etc. The only NumPy 2 concern was `np.trapz`
(deprecated in 2.x) — replaced with `np.trapezoid` in 4 files
(8 substitutions): `cerebro_62_deep_engine.py`, `science_engines.py`,
`pbbm_engine.py`, `dds_drug_engine.py`.

### pandas 3 compatibility audit

Zero real `DataFrame.append()` calls (all the `.append(` matches were
list/dict appends, which work fine in any pandas version).

---

## ✅ Verification

```
Files scanned             : 102 Python files
Syntax errors             : 0
Off-brand hexes (HTML/PNG): 0
Off-brand hexes (Excel)   : 0
Stale "v22.1" in outputs  : 0
Canonical _version.py     : preserved
FastAPI version metadata  : preserved (22.1 — internal API surface)

H11 smoke test (realistic DDS record):
  Cells populated → 6/6 metrics, all > 50%
  Was: 0/0 (all cells rendered 0%)
  Now: BBB 78%, CNS BA 56%, Escape 81%, Stealth 98%, Payload 82%, Score 81%
```

---

## 📝 New / Modified Files

### New
| File | Purpose |
|------|---------|
| `src/viz/_dds_metrics.py` | Centralized metric extractor (the H11 fix lives here) |
| `strip_version_from_outputs.py` | Re-runnable, idempotent strip pass |
| `normalize_brand_colors.py` | Pass-1 colour normalisation |
| `normalize_brand_colors_pass2.py` | Pass-2 (semantic colours) |
| `normalize_excel_brand_colors.py` | openpyxl-format colour pass |
| `CHANGELOG_v22.1_brand_and_data_binding.md` | This file |

### Modified
- `src/viz/cerebro_html5_engine.py` — H05, H10, H11, H13, H20 rewired through extractor
- `src/viz/cerebro_canvas_engine.py` — brand colour pass
- `src/viz/cerebro_video_engine_v2.py` — brand colour pass
- `src/viz/advanced_viz.py`, `visualization_3d.py` — brand colour pass
- `src/core/final_report.py`, `final_report_unified.py` — brand pass
- `cerebro_completed_excel_writer.py`, `cerebro_multi_drug_comparison.py`,
  `build_input_template.py` — Excel brand colour pass
- `run.py` — applies `matplotlib_style()` at startup; np.trapz → np.trapezoid
- `cerebro_62_deep_engine.py`, `science_engines.py`, `pbbm_engine.py`,
  `dds_drug_engine.py` — np.trapz → np.trapezoid
- `Dockerfile`, `Dockerfile.worker` — Python 3.13, Inter font, latest pins
- `requirements.txt` — Python 3.11+ baseline, NumPy 2 compatible

---

## 🧭 Migrating future code to use the patches

### When you add a new H-function or chart

```python
from src.viz._dds_metrics import get_score, get_pct, normalize_row, METRIC_DEFS

# Don't:  d.get("Composite_Score") or d.get("BBB_Engineering_Score") or 0
# Do:     get_score(d)

# Don't:  d.get("BBB_Enhanced_Pct") or 0
# Do:     get_pct(d, "BBB%")
```

### When you add a new output title

```python
from _version import PROJECT_NAME       # ← visible titles
# Not:                  PROJECT_TITLE   # ← deprecated alias (= FULL form)
# Not:                  PROJECT_TITLE_FULL  # ← only for citations/footers
```

### When you add a new colour

```python
from cerebro_brand import GOLD, NEURO_POSITIVE, ALERT_RED, MOLECULE_ORANGE
# Don't hard-code hex values. The brand module is the source of truth.
```

### When you bump a dependency

Edit `requirements.txt` (range form for developer flows) AND the matching
EXACT pin in `Dockerfile` (production reproducibility). Both must agree
or builds will install one version locally and a different one in
production.
