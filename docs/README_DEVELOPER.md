> **⚠️ HISTORICAL — describes architecture v13 (`CEREBRO_WORK_V10/` layout),
> which has since been superseded by the v22.1 "C+ Flow" architecture
> (`cerebro_62_*.py` + `cerebro_value_resolver/`). Some file paths and line
> counts below are stale. [README.md](../README.md) is the current, accurate
> document — start there.** This file is kept for historical reference on
> the reasoning behind earlier design decisions.

# CEREBRO-X — Developer & Owner Reference (v13, historical)

**Owner:** Muhammad Talaat | R&D Lead  
**Architecture Version:** v13 (superseded — see notice above)  
**Stack:** Python 3.12 · Docker · SQLite · openpyxl · reportlab · Chart.js  

---

## Architecture Overview

```
CEREBRO_WORK_V10/
├── run.py                              # Main pipeline (3,935 lines)
├── src/
│   ├── core/
│   │   ├── cerebro_science_modules.py  # Part 1: 10 modules (66KB)
│   │   ├── cerebro_advanced_modules_2.py  # Part 2+3+4: 50 modules (128KB)
│   │   ├── novel_drug_analog.py        # Novel drug similarity engine (NEW v13)
│   │   ├── final_report_unified.py     # Unified PDF (15 sections, 54KB)
│   │   └── final_report.py             # Legacy PDF (backward compat)
│   ├── viz/
│   │   ├── cerebro_html5_engine.py     # 25 HTML5 Canvas visualizations (94KB)
│   │   ├── cerebro_canvas_engine.py    # 5 Canvas "video" animations (29KB)
│   │   ├── cerebro_video_engine_v2.py  # MP4 fallback (imageio/ffmpeg)
│   │   └── advanced_viz.py             # Legacy viz
│   └── dds/
│       └── enterprise_infra.py         # DDS scoring, ML, DLVO engine (74KB)
├── CEREBRO_Input_FINAL_Template.xlsx   # Master Excel template (5 sheets)
├── CEREBRO_Input_Alzheimer_3Drugs.xlsx # 3-drug Alzheimer test
├── CEREBRO_Input_Naloxegol_v10.xlsx    # Naloxegol single-drug test
├── docker-compose.yml
├── Dockerfile
├── config/
│   ├── dds_config.yaml                 # Auto-generated from Excel
│   └── init.sql                        # SQLite schema
└── outputs/                    # All trial outputs
    └── Trial_N/
        ├── CEREBRO_X_Final_Report_*.pdf
        ├── html5/*.html
        ├── canvas_videos/*.html
        ├── videos/*.mp4
        └── science_modules/*.json
```

---

## The 62-Point Science Engine

### Part 1: `cerebro_science_modules.py` (10 modules)
| Module key | Science point | Method |
|------------|--------------|--------|
| `pbpk_cns` | 13, 44, 56 | 6-compartment ODE (scipy Radau) |
| `release` | 14 | Zero/First/Higuchi/Korsmeyer |
| `shelf_life` | 15 | Arrhenius k₀ + Weibull |
| `nanotoxicity` | 17, 22 | CARPA + Anti-PEG + MPS |
| `qsar_toxicity` | 48, 58, 60 | 50-receptor panel |
| `glymphatic` | 50 | ECM binding + sleep/wake |
| `drug_problems` | 45 | BBB auto-detection |
| `dds_comparison` | 3 | Competitive landscape |
| `allometric` | 2 | Species-specific BBB scaling |
| `stress_test` | 1, 24 | Adversarial scenarios |

### Part 2+3+4: `cerebro_advanced_modules_2.py` (40 modules)
Points 3–12, 16, 18–21, 23, 25–35, 36–43, 46–47, 49, 51–55, 57, 59, 61–62

### Novel Drug Engine: `novel_drug_analog.py` (v13 NEW)
- 220-drug reference database (FDA-approved)
- Euclidean similarity in 7D physicochemical space
- Tanimoto (Morgan FP) when SMILES available
- Confirms database absence via ChEMBL + PubChem APIs

---

## Data Flow

```
Excel Input → excel_to_yaml() → dds_config.yaml
                     ↓
              MoleculeEngine.analyze() → mol_profile dict
              [ChEMBL, PubChem, UniProt APIs + RDKit/BioPython]
                     ↓
              Novel Drug Analog Check → analog_result dict
                     ↓
              CascadeDataEngine.build_mab_dataset() → df_mab
                     ↓
              _run_dds_from_yaml() → df_dds (ranked DataFrame)
                     ↓
              run_all_science_modules() → science_results (Part 1)
              run_all_advanced_modules() → science_results (Part 2+3+4)
                     ↓
              build_html5_report() → 25 visualizations HTML
              run_all_canvas_videos() → 5 Canvas animation HTML
              run_all_videos() → 5 MP4 (optional)
              UnifiedPDFReport.generate() → 15-section PDF
```

---

## Key Configuration Points

### Changing BBB permeability model
In `cerebro_science_modules.py`, `PBPK_CNS_DigitalTwin.simulate()`:
```python
# BBB_integrity modifier per disease stage
DISEASE_BBB_INTEGRITY = {
    "healthy": 1.0, "alzheimer_1": 0.92, "alzheimer_2": 0.80,
    "alzheimer_3": 0.68, "alzheimer_4": 0.55,
    "parkinsons_1": 0.90, "parkinsons_2": 0.75,
}
```

### Adding a new DDS carrier type
In `src/dds/enterprise_infra.py`, `CARRIER_PROFILES` dict:
```python
"My_New_Carrier": {
    "base_BBB_pct": 25.0, "endosomal_escape_base": 0.65,
    "MPS_clearance_h": 18, "stealth_base": 0.60, ...
}
```

### Adding a new science module
1. Add function to `cerebro_advanced_modules_2.py`
2. Add to `run_missing_modules()` or `run_final_modules()`
3. Add visualization to `cerebro_html5_engine.py` if needed
4. Add section to `final_report_unified.py`

---

## API Dependencies

| API | Used For | Fallback |
|-----|---------|---------|
| ChEMBL REST | MW, LogP, binding data | RDKit from SMILES |
| PubChem REST | Physicochemical props | Literature values |
| UniProt REST | Protein sequence, pI | BioPython from FASTA |
| PubMed E-utils | Literature citations | Curated 50-paper database |
| ClinicalTrials.gov | Competitive landscape | Representative NP trials |

Note: All APIs return 403 from Docker's network — the pipeline handles this gracefully with exponential-backoff retry + curated fallback data. In production cloud, APIs work normally.

---

## Running Tests

```bash
# Full integration test (Temozolomide)
python3 -c "
import sys; sys.path.insert(0,'src/core'); sys.path.insert(0,'src/viz')
from cerebro_science_modules import run_all_science_modules
from cerebro_advanced_modules_2 import run_all_advanced_modules
mol = {'MW_Da':194,'LogP':-0.9,'name':'Temozolomide','dose_mg':75}
top = {'size_nm':80,'zeta_potential_mv':-15,'pdi':0.12,'Carrier_Type':'Vexosome'}
from pathlib import Path; d=Path('/tmp/test'); d.mkdir(exist_ok=True)
s1 = run_all_science_modules(mol, top, None, d, 'alzheimer_3', 75)
print(f'Part 1: {len(s1)} modules')
"

# Syntax check all files
python3 -c "
import ast
from pathlib import Path
for f in Path('.').rglob('*.py'):
    try: ast.parse(f.read_text(errors='replace'))
    except SyntaxError as e: print(f'ERROR: {f.name}:{e.lineno}')
print('All syntax OK')
"
```

---

## Extending for Production

### To add real-time API access (lift Docker restrictions):
- Deploy on AWS/GCP/Azure — all APIs accessible
- Set `PUBMED_API_KEY` env var for higher rate limits (from NCBI)
- Set `CHEMBL_API_URL` for enterprise ChEMBL mirror

### To add multi-GPU acceleration:
- PBPK ODE: replace scipy with `diffrax` (JAX-based, GPU-accelerated)
- Molecular docking: replace LIE approximation with AutoDock-GPU

### To add real Tanimoto fingerprints:
```bash
pip install rdkit  # Not included by default to keep Docker image small
```
Then Morgan FP Tanimoto in `novel_drug_analog.py` will activate automatically.

---

## IP & Ownership

All code, algorithms, and design decisions:  
© Muhammad Talaat | CEREBRO-X | 2024–2026  
Not to be shared or deployed without written permission.
