# CEREBRO-X v22.1 Changelog

**Release Date**: 2026-04-28
**Author**: Muhammad Talaat (BPharm, R&D Computational Lead)
**Codename**: *The 62-Principle C+ Flow*

---

## 🎯 Headline Change

CEREBRO-X v22.1 elevates the CNS DDS analysis pipeline from a **25-principle subset** (v21)
to the **complete 62-principle catalog** as defined in `62_Principles.md`, executed
via the **C+ Flow architecture** approved by the project lead on 2026-04-28.

The C+ Flow has three explicit phases:

| Phase | Class | Scope | What Runs |
|-------|-------|-------|-----------|
| 1 | **A — Fast Surrogate** | Every DDS in the input (HTVS) | All 57 surrogate functions for the 62 principles → composite ranking |
| 2 | **B — Deep Physics** | Top-1 DDS only (with Top-2/Top-3 fallback) | Full PBPK ODEs, MM/GBSA, Stokes-Einstein, FEP+ enhanced surrogate, allometric scaling |
| 3 | **C — Translational** | Top-1 DDS only, **after** Class B passes | Pre-IND outline, FTO analysis, 21 CFR Part 11 audit, Grant outline, Patentability score |

Translational deliverables (Class C) follow **Option 2**: structured JSON + summary
scores in v22; full Word/PDF deliverable generation deferred to v23.

---

## 🆕 New Files

| File | Purpose |
|------|---------|
| `cerebro_62_principles_catalog.py` | Master catalog of 62 principles with class, weight, methods, references; auto-normalized CNS-focused weights summing to 1.0 across Classes A+B |
| `cerebro_62_surrogate_engine.py` | 57 Class A surrogate functions (P01–P62 minus translational) |
| `cerebro_62_deep_engine.py` | Class B deep physics: 7 real implementations (P02, P13, P18, P31, P38, P44, P47) + 21 HPC-deferred enhanced-surrogate stand-ins |
| `cerebro_62_translational_engine.py` | Class C structured outputs for P21, P32, P45, P55, P56 |
| `cerebro_62_orchestrator.py` | Master C+ Flow orchestrator: Class A → ranking → Class B (with Top-N fallback) → Class C |

---

## 🔧 Modified Files

### `run.py`
- Drug 1 path now invokes `evaluate_all_dds_62` (replaces v21's 25-principle `evaluate_all_dds`).
- Drug 2..N loop updated identically.
- `all_drug_results` entries now carry `deep_results`, `deep_summary`, `translational`, `fallback_chain`.
- Both HTML5 and PDF generation calls now pass the C+ Flow data through.

### `cerebro_completed_excel_writer.py`
- Three new per-drug sheets generated automatically: `Deep`, `Trans`, `Fallback`.
- All sheets receive color-coding (green = passed, amber = marginal, red = failed).
- The Fallback sheet now includes per-candidate **failure reason** and **transition reason**, plus a detailed list of the failed deep principles for each candidate that was attempted.

### `cerebro_multi_drug_comparison.py`
- Comparison summary now captures `cplus_flow` data per drug.
- Three new cross-drug comparison sheets: `CPlus_Deep_Validation`, `CPlus_Translational`, `CPlus_Fallback_Audit`.

### `src/viz/cerebro_html5_engine.py`
- Four new sections appended: **H27** (Class A surrogate principles for Top-1, with strengths/weaknesses + group rollups), **H28** (Class B deep validation table with verdict badge), **H29** (Class C translational deliverables as cards), **H30** (Top-N fallback audit with reasons).
- `build_html5_report` signature extended with optional C+ Flow kwargs (backward-compatible).

### `src/core/final_report_unified.py`
- Four new PDF sections **14e–14h** appended before Section 15 (Executive Decision):
  - 14e — Class A surrogate Top-1 (composite, group rollups, strengths, weak spots)
  - 14f — Class B deep validation (per-principle table with confidence)
  - 14g — Class C translational deliverables (status, scores, narratives)
  - 14h — Top-N fallback audit trail (verdict per candidate + failure & transition reasons)
- `UnifiedPDFReport.generate()` signature extended with C+ Flow kwargs (backward-compatible).

### `build_input_template.py`
- Instructions tab now includes a section explaining the 62-principle C+ Flow workflow so researchers understand how their inputs flow through the system.
- Output description updated to mention the new Deep / Translational / Fallback sheets.

---

## 🐛 Bug Fixes

- **numpy 2.0 incompatibility**: `np.trapz` was removed in numpy 2.0. Replaced with `np.trapezoid` and added a compatibility shim that falls back to `np.trapz` for older numpy installations. Affected: `deep_P13` (3-compartment PBPK ODE) and `deep_P44` (4-compartment CNS-PBPK ODE).
- **PDF font color crash**: corrected an HTML font-color attribute that was incorrectly receiving the verdict literal (`PASSED`/`MARGINAL`/`FAILED`) instead of a hex color.
- **Drug 2..N PDF call**: removed two invalid kwargs (`metrics`, `analog_result`) that did not exist in `UnifiedPDFReport.generate`'s signature.

---

## 📊 Fallback Chain Enrichment

Per the explicit instruction on 2026-04-28, the fallback chain now records, for every
candidate DDS that was attempted in Class B:

- `rank` — which position in the surrogate ranking was tried
- `surrogate_score` — the Class A composite score
- `deep_passed_pct`, `deep_passed_count`, `deep_total` — full breakdown of the 70% threshold check
- `verdict` — PASSED / MARGINAL / FAILED
- `promoted` — whether this candidate became the final Top-1
- `failure_reason` — human-readable description including which deep principles failed
- `transition_reason` — explicit explanation of why we moved to the next candidate (or stopped)
- `failed_principles` — list of all deep principles that did not validate, with score, value, method, narrative, and confidence
- `passed_principles` — list of validated principles for completeness

This data is surfaced in **Excel** (per-drug `Fallback` sheet + cross-drug `CPlus_Fallback_Audit` sheet),
**HTML5** (section H30), and **PDF** (section 14h).

---

## 📦 Library Audit

All 29 libraries required for the 62-principle C+ Flow are confirmed present in
`requirements.txt` and importable in the runtime environment:

- **Core**: numpy, scipy (incl. integrate), pandas, scikit-learn, matplotlib, openpyxl, yaml, joblib
- **Chemistry**: rdkit, thermo, pint, molmass, mendeleev, periodictable, qcelemental, pubchempy, chembl-webresource-client
- **Bio**: biopython, MDAnalysis
- **ML**: xgboost, shap
- **Network/Graph**: networkx
- **I/O**: reportlab, plotly, imageio, Pillow, requests

---

## ✅ End-to-End Test Reference

The release was validated end-to-end on a multi-drug input containing **Donepezil**
and **Rivastigmine** (both Alzheimer's-indicated) plus 8 BBB-targeting CNS DDS
(Tf-PEG-Liposome, RVG29-PLGA-NP, ApoE-SLN, PEG-Polymer-Micelle, Bare-PLGA,
Tf-SLN-Stealth, RVG29-Liposome-pH, Lf-Micelle-Thermo).

Test results:

| Drug | Top-1 DDS | Class A Composite | Class B Verdict | Translational |
|------|-----------|-------------------|------------------|---------------|
| Donepezil | RVG29-PLGA-NP | 81.3 / 100 (EXCELLENT) | PASSED (75%) | 5/5 generated |
| Rivastigmine | RVG29-PLGA-NP | 82.9 / 100 (EXCELLENT) | PASSED (75%) | 5/5 generated |

Outputs verified across: Completed Excel (19 sheets, including 6 v22 sheets),
Comparison Excel (7 sheets, including 3 v22 sheets), HTML5 (all 4 v22 sections present),
PDF (4 v22 sections rendered).

---

## 🚧 Deferred to v23

The following items are intentionally deferred:
- Full Word/PDF generation for Pre-IND outline (P21) and NIH Grant proposal (P55)
- Live Lens.org / USPTO patent search API integration (P32, P56)
- Full HPC simulations for principles currently using the `_enhanced_surrogate`
  stand-in (21 principles): full MD, DFT, CFD, atomistic docking, constant-pH MD,
  population-MC PBPK, etc.
- E-signature + complete user-action logging + data-integrity hashing (the 3
  features missing from full 21 CFR Part 11 compliance)

---

## 👤 Project Lead Sign-off Required

This release implements the C+ Flow exactly as specified by Muhammad Talaat on
2026-04-28, including:
- All 62 principles run via Class A surrogate (no subsetting)
- Heavy physics on Top-1 only with explicit Top-N fallback
- Translational layer gated on Class B success
- Every result surfaced in every output (Excel, HTML5, PDF, Comparison)
- CNS focus preserved in the principle weighting

— *CEREBRO Therapeutics*
