# CEREBRO-X — v19 Patch Notes
**Creator:** Muhammad Talaat (BPharm, R&D Computational Lead)
**Date:** 2026-04-27
**Supersedes:** v18 (which had a structural duplication that defeated v18 fixes at runtime)

---

## Executive Summary

v18 contained two unintended structural defects that caused the user-visible
symptom *"the system either doesn't read the Excel at all, or reads the first
drug and clones results for the rest":*

1. **`run.py` was duplicated end-to-end.** The 4,431-line file contained two
   complete copies of every function. Python's top-down evaluation made the
   *second* (older) copy the active one, and that older copy had **no
   multi-drug parsing logic at all**. So `cfg.get("additional_drugs", [])`
   always returned `[]` and the pipeline silently processed Drug 1 only.
2. **A latent `NameError` (`_is_marker`)** in the v18 multi-drug section of
   the *first* copy meant that even if the first copy had been the active
   one, multi-drug Excel files would have crashed.

Both defects were eliminated. The pipeline now parses `1 → N` drugs reliably,
respects researcher overrides on auto-fetched cells, and never silently
fabricates missing values.

---

## FIX-1 · Eliminate `run.py` Duplication

**Before:** 4,431 lines · 29 duplicate function definitions · 2 `__main__` blocks
**After:** 2,683 lines · 0 duplicates · 1 `__main__` block

The duplicate Version-B copy (lines 2,586–4,431 in v18) was deleted in full.
Verified via `ast.parse` — no syntax errors, no orphan references.

---

## FIX-2 · Rewrite `excel_to_yaml` (Fully Robust, Dynamic-N)

**File:** `run.py` lines 270 ff.

The new parser replaces the brittle exact-string-matching approach with:

| Capability | How |
|---|---|
| Dynamic-N drug count | Anchored regex `^drug\s+(\d+)\b` on normalized label — no upper limit on number of drugs |
| Robust label matching | Strip whitespace, embedded `\n\r\t`, parenthetical suffixes, bullet prefixes; lowercase; lookup in canonical map; fallback to partial match |
| Researcher override capture | If a cell normally marked `(fetched automatically)` contains a real value, it is stored with `_provenance=researcher_excel_input` and logged |
| Section-marker tolerance | Help rows (`▶`, `►`, `Fill`, `NOTE`, `If you`, `For Drug 2 & 3 …`) are skipped without false-positive section detection |
| Single + multi-drug uniformity | Returns `cfg["drugs"] = [drug1, …, drugN]`; backward-compat keys `cfg["drug"]` and `cfg["additional_drugs"]` preserved |
| Numeric type coercion | Properties expected to be numbers (`mw_da`, `logp`, `tpsa`, `bbb_native_pct`, …) are auto-cast to `float` |
| Validation | Each drug must have a `name`; empty slots dropped; raises with clear message if no drug has a name |

**Verified against:**
- `CEREBRO_Input_Naloxegol.xlsx` (single drug, 100 formulations) → ✅ 1 drug parsed correctly
- `CEREBRO_Input_Alzheimer_3Drugs.xlsx` (Temozolomide / Donepezil / Galantamine) → ✅ 3 drugs, no cloning, each retains its own SMILES/indication/BBB/clinical_phase
- Synthetic 4-drug case with researcher overrides → ✅ 4 drugs detected, 6 overrides logged transparently

---

## FIX-3 · Tier-6 Predictive Fallback

**File:** `src/core/missing_value_resolver.py`

Added Tier 6 (Class-Typical Estimate) between Tier 5 (analog matching) and
Tier 99 (truly-unknown). Activated only after Tiers 1–5 all fail.

Per project requirements, Tier 6 enforces three guard-rails:

1. **Numeric confidence drop** — `_confidence_score: 30` (out of 100), versus
   ≥80 for Tiers 1–4. Downstream scoring code can use this to weight the
   estimate appropriately.
2. **Explicit disclaimer text** — `_disclaimer` field carries a human-readable
   warning naming the molecule class used and the limit of the estimate.
3. **Manual override flag** — `_overridable: True` signals the report
   renderer to expose a manual-input field so the researcher can replace
   the class-mean with an in-vitro measurement. The Excel parser already
   honours this: any value typed into an "(fetched automatically)" cell
   overrides the predicted value at Tier 0 (highest confidence).

**Class-typical references built in** (population means with citations):

| Property | small_molecule | biologic / mAb | peptide |
|---|---|---|---|
| `half_life_days` | 0.25 d (Smith 2018) | 21 d (Wang 2008) | 0.02 d (Diao & Meibohm 2013) |
| `mw_da` | 350 Da (Lipinski 1997) | 150,000 Da (Reichert 2017) | 3,000 Da (Lau & Dunn 2018) |
| `logp` | 2.5 (Leeson 2007) | −1.5 | −0.5 (Davies 2008) |
| `tpsa` | 90 Å² (Veber 2002) | — | — |
| `hbd` | 2 (Lipinski 1997) | — | — |
| `hba` | 5 (Lipinski 1997) | — | — |

**Tier 99 now triggers only** in the rare case where the molecule class itself
is unrecognized AND no analog could be matched. In practice this is
near-impossible for any real CNS drug.

---

## Verification Matrix

| Scenario | Expected | Result |
|---|---|---|
| Single-drug Excel parse | 1 drug, full SMILES | ✅ |
| 3-drug Excel parse | 3 drugs, distinct SMILES each | ✅ |
| Synthetic 4-drug with overrides | 4 drugs, 6 overrides logged | ✅ |
| `ast.parse(run.py)` | OK | ✅ |
| Duplicate function check | 0 duplicates | ✅ |
| Tier 1 wins when API value present | yes | ✅ |
| Tier 4 (RDKit) wins when SMILES present | yes | ✅ |
| Tier 6 fires for unknown small molecule | value=0.25, conf=30 | ✅ |
| Tier 6 fires for unknown biologic | value=21.0, conf=30 | ✅ |
| Tier 99 only when class unrecognized | yes | ✅ |
