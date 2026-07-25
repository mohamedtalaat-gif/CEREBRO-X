# CEREBRO-X — v18 Patch Notes
**Creator:** Muhammad Talaat (BPharm, R&D Computational Lead)

---

## Fix Summary

### FIX-1 · Multi-Drug Excel Parser
**File:** `src/core/pipeline_patches.py` → `ExcelInputReader._read_drug_sheet()`

**Root cause:**
```python
# BEFORE (broken) — empty-val skip ran FIRST
for row in ws.iter_rows(min_row=4, values_only=True):
    if not row[0]:           # ← rows like "▶  A.  Drug Identity"
        continue             #   passed here (non-empty), then fell
    label = str(row[0])...  #   into field-map lookup with marker text
```
Section-marker rows (`▶  A.  Drug Identity`, `▶  B.  Molecule Inputs`, …)
are non-empty, so they bypassed the `if not row[0]` guard and were treated as
field labels — mapping to garbage keys and silently corrupting `profile`.

**Fix applied:**
```python
# AFTER (v18) — marker guard BEFORE empty-val skip
if cls._is_section_marker(label_raw):   # ← evaluated FIRST
    continue
if not cell0 or not label_raw:          # ← empty-val skip AFTER
    continue
# Then regex-cleaned extraction
val_str = cls._DRUG_NAME_CLEAN_RE.sub("", val_str).strip()
```
Added: `_SECTION_MARKER_PREFIXES`, `_MARKER_RE` (regex), `_is_section_marker()`,
`_DRUG_NAME_CLEAN_RE` (regex for value cleanup).

---

### FIX-2 · h23_biodistribution_animated — mol_profile not received
**File:** `src/viz/cerebro_html5_engine.py`

**Root cause:**
```python
# BEFORE (broken) — mol_profile absent from signature
def h23_biodistribution_animated(science: Dict, top_dds: Dict, drug_name: str) -> str:
    ...
    _mol_class = str(mol_profile.get("molecule_class","")).lower()  # ← NameError
```
`mol_profile` was used inside the function body but never declared as a parameter.
Any call path that reached the fallback recalculation block raised `NameError: mol_profile`.

**Fix applied:**
```python
# AFTER (v18) — mol_profile in signature
def h23_biodistribution_animated(
    science: Dict, top_dds: Dict,
    drug_name: str, mol_profile: Dict      # ← added
) -> str:
```
Call site in `build_html5_report()` updated to pass `mol_profile` explicitly.

---

### FIX-3 · docker-compose container_name removed
**Files:** `docker-compose.yml`, `docker-compose.prod.yml`

**Root cause:**
Hard-coded `container_name:` fields in 4 services (`docker-compose.yml`) and
7 services (`docker-compose.prod.yml`) caused:
- `container name already in use` on re-deploy without `down`
- Incompatibility with `docker compose --scale` and Swarm mode

**Fix applied:**
All `container_name:` lines converted to explanatory comments.
Docker Compose now assigns names automatically via `<project>_<service>_<index>`.

---

## Files changed
| File | Change |
|------|--------|
| `src/core/pipeline_patches.py` | FIX-1: added `import re`, marker constants, `_is_section_marker()`, rewritten `_read_drug_sheet()` |
| `src/viz/cerebro_html5_engine.py` | FIX-2: `mol_profile: Dict` param added to `h23_biodistribution_animated`; call site updated |
| `docker-compose.yml` | FIX-3: 4 × `container_name:` → comments |
| `docker-compose.prod.yml` | FIX-3: 7 × `container_name:` → comments |

---

## v18 — Patch 2 (post-RAR review)

### REAL FIX-1 Location: `run.py::excel_to_yaml()`

The fix previously applied to `pipeline_patches.py::ExcelInputReader._read_drug_sheet()`
was correct but targeted the **wrong call path**. The pipeline invokes `excel_to_yaml()`
in `run.py` directly, which has its own inline parser — and that is where the bug lived.

**Two locations fixed in `run.py`:**

#### A) Primary drug loop (both copies of `excel_to_yaml`)
Added `_is_marker()` / `_is_m2()` guard before `if not label or not val: continue`.
Prevents `▶  A.  Drug Identity`-style rows from populating junk keys in `drug{}`.

#### B) `additional_drugs` loop (first copy only, ~line 360)
**Root cause:**
```python
# BROKEN — empty-val skip on row[1] fires BEFORE marker detection
if not val or str(val).strip() in (...):
    continue                      # ← "Drug 2" row has val=None → SKIPS HERE
if any(m in label for m in DRUG2_MARKERS):   # ← never reached
    in_drug2 = True; continue
```
`Drug 2` / `Drug 3` section-header rows have an empty column B (val = None).
The `if not val: continue` fired immediately, so `in_drug2` was never set to True,
and `additional_drugs` stayed `[]` for every multi-drug Excel.

**Fix:**
```python
# FIXED — markers evaluated FIRST on column A (label), before column B (val) check
if any(m in label for m in DRUG2_MARKERS):   # ← now FIRST
    in_drug2 = True; in_drug3 = False; continue
if any(m in label for m in DRUG3_MARKERS):
    in_drug3 = True; in_drug2 = False; continue
if _is_marker(label):   # generic ▶ / bullet / numbered headers
    continue
# THEN empty-val skip
if not val or val_s in (...):
    continue
```
