"""
================================================================================
CEREBRO-X |  cerebro_dds_principle_evaluator.py
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X

PURPOSE
═══════
This module originally ran its own per-DDS × per-principle scoring engine
(a v21-era 24-principle evaluator: _evaluate_dds/evaluate_all_dds). That job
has since been fully superseded by the 62-criterion Class A/B/C pipeline in
cerebro_62_orchestrator.py + cerebro_62_surrogate_engine.py — the real,
live scoring path — so the old scoring functions were removed here rather
than left as dead code that nothing calls.

What remains is the two lookup tables below (PRINCIPLE_WEIGHTS,
PRINCIPLE_DOCS), which are still genuinely used — cerebro_multi_drug_
comparison.py and cerebro_completed_excel_writer.py import them for
report/documentation labeling. Everything past this docstring is data,
not logic.

PRINCIPLES DOCUMENTED  (the DDS-dependent subset of the original 62)
══════════════════════════════════════════════════════════════════
Group 1 — CNS DELIVERY (CNS-weighted highest)
  P1.1  BBB transcytosis efficiency (size + zeta + ligand)
  P1.2  Receptor-mediated targeting score
  P1.3  P-glycoprotein evasion potential
  P1.4  Brain-to-plasma AUC ratio (simplified PBPK)

Group 2 — RELEASE KINETICS
  P2.1  Burst release at 24h (lower = better controlled)
  P2.2  Sustained release t50 (target window 12-72 h)
  P2.3  Endosomal escape efficiency
  P2.4  Release model fit (Higuchi / Korsmeyer / first-order)

Group 3 — STABILITY
  P3.1  Shelf-life at 25°C (Arrhenius-extrapolated)
  P3.2  Shelf-life at 4°C
  P3.3  Phase transition margin (LCST/UCST distance from 37°C)
  P3.4  Cold-chain excursion tolerance

Group 4 — SAFETY / NANOTOX
  P4.1  Composite nanotoxicity score
  P4.2  Hemolysis risk (zeta + size)
  P4.3  Complement activation potential (PEG density)
  P4.4  RES uptake risk (size > 200 nm penalty)

Group 5 — GLYMPHATIC CLEARANCE
  P5.1  Glymphatic clearance rate (Stokes-Einstein in CSF)
  P5.2  CSF distribution volume
  P5.3  Brain residence half-life

Group 6 — MANUFACTURABILITY (drug-problem layer)
  P6.1  Encapsulation efficiency adequacy
  P6.2  PDI quality (< 0.3 = good, > 0.5 = poor)
  P6.3  Surface charge stability window

Group 7 — DRUG-DDS PHYSICOCHEMICAL FIT
  P7.1  LogP-carrier compatibility
  P7.2  MW-pore-size match
  P7.3  H-bond-donor-acceptor balance for matrix interaction

Each principle returns:
  {
    "value":     numeric score 0-100 OR raw measurement,
    "score":     normalized 0-100 contribution to composite,
    "weight":    weight in composite (CNS-focused),
    "method":    formula or literature method used,
    "reference": citation,
    "confidence": HIGH / MODERATE / LOW
  }

The real per-DDS × per-principle matrix, composite ranking, and re-ranked
DataFrame this module used to produce are now cerebro_62_orchestrator.
evaluate_all_dds_62's job — see that module for the live output contract.
================================================================================
"""
from __future__ import annotations

import logging

log = logging.getLogger("CEREBRO-DDS-PRINCIPLE-EVAL")

# ──────────────────────────────────────────────────────────────────────────
# CNS-FOCUSED PRINCIPLE WEIGHTS  (sum = 1.00)
# ──────────────────────────────────────────────────────────────────────────
PRINCIPLE_WEIGHTS = {
    # Group 1: CNS delivery — highest weight (project focus)
    "P1.1_BBB_transcytosis":      0.12,
    "P1.2_Receptor_targeting":    0.08,
    "P1.3_Pgp_evasion":           0.06,
    "P1.4_Brain_AUC_ratio":       0.11,
    # Group 2: Release kinetics
    "P2.1_Burst_release_low":     0.04,
    "P2.2_Sustained_release":     0.05,
    "P2.3_Endosomal_escape":      0.04,
    "P2.4_Release_model_fit":     0.02,
    # Group 3: Stability
    "P3.1_Shelf_life_25C":        0.03,
    "P3.2_Shelf_life_4C":         0.02,
    "P3.3_Phase_margin":          0.02,
    "P3.4_Cold_chain_excursion":  0.02,
    # Group 4: Safety
    "P4.1_Nanotox_composite":     0.05,
    "P4.2_Hemolysis_risk_low":    0.03,
    "P4.3_Complement_low":        0.03,
    "P4.4_RES_uptake_low":        0.03,
    # Group 5: Glymphatic
    "P5.1_Glymph_clearance":      0.04,
    "P5.2_CSF_distribution":      0.03,
    "P5.3_Brain_residence":       0.04,
    # Group 6: Manufacturability
    "P6.1_Encap_adequacy":        0.03,
    "P6.2_PDI_quality":           0.02,
    "P6.3_Charge_stability":      0.02,
    # Group 7: Drug-DDS fit
    "P7.1_LogP_carrier_match":    0.03,
    "P7.2_MW_pore_match":         0.02,
    "P7.3_HBD_HBA_balance":       0.02,
}
assert abs(sum(PRINCIPLE_WEIGHTS.values()) - 1.00) < 0.001, \
    f"Weights sum {sum(PRINCIPLE_WEIGHTS.values())} != 1.00"

# Principle metadata for explanation sheet
PRINCIPLE_DOCS = {
    "P1.1_BBB_transcytosis": {
        "group": "CNS Delivery",
        "explanation": ("BBB transcytosis efficiency. Optimal nanoparticle "
                         "size 50-150 nm, slight negative zeta (-5 to -20 mV), "
                         "and ligand presence (Tf, RVG29, ApoE) maximize "
                         "receptor-mediated transcytosis."),
        "method": "Score = f(size_optimality, zeta_optimality, ligand_present)",
        "reference": "Pardridge WM (2020) Fluids Barriers CNS 17:62",
        "higher_is_better": True,
    },
    "P1.2_Receptor_targeting": {
        "group": "CNS Delivery",
        "explanation": ("Receptor-mediated targeting score. Surface ligands "
                         "binding to BBB receptors (TfR, LRP1, LDLR) "
                         "increase active uptake by 5-50× over passive."),
        "method": "Score from ligand identity + ligand density per nm²",
        "reference": "Tian X et al (2020) Biomaterials 233:119708",
        "higher_is_better": True,
    },
    "P1.3_Pgp_evasion": {
        "group": "CNS Delivery",
        "explanation": ("P-glycoprotein evasion. Pgp is the main efflux "
                         "barrier at the BBB. Larger NPs (>50 nm) and "
                         "PEGylated surfaces evade Pgp recognition."),
        "method": "Score from size + PEG density",
        "reference": "Loscher W & Potschka H (2005) Nat Rev Neurosci 6:591",
        "higher_is_better": True,
    },
    "P1.4_Brain_AUC_ratio": {
        "group": "CNS Delivery",
        "explanation": ("Simplified brain-to-plasma AUC ratio. Estimated "
                         "from BBB transcytosis × release kinetics × "
                         "drug elimination."),
        "method": "AUC_brain / AUC_plasma (simplified compartment model)",
        "reference": "Hammarlund-Udenaes M et al (2008) Pharm Res 25:1737",
        "higher_is_better": True,
    },
    "P2.1_Burst_release_low": {
        "group": "Release Kinetics",
        "explanation": ("24-hour burst release. Burst > 30% indicates poor "
                         "encapsulation; controlled DDS should release "
                         "<25% in first 24h."),
        "method": "Korsmeyer-Peppas model with carrier-specific rate constant",
        "reference": "Korsmeyer RW et al (1983) Int J Pharm 15:25",
        "higher_is_better": False,
    },
    "P2.2_Sustained_release": {
        "group": "Release Kinetics",
        "explanation": ("Sustained release t50 (time to 50% release). "
                         "Target window 12-72h for CNS dosing."),
        "method": "First-order release: t50 = ln(2)/k",
        "reference": "Higuchi T (1961) J Pharm Sci 50:874",
        "higher_is_better": True,
    },
    "P2.3_Endosomal_escape": {
        "group": "Release Kinetics",
        "explanation": ("Endosomal escape efficiency. After receptor-mediated "
                         "endocytosis at the BBB, the DDS must escape the "
                         "endosome before lysosomal degradation."),
        "method": "Direct from DDS Endosomal_Escape_Eff parameter",
        "reference": "Smith SA et al (2019) Trends Biotechnol 37:1077",
        "higher_is_better": True,
    },
    "P2.4_Release_model_fit": {
        "group": "Release Kinetics",
        "explanation": ("How well the DDS matches an ideal release model "
                         "for its carrier type. Liposomes ≈ first-order, "
                         "PLGA NPs ≈ Higuchi, polymeric micelles ≈ "
                         "Korsmeyer-Peppas."),
        "method": "Carrier-model fit table from cerebro_science_modules",
        "reference": "Costa P & Lobo JM (2001) Eur J Pharm Sci 13:123",
        "higher_is_better": True,
    },
    "P3.1_Shelf_life_25C": {
        "group": "Stability",
        "explanation": ("Predicted shelf life at 25°C using Arrhenius "
                         "extrapolation from accelerated stability data."),
        "method": "Arrhenius: t = A·exp(-Ea/RT) with carrier-specific Ea",
        "reference": "Kennon L (1964) J Pharm Sci 53:815",
        "higher_is_better": True,
    },
    "P3.2_Shelf_life_4C": {
        "group": "Stability",
        "explanation": ("Predicted shelf life at 4°C (refrigerated). "
                         "Most CNS DDS need ≥ 24 months at 4°C for "
                         "commercial viability."),
        "method": "Arrhenius extrapolation",
        "reference": "Kennon L (1964) J Pharm Sci 53:815",
        "higher_is_better": True,
    },
    "P3.3_Phase_margin": {
        "group": "Stability",
        "explanation": ("Distance between body temp (37°C) and DDS phase "
                         "transition. For thermoresponsive DDS, > 5°C "
                         "margin prevents premature unloading."),
        "method": "|37 - phase_transition_temp_C|",
        "reference": "Schmaljohann D (2006) Adv Drug Deliv Rev 58:1655",
        "higher_is_better": True,
    },
    "P3.4_Cold_chain_excursion": {
        "group": "Stability",
        "explanation": ("Tolerance to brief temperature excursions during "
                         "cold-chain transport (e.g., freezer failure)."),
        "method": "Carrier robustness × encapsulation efficiency",
        "reference": "Wang W (2000) Int J Pharm 203:1",
        "higher_is_better": True,
    },
    "P4.1_Nanotox_composite": {
        "group": "Safety",
        "explanation": ("Composite nanotoxicity score. Lower is safer. "
                         "Penalties for high zeta-potential magnitude, "
                         "small size (<20 nm), and reactive surfaces."),
        "method": "Rule-based weighted sum",
        "reference": "Nel A et al (2006) Science 311:622",
        "higher_is_better": False,
    },
    "P4.2_Hemolysis_risk_low": {
        "group": "Safety",
        "explanation": ("Hemolysis risk from positive surface charge "
                         "(cationic NPs disrupt RBC membranes)."),
        "method": "Score = max(0, 100 - max(0, zeta) × 5)",
        "reference": "Goodman CM et al (2004) Bioconjug Chem 15:897",
        "higher_is_better": True,
    },
    "P4.3_Complement_low": {
        "group": "Safety",
        "explanation": ("Complement activation potential. PEG density "
                         "<5 mol% triggers complement; >5% reduces opsonization."),
        "method": "Score from PEG density curve",
        "reference": "Moghimi SM et al (2012) Annu Rev Pharmacol Toxicol 52:481",
        "higher_is_better": True,
    },
    "P4.4_RES_uptake_low": {
        "group": "Safety",
        "explanation": ("Reticulo-endothelial system (liver/spleen) uptake. "
                         "NPs > 200 nm or with positive charge are quickly "
                         "cleared by RES."),
        "method": "Score = 100 if 50<size<200; penalties outside",
        "reference": "Owens DE & Peppas NA (2006) Int J Pharm 307:93",
        "higher_is_better": True,
    },
    "P5.1_Glymph_clearance": {
        "group": "Glymphatic",
        "explanation": ("Glymphatic clearance rate from CSF. Smaller NPs "
                         "(<100 nm) and neutral surfaces clear better via "
                         "the glymphatic system."),
        "method": "Stokes-Einstein in CSF: D = kT/(6πηr)",
        "reference": "Iliff JJ et al (2012) Sci Transl Med 4:147ra111",
        "higher_is_better": True,
    },
    "P5.2_CSF_distribution": {
        "group": "Glymphatic",
        "explanation": ("Volume of CSF distribution. Function of "
                         "size + surface charge."),
        "method": "Empirical fit from glymphatic studies",
        "reference": "Plog BA & Nedergaard M (2018) Annu Rev Pathol 13:379",
        "higher_is_better": True,
    },
    "P5.3_Brain_residence": {
        "group": "Glymphatic",
        "explanation": ("Brain residence half-life. Balance between "
                         "delivery (high) and clearance (low) — "
                         "optimum 6-24h for CNS efficacy."),
        "method": "Combined transcytosis_in / glymphatic_out kinetics",
        "reference": "Pardridge WM (2020) Fluids Barriers CNS 17:62",
        "higher_is_better": True,
    },
    "P6.1_Encap_adequacy": {
        "group": "Manufacturability",
        "explanation": ("Encapsulation efficiency. < 50% = manufacturing "
                         "challenge; > 75% = excellent."),
        "method": "Direct from DDS Encapsulation_Efficiency_pct",
        "reference": "Bangham AD (1965) J Mol Biol 13:238",
        "higher_is_better": True,
    },
    "P6.2_PDI_quality": {
        "group": "Manufacturability",
        "explanation": ("Polydispersity index. PDI < 0.3 = monodisperse; "
                         "PDI > 0.5 = heterogeneous (regulatory concern)."),
        "method": "Score from PDI table",
        "reference": "Danaei M et al (2018) Pharmaceutics 10:57",
        "higher_is_better": True,
    },
    "P6.3_Charge_stability": {
        "group": "Manufacturability",
        "explanation": ("Surface charge magnitude for colloidal stability. "
                         "|ζ| > 25 mV = stable suspension."),
        "method": "Score = min(100, |zeta| × 4)",
        "reference": "Hunter RJ (1981) Zeta Potential in Colloid Science",
        "higher_is_better": True,
    },
    "P7.1_LogP_carrier_match": {
        "group": "Drug-DDS Fit",
        "explanation": ("LogP-carrier compatibility. Lipophilic drugs "
                         "(LogP > 3) match liposomes/lipid NPs; hydrophilic "
                         "(LogP < 1) match polymer micelles/hydrogels."),
        "method": "Carrier-LogP table lookup",
        "reference": "Allen TM & Cullis PR (2013) Adv Drug Deliv Rev 65:36",
        "higher_is_better": True,
    },
    "P7.2_MW_pore_match": {
        "group": "Drug-DDS Fit",
        "explanation": ("Drug MW vs DDS pore/cavity size. Small drugs leak "
                         "from large-pore carriers; large drugs can't load "
                         "into small cavities."),
        "method": "Empirical MW-carrier fit table",
        "reference": "Torchilin VP (2014) Nat Rev Drug Discov 13:813",
        "higher_is_better": True,
    },
    "P7.3_HBD_HBA_balance": {
        "group": "Drug-DDS Fit",
        "explanation": ("H-bond donor/acceptor balance for drug-matrix "
                         "interaction. Critical for sustained release "
                         "from polymeric carriers."),
        "method": "Score from HBD+HBA total range 4-10",
        "reference": "Lipinski CA (1997) Adv Drug Deliv Rev 23:3",
        "higher_is_better": True,
    },
}
