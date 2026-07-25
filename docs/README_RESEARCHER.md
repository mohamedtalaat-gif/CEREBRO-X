> **⚠️ HISTORICAL — describes architecture v13 (`CEREBRO_WORK_V10/` layout
> and file names), which has since been superseded by the v22.1 "C+ Flow"
> architecture. [README.md](../README.md) is the current, accurate document —
> start there.** Kept for historical reference on onboarding intent.

# CEREBRO-X — Researcher Quick-Start Guide (v13, historical)

**Created by:** Muhammad Talaat | CEREBRO-X  
**Version:** v13 (superseded — see notice above) | [contact: mohamed.talaat@pharma.asu.edu.eg]

---

## What Is CEREBRO-X?

A research-prototype computational pipeline that takes your drug and DDS
formulation parameters and runs them through CEREBRO-X's internal 62-criterion
scoring rubric (fast heuristics/correlations, not all independently
validated — see [README.md](../README.md)'s Status section) covering PBPK,
molecular docking, QSAR toxicity, stability, manufacturing, regulatory, and
clinical simulation — generating interactive HTML5 visualizations, animated
Canvas videos, and a unified PDF report.

You never need to touch the code to run a trial, but you should read
[README.md](../README.md)'s Status and validation-snapshot sections before
treating any output as a validated prediction.

---

## Step 1 — Fill the Excel Template

Open `CEREBRO_Input_FINAL_Template.xlsx`.

### Sheet 1: Drug Input (1_Drug_Input)

**You MUST fill (yellow cells):**

| Field | What to put | Example |
|-------|-------------|---------|
| Drug Name | INN or brand name | `Idursulfase` |
| Molecule Class | `small_molecule`, `biologic`, `peptide` | `biologic` |
| Molecule Input | **ONE of**: SMILES / FASTA / PDB ID / InChIKey | `>Heavy_chain\nSETQ...` |

**Optionally fill (helps accuracy):**

| Field | What to put |
|-------|-------------|
| Indication | Disease target | 
| Target Protein | Protein the drug binds |
| Target PDB ID | e.g. `2NAO` (from RCSB PDB) |
| Native BBB % | Published CSF/plasma ratio |
| Clinical Phase | `4`, `3`, `2`, `1`, `preclinical` |

**Leave GREY cells empty** — the pipeline fetches these automatically:
- MW, LogP, Half-life, TPSA, H-bond donors/acceptors, pI, UniProt ID, LogBB, BBB%

**For Drug 2 / Drug 3 (optional multi-drug comparison):**  
Fill the same fields in the Drug 2 / Drug 3 section below.

---

### Sheet 2: DDS Formulations (2_DDS_Formulations)

Add one row per formulation. **Fill the first 22 yellow columns only:**

| Column | What to put | Units |
|--------|-------------|-------|
| Formulation_ID | Unique ID | `VEX-001` |
| Formulation_Name | Descriptive name | `RVG29-Vexosome` |
| Carrier_Type | One of the known types | See below |
| Surface_Ligand | Ligand on surface | `RVG29`, `Transferrin` |
| Size_nm | Target particle size | nm |
| Zeta_Potential_mV | Surface charge | mV (negative = anionic) |
| Shape | `spherical`, `rod`, `disc` | — |
| PDI | Polydispersity index | 0.0–1.0 |
| Elasticity_kPa | Young's modulus | kPa |
| Surface_Ligand_Density_per_nm2 | Ligands per nm² | /nm² |
| PEG_Chain_Length_Da | PEG molecular weight | Da |
| PEGylation_Degree_mol_pct | PEG content | mol% |
| Drug_Loading_pct | Drug/total weight | % |
| Encapsulation_Efficiency_pct | % drug inside NP | % |
| Lipid_to_Drug_Ratio | Molar or mass ratio | — |
| Release_Kinetics | `sustained`, `triggered`, `immediate` | — |
| pH_Trigger | pH for triggered release | 5.0–7.4 |
| Phase_Transition_Temp_C | Lipid Tm | °C (0 = N/A) |
| Manufacturing_Method | How made | `microfluidics`, `sonication` |
| Route | Administration route | `IV`, `intranasal`, `oral` |
| Notes | Free text | — |
| Mechanical_Half_Life_s | Structural stability | seconds |

**Valid Carrier Types:**
`Vexosome`, `Liposome`, `Lipid Nanoparticle`, `Solid Lipid Nanoparticle`,  
`Polymeric Nanoparticle`, `Dendrimeric Nanoparticle`, `Magnetoliposome`,  
`Carbon Nanotube`, `DNA Nanostructure`, `Extracellular Vesicle`

**Leave columns 23–35 empty** — automatically computed by pipeline.

---

### Sheet 5: Pipeline Config (5_Pipeline_Config)

Adjust optional settings:

| Setting | Default | Options |
|---------|---------|---------|
| Run multi-drug comparison | YES | YES / NO |
| n_clinical_patients | 500 | 100–5000 |
| Generate_HTML5 | YES | YES / NO |
| Generate_Canvas_Videos | YES | YES / NO |

---

## Step 2 — Run the Pipeline

```bash
# Navigate to project folder
cd CEREBRO_WORK_V10

# Place your Excel file here
cp CEREBRO_Input_FINAL_Template.xlsx CEREBRO_Input_YourDrug.xlsx

# Stop any previous run
docker compose down
rm -f outputs/trial_index.db

# Start fresh
docker compose up --build -d

# Watch progress
docker compose logs -f cerebro-core
```

---

## Step 3 — Get Your Results

Results appear in `outputs/Trial_N/`:

| File/Folder | Contents |
|-------------|----------|
| `CEREBRO_X_Final_Report_[Drug].pdf` | 15-section unified report (all 62 modules) |
| `html5/CEREBRO_X_Interactive_[Drug].html` | 25 interactive Canvas visualizations |
| `canvas_videos/V01_BBB_Crossing_[Drug].html` | V01 BBB crossing animation |
| `canvas_videos/V02_PBPK_[Drug].html` | V02 PBPK 6-compartment simulation |
| `canvas_videos/V03_Release_[Drug].html` | V03 Drug release kinetics |
| `canvas_videos/V04_Ranking_[Drug].html` | V04 DDS ranking bar animation |
| `canvas_videos/V05_Biodistrib_[Drug].html` | V05 Organ biodistribution |
| `science_modules/science_modules_output.json` | Raw data Part 1 (10 modules) |
| `science_modules/advanced_modules_2_output.json` | Raw data Part 2+3 (40 modules) |

---

## What If My Drug Isn't in Any Database?

If you enter SMILES or FASTA for a completely unknown/novel compound,  
the system will:

1. Compute physicochemical properties directly from the molecular structure
2. Search 220 FDA-approved drugs to find the closest analog by Euclidean distance in physicochemical space (MW, LogP, TPSA, HBD, HBA)
3. Run all 62 modules on **your drug's own properties** (not the analog's)
4. Report: *"Novel drug not found in ChEMBL/PubChem/DrugBank. Closest analog: [X] (similarity Y%)"*
5. Include a confidence level: HIGH / MODERATE / LOW based on analog similarity

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Pipeline stops at PBPK | Check your drug MW — very large biologics (>100 kDa) use biologic-specific PBPK |
| DDS not ranked | Ensure Carrier_Type matches exactly one of the valid types |
| HTML5 not opening | Open directly in Chrome/Firefox — no server needed |
| Docker build fails | Run `docker compose down && docker compose up --build` again |
| ClinicalTrials API 403 | Normal — pipeline uses representative data automatically |
| PubMed API 403 | Normal — curated citations used as fallback |

---

## Support

Muhammad Talaat | CEREBRO-X  
Email: mohamed.talaat@pharma.asu.edu.eg  
