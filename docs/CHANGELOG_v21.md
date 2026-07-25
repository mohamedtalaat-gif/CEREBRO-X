# CEREBRO-X — v21 Patch Notes
**Creator:** Muhammad Talaat (BPharm, R&D Computational Lead)
**Date:** 2026-04-27
**Builds on:** v20 (Completed-Data Excel + cross-drug comparison engine)

---

## What v21 Adds

v20 wrote the data the pipeline produced. v21 fixes the actual *evaluation*: it
makes the 25 CNS-weighted principles run for **EVERY DDS in the input Excel**,
not just the top-1, and emits a dedicated **drug × best-DDS champion comparison**
when the run includes multiple drugs. Plus a polished, dashboard-style input
template that stays 100% backward-compatible with the parser.

The v20 pipeline's behaviour:
```
df_dds (e.g. 100 DDS)
    ↓ ranked by single BBB_Engineering_Score (heuristic)
    ↓ pick top-1 DDS
    ↓ run 62 principles for top-1 ONLY
    ↓ result: PDF/HTML5 deep dive for 1 DDS, no principle data for the other 99
```

The v21 pipeline's behaviour:
```
df_dds (e.g. 100 DDS)
    ↓ for EACH DDS: run 25 CNS-weighted principles
    ↓ composite score per DDS (CNS-Delivery 37%, Glymphatic 11%, …)
    ↓ re-rank by Principle_Composite_Score
    ↓ top-1 (now principle-ranked) gets full PBPK/QSAR/MD deep dive
    ↓ Completed Excel: full DDS×Principle matrix, top-10 reasoning, glossary
    ↓ Multi-drug: Champion sheet pairing each drug with its principle-best DDS
```

---

## NEW MODULES

### 1. `cerebro_dds_principle_evaluator.py` — Per-DDS principle evaluator

Runs 25 CNS-weighted principles against every DDS in the formulations list.

**Principle groups (weight share, sum = 1.000):**

| Group | Principles | Weight |
|---|---|---|
| G1 — CNS Delivery | BBB transcytosis, receptor targeting, Pgp evasion, brain AUC | **37%** ← project focus |
| G2 — Release | burst, sustained t50, endosomal escape, model fit | 15% |
| G3 — Stability | shelf-life 25°C, 4°C, phase margin, cold-chain | 9% |
| G4 — Safety | nanotox, hemolysis, complement, RES uptake | 14% |
| G5 — Glymphatic | clearance, CSF distribution, brain residence | **11%** ← CNS focus |
| G6 — Manufacturability | encapsulation, PDI, charge stability | 7% |
| G7 — Drug-DDS Fit | LogP-carrier, MW-pore, HBD/HBA balance | 7% |

CNS-related total weight: **48%** (G1 + G5).

Each principle returns:
- `value`   — raw measurement (e.g. 100 nm size, 18% burst)
- `score`   — normalized 0-100 contribution to composite
- `method`  — formula or lookup-table used
- `reference` — literature citation (DOI when available)
- `confidence` — HIGH / MODERATE / LOW

Score grading:
| Composite | Verdict |
|---|---|
| ≥ 80 | EXCELLENT |
| 65-80 | GOOD |
| 50-65 | ACCEPTABLE |
| 35-50 | MARGINAL |
| < 35 | POOR |

### 2. `build_input_template.py` — Polished input template generator

Generates `CEREBRO_Input_Template.xlsx` — a dashboard-style researcher input
template that is **100% parser-backward-compatible** (same field labels in
column A, same DDS column order, dynamic Drug-N section detection).

**Visual upgrades over v18-v20:**
- Branded NAVY/TEAL title bands with project tagline
- Colour-banded sections (Identity → Auto-fetched → Multi-drug optional)
- Data-validation dropdowns (Molecule Class, Clinical Phase, Carrier Type,
  Release Kinetics, Scale-Up Readiness)
- Cell-level comments on every field explaining what to enter
- Conditional formatting on key DDS numeric columns (Size, Zeta, EE — green
  for healthy ranges, red/yellow for outliers)
- Auto-filter on the DDS sheet header row
- Frozen panes (header rows + DDS name column stay visible)
- A3 landscape print layout with hidden gridlines
- Example DDS row clearly labeled "EXAMPLE — DELETE BEFORE RUN" in red italic

The template also embeds a 9-row Material Library reference sheet (DSPC,
Cholesterol, DOPE, PLGA, PEG, Chitosan, HSA, SPION, PAMAM) with CAS numbers,
MW, LogP, and citations.

---

## EXTENDED MODULES

### 3. `cerebro_completed_excel_writer.py` — three new sheets per drug

Per-drug workbook now emits **8 sheets** (was 5):

| Sheet | Contents | New in v21? |
|---|---|---|
| Overview | Drug × Tier coverage matrix | — |
| Properties | Per-property provenance (Tier, confidence, source, DOI, disclaimer) | — |
| Principles | Flat key:value table of all 62-principle results for the drug | — |
| DDS_Top10 | Top 10 DDS by principle composite | — |
| **DDSxP_Matrix** | **100 DDS × 25 principles, color-graded, openpyxl Comments per cell with method+reference+confidence, frozen panes** | ✅ NEW |
| **Reasoning** | **Top-10 DDS narrative: why each ranked there, top-3 strengths, weak spots with improvement hints** | ✅ NEW |
| Audit_Trail | Full provenance log per (drug, property) | — |
| **Principle_Explanations** | **The 25-principle textbook glossary: ID, group, weight%, higher=better, explanation, method, reference** | ✅ NEW |

### 4. `cerebro_multi_drug_comparison.py` — two new sheets

When ≥ 2 drugs are processed, the comparison Excel now has **5 sheets** (was 3):

| Sheet | Contents | New in v21? |
|---|---|---|
| Overview | CNS-weighted overall ranking | — |
| Per_Principle | Full N-drug × M-metric matrix with winner highlighting | — |
| Tier_Coverage | Per-drug Tier histogram + risk label | — |
| **Champion_DDS_Compare** | **Drug × Best-DDS pair head-to-head: composite, verdict, group rollups, all 25 principles side-by-side, winner cells highlighted green per principle** | ✅ NEW |
| **Scientific_Rationale** | **Plain-language 7-section report: pipeline architecture, principle methodology, comparison logic, validity statement, decision-making guide** | ✅ NEW |

---

## WIRING IN `run.py`

| Step | What it does | Drug 1 | Drug 2..N |
|---|---|---|---|
| 9 / 5 | DDS scoring (basic BBB engineering score from existing engine) | ✓ | ✓ |
| **9b / 5b** | **`evaluate_all_dds()` re-ranks df_dds by Principle_Composite_Score** | **✅ NEW** | **✅ NEW** |
| 10+ | Top-1 DDS (now principle-ranked) feeds science modules / PBPK / QSAR / MD | unchanged | unchanged |
| End | `dds_principle_matrix` + `dds_principle_breakdown` propagated into `all_drug_results[i]` | ✅ | ✅ |
| End | `compare_drugs()` reads `champions` from each drug → emits Champion sheet | ✅ | ✅ |

---

## VERIFICATION

### v21 unit tests
- `cerebro_dds_principle_evaluator.py` — weights sum = 1.0000 ✅, 25 principles ✅, 25 doc entries ✅
- `cerebro_completed_excel_writer.py` — AST OK ✅
- `cerebro_multi_drug_comparison.py` — AST OK ✅
- `build_input_template.py` — AST OK ✅
- `run.py` — AST OK, 6 references to `dds_principle_matrix`, 6 to `breakdown`, 4 to `evaluate_all_dds`, 5 to `Principle_Composite_Score` ✅

### v21 integration tests (all PASSED)

**Test 1: Per-DDS evaluation on real Excel (Naloxegol, 100 DDS)**
- All 100 DDS evaluated against 25 principles
- Composite range: 73.7 — 86.5
- Top: `Tf-SLN-V6` (86.5/100, EXCELLENT) — Transferrin-SLN, 100 nm, ζ -11 mV
- Bottom: `Lf-Micelle` (73.7/100, GOOD) — weak shelf-life and release

**Test 2: Single-drug Completed Excel (Naloxegol)**
- 8 sheets emitted (74,198 bytes)
- DDSxP matrix: 104 rows × 35 cols
- Reasoning sheet: top-10 with full narrative
- Principle_Explanations: 25 entries with method, reference, weight

**Test 3: Multi-drug pipeline (3 drugs × 100 DDS each)**
- Per-drug Completed Excels: 8 sheets each, 74 KB each
- Combined Completed Excel: 18 sheets (3 drugs × 5 sheets + Overview + Audit + Glossary)
- Multi-drug Comparison Excel: 5 sheets including Champion_DDS_Compare
- Champion sheet: composite + verdict + 7 group rollups + 25 per-principle scores
- Cross-drug ranking computed correctly with CNS-weighted scoring

**Test 4: Polished template parser compatibility**
- New template generated (22.6 KB)
- Filled with sample Drug 1 data
- Parser detected: drug name, molecule class, SMILES, formulations, drug 2/3 sections
- Verdict: 100% backward-compatible — no parser changes needed

---

## FILES ADDED IN v21

- `cerebro_dds_principle_evaluator.py` (28 KB) — per-DDS 25-principle evaluator
- `build_input_template.py` (22 KB) — dashboard-style template generator
- `CEREBRO_Input_Template.xlsx` (22 KB) — pre-built template ready for researcher
- `CHANGELOG_v21.md` — this document

## FILES EXTENDED IN v21

- `cerebro_completed_excel_writer.py` — added 3 sheet writers (DDSxP matrix, reasoning, principle explanations)
- `cerebro_multi_drug_comparison.py` — added Champion + Rationale sheets, champions extraction
- `run.py` — Step 9b for Drug 1, Step 5b for Drug 2..N, top-DDS extraction now uses Principle_Composite_Score, dds_principle_matrix/breakdown propagated everywhere

## FILES UNCHANGED

Every file not listed above is byte-identical to v20. The science modules
(`cerebro_science_modules.py`, `cerebro_advanced_modules_2.py`), molecule
engine, ML engine, ADMET engine, PBPK engine, HTML5 engine, PDF engine — all
untouched.

---

## DECISION-GRADE DELIVERABLE

After a v21 run, the researcher gets:

1. **Per-drug Completed Excel** — every property resolved with full provenance,
   100-DDS principle matrix, top-10 narrative, glossary.
2. **Multi-drug Comparison Excel** (when N ≥ 2) — Champion head-to-head,
   per-principle ranking, tier-coverage QC, scientific rationale.
3. **PDF reports + HTML5 dashboards** for each drug's principle-ranked top-1 DDS.

Every numeric output is traceable to:
- Its **source** (API/Library/PubMed/RDKit/Class-mean — Tier 1-99)
- Its **citation** (DOI when available)
- Its **method** (formula or lookup-table referenced in Principle_Explanations)
- Its **confidence percentage**

The researcher can override any value, re-run, and watch the override flow as
Tier-0 (100% confidence) through every downstream calculation. Every decision
made on this output is therefore as rigorous as the experimental data the
researcher is willing to add.
