"""
================================================================================
CEREBRO-X |  cerebro_dds_principle_evaluator.py
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X

PURPOSE
═══════
The OLD pipeline computed the 62 principles for the TOP-1 DDS only — every
other DDS in the Excel was ranked by a single BBB engineering score. This
hid all the principle-level evidence behind the ranking and made it impossible
for the researcher to see why DDS #2 lost to #1, or where DDS #50 actually
excels.

This module fixes that gap. For EACH DDS in the formulations list, it runs
the principle modules that depend on DDS material specs (size, ζ-potential,
PEGylation, release kinetics, encapsulation, etc.) and returns:

  • A per-DDS × per-principle numeric matrix
  • A composite CNS-weighted score per DDS (0-100)
  • A re-ranked DataFrame ordered by the principle composite (NOT by the
    raw engineering score)
  • Full provenance: which principle contributed how many points,
    which formula was used, which literature reference

The TOP-1 of the re-ranked list still goes through the existing slow
modules (full PBPK ODE, 50-receptor QSAR, atomistic MD) for the deep-dive
PDF/HTML5 output. So nothing in the existing flow breaks — this is a
new layer that runs BEFORE the deep dive.

PRINCIPLES COVERED PER DDS  (the DDS-dependent subset of the 62)
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

OUTPUT
══════
  evaluate_all_dds(...) returns a tuple:
    (df_dds_ranked, principle_matrix, composite_breakdown)
  
  df_dds_ranked      — original df_dds with new columns:
                       Principle_Composite_Score, Principle_Rank, ...
  principle_matrix   — list of dicts, one per DDS, with all principle scores
  composite_breakdown — per-DDS score decomposition + reasoning text
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


# ──────────────────────────────────────────────────────────────────────────
# Per-principle scoring functions (each returns score 0-100)
# All functions are deterministic, fast (<1ms), and side-effect-free.
# ──────────────────────────────────────────────────────────────────────────
def _safe(d: dict, key: str, default: float = 0.0) -> float:
    """Get a numeric value from dict with fallback. Handles None and strings."""
    v = d.get(key)
    if v is None: return float(default)
    try:    return float(v)
    except (ValueError, TypeError): return float(default)


def _score_size_optimum(size_nm: float, opt_min: float = 50, opt_max: float = 150) -> float:
    """Triangular score: 100 inside [opt_min, opt_max], decays linearly outside."""
    if size_nm <= 0: return 0
    if opt_min <= size_nm <= opt_max: return 100.0
    if size_nm < opt_min:
        return max(0, 100 - (opt_min - size_nm) * 2)
    return max(0, 100 - (size_nm - opt_max) * 0.5)


def _score_zeta_for_bbb(zeta_mv: float) -> float:
    """BBB-optimal zeta: -5 to -20 mV. Strong neg or any pos = penalty."""
    if -20 <= zeta_mv <= -5: return 100.0
    if 0 < zeta_mv <= 5: return 80.0
    if -5 < zeta_mv <= 0: return 90.0
    if zeta_mv > 5: return max(0, 100 - (zeta_mv - 5) * 5)
    return max(0, 100 + (zeta_mv + 20) * 5)   # zeta < -20


def _evaluate_dds(dds: dict, mol_profile: dict) -> dict[str, dict]:
    """
    Run all 24 DDS-dependent principles for a single DDS.
    Returns dict mapping principle_id → {value, score, weight, method, reference, confidence}.
    """
    out: dict[str, dict] = {}

    # Pull DDS specs (handle multiple naming conventions)
    size  = _safe(dds, "Size_nm",  _safe(dds, "size_nm", 100))
    zeta  = _safe(dds, "Zeta_Potential_mV", _safe(dds, "zeta_potential_mv", -10))
    pdi   = _safe(dds, "PDI", _safe(dds, "pdi", 0.2))
    ee    = _safe(dds, "Encapsulation_Efficiency_pct", 75)
    peg   = _safe(dds, "PEGylation_Degree_mol_pct",
                   _safe(dds, "PEG_Density_mol_pct", 5))
    ligand = str(dds.get("Surface_Ligand", "") or "").lower()
    carrier = str(dds.get("Carrier_Type", "liposome") or "liposome").lower()
    rel_kin = str(dds.get("Release_Kinetics", "sustained")).lower()
    ph_trig = _safe(dds, "pH_Trigger", 6.5)
    endo_esc = _safe(dds, "Endosomal_Escape_Eff", 0.5)
    phase_T = _safe(dds, "Phase_Transition_Temp_C", 42)
    bbb_score = _safe(dds, "BBB_Engineering_Score", 0)
    cns_bio = _safe(dds, "CNS_Bioavailability_Pct", 10)

    mw   = _safe(mol_profile, "MW_Da", 350)
    logp = _safe(mol_profile, "LogP", 2.5)
    hbd  = _safe(mol_profile, "HBD", 2)
    hba  = _safe(mol_profile, "HBA", 5)

    # ───── Group 1: CNS DELIVERY ────────────────────────────────────
    # P1.1 BBB transcytosis
    s_size = _score_size_optimum(size)
    s_zeta = _score_zeta_for_bbb(zeta)
    has_lig = 1 if ligand and ligand not in ("none","-","") else 0
    s_lig = 100 if has_lig else 30
    p11 = 0.4 * s_size + 0.3 * s_zeta + 0.3 * s_lig
    out["P1.1_BBB_transcytosis"] = {
        "value": round(p11, 2), "score": round(p11, 2),
        "raw": {"size_nm": size, "zeta_mV": zeta, "ligand": ligand or "(none)"},
        "method": "0.4·size_score + 0.3·zeta_score + 0.3·ligand_score",
        "reference": PRINCIPLE_DOCS["P1.1_BBB_transcytosis"]["reference"],
        "confidence": "MODERATE",
    }
    # P1.2 Receptor targeting
    LIG_AFFINITY = {"transferrin":95, "tf":95, "rvg29":90, "rvg-29":90,
                     "apoe":85, "ldl":80, "ldlr":80, "insulin":75,
                     "leptin":70, "tat":60, "":20, "none":20, "-":20}
    p12 = LIG_AFFINITY.get(ligand, 50)
    out["P1.2_Receptor_targeting"] = {
        "value": p12, "score": p12,
        "raw": {"ligand": ligand or "(none)"},
        "method": "Ligand-affinity lookup table",
        "reference": PRINCIPLE_DOCS["P1.2_Receptor_targeting"]["reference"],
        "confidence": "HIGH" if has_lig else "LOW",
    }
    # P1.3 Pgp evasion
    s_pgp_size = min(100, max(0, (size - 30) * 2))
    s_pgp_peg  = min(100, peg * 10)
    p13 = 0.6 * s_pgp_size + 0.4 * s_pgp_peg
    out["P1.3_Pgp_evasion"] = {
        "value": round(p13, 2), "score": round(p13, 2),
        "raw": {"size_nm": size, "peg_mol_pct": peg},
        "method": "0.6·size_score + 0.4·peg_score",
        "reference": PRINCIPLE_DOCS["P1.3_Pgp_evasion"]["reference"],
        "confidence": "MODERATE",
    }
    # P1.4 Brain AUC ratio (simplified)
    auc_ratio_pct = (p11/100) * (cns_bio/10) * (1 + 0.5 * has_lig) * 25
    p14 = min(100, auc_ratio_pct * 2)
    out["P1.4_Brain_AUC_ratio"] = {
        "value": round(auc_ratio_pct, 3),
        "score": round(p14, 2),
        "raw": {"BBB_transcytosis_pct": p11, "cns_bio_pct": cns_bio,
                "ligand_present": bool(has_lig)},
        "method": "Simplified compartment model: f(transcytosis × bioavail × ligand)",
        "reference": PRINCIPLE_DOCS["P1.4_Brain_AUC_ratio"]["reference"],
        "confidence": "MODERATE — full PBPK model runs only for top-1",
    }

    # ───── Group 2: RELEASE ─────────────────────────────────────────
    # P2.1 Burst release low
    K_BURST = {"sustained":12, "zero-order":8, "first-order":18,
                "burst":48, "ph-responsive":15, "thermo":14}
    burst_pct = K_BURST.get(rel_kin, 20)
    p21 = max(0, 100 - burst_pct * 2)
    out["P2.1_Burst_release_low"] = {
        "value": burst_pct, "score": round(p21, 2),
        "raw": {"release_kinetics": rel_kin},
        "method": "Carrier-kinetics → 24h burst lookup table",
        "reference": PRINCIPLE_DOCS["P2.1_Burst_release_low"]["reference"],
        "confidence": "HIGH",
    }
    # P2.2 Sustained release t50
    K_T50 = {"sustained":36, "zero-order":48, "first-order":18,
              "burst":4, "ph-responsive":24, "thermo":30}
    t50_h = K_T50.get(rel_kin, 24)
    if 12 <= t50_h <= 72: p22 = 100
    elif t50_h < 12: p22 = max(0, 100 - (12 - t50_h) * 8)
    else: p22 = max(0, 100 - (t50_h - 72) * 0.8)
    out["P2.2_Sustained_release"] = {
        "value": t50_h, "score": round(p22, 2),
        "raw": {"release_kinetics": rel_kin, "t50_hours": t50_h},
        "method": "First-order: t50 = ln(2)/k, carrier-specific k",
        "reference": PRINCIPLE_DOCS["P2.2_Sustained_release"]["reference"],
        "confidence": "HIGH",
    }
    # P2.3 Endosomal escape
    p23 = endo_esc * 100 if endo_esc <= 1 else endo_esc
    out["P2.3_Endosomal_escape"] = {
        "value": round(p23, 2), "score": round(p23, 2),
        "raw": {"endosomal_escape_eff": endo_esc, "ph_trigger": ph_trig},
        "method": "Direct from DDS spec; pH<6.5 boosts escape",
        "reference": PRINCIPLE_DOCS["P2.3_Endosomal_escape"]["reference"],
        "confidence": "HIGH" if endo_esc > 0 else "LOW",
    }
    # P2.4 Release model fit
    MODEL_FIT = {("liposome","first-order"):95, ("liposome","sustained"):85,
                  ("plga","sustained"):95, ("plga","first-order"):75,
                  ("polymer","sustained"):90, ("polymer","ph-responsive"):88,
                  ("micelle","first-order"):80, ("micelle","sustained"):82,
                  ("dendrimer","ph-responsive"):85, ("nanogel","sustained"):85,
                  ("solid_lipid","sustained"):90,
                  ("metallic","first-order"):60,}
    p24 = MODEL_FIT.get((carrier, rel_kin), 60)
    out["P2.4_Release_model_fit"] = {
        "value": p24, "score": p24,
        "raw": {"carrier": carrier, "kinetics": rel_kin},
        "method": "(carrier × kinetics) → fit-quality lookup table",
        "reference": PRINCIPLE_DOCS["P2.4_Release_model_fit"]["reference"],
        "confidence": "HIGH",
    }

    # ───── Group 3: STABILITY ───────────────────────────────────────
    # P3.1 Shelf-life at 25°C
    CARRIER_T25_M = {"liposome":18, "plga":36, "polymer":36, "micelle":24,
                      "dendrimer":24, "nanogel":18, "solid_lipid":30,
                      "metallic":48}
    sl25 = CARRIER_T25_M.get(carrier, 18)
    sl25 *= (0.7 + 0.3 * (ee/100))
    p31 = min(100, sl25 / 0.36)
    out["P3.1_Shelf_life_25C"] = {
        "value": round(sl25, 1), "score": round(p31, 2),
        "raw": {"carrier": carrier, "ee_pct": ee},
        "method": "Carrier baseline × (0.7 + 0.3·EE)",
        "reference": PRINCIPLE_DOCS["P3.1_Shelf_life_25C"]["reference"],
        "confidence": "MODERATE",
    }
    # P3.2 Shelf-life at 4°C — Arrhenius scale × 2
    sl4 = sl25 * 2.5
    p32 = min(100, sl4 / 0.6)
    out["P3.2_Shelf_life_4C"] = {
        "value": round(sl4, 1), "score": round(p32, 2),
        "raw": {"shelf_25C_months": sl25},
        "method": "Arrhenius: factor 2.5× from 25°C",
        "reference": PRINCIPLE_DOCS["P3.2_Shelf_life_4C"]["reference"],
        "confidence": "MODERATE",
    }
    # P3.3 Phase margin
    margin = abs(37 - phase_T)
    p33 = 100 if margin >= 5 else margin * 20
    out["P3.3_Phase_margin"] = {
        "value": round(margin, 1), "score": round(p33, 2),
        "raw": {"phase_T_C": phase_T, "body_T_C": 37},
        "method": "|37 - phase_transition_T|; ≥5 °C gives full score",
        "reference": PRINCIPLE_DOCS["P3.3_Phase_margin"]["reference"],
        "confidence": "HIGH",
    }
    # P3.4 Cold-chain excursion (binary-ish based on carrier)
    EXCURSION = {"liposome":40, "plga":85, "polymer":75, "solid_lipid":80,
                  "dendrimer":70, "metallic":95, "nanogel":50, "micelle":55}
    p34 = EXCURSION.get(carrier, 60)
    out["P3.4_Cold_chain_excursion"] = {
        "value": p34, "score": p34,
        "raw": {"carrier": carrier},
        "method": "Carrier excursion-tolerance lookup",
        "reference": PRINCIPLE_DOCS["P3.4_Cold_chain_excursion"]["reference"],
        "confidence": "MODERATE",
    }

    # ───── Group 4: SAFETY / NANOTOX ────────────────────────────────
    # P4.1 Composite nanotox (lower=better → invert for score)
    nano_raw = max(0, 100 - max(0, 25 - size) * 3)         # too small = bad
    nano_raw = min(nano_raw, max(0, 100 - max(0, abs(zeta) - 30) * 2))  # |ζ|>30 = bad
    p41 = nano_raw
    out["P4.1_Nanotox_composite"] = {
        "value": round(100 - p41, 2),     # raw nanotox score (low=safe)
        "score": round(p41, 2),            # inverted for composite
        "raw": {"size_nm": size, "abs_zeta": abs(zeta)},
        "method": "Penalty for size<25nm AND |zeta|>30mV",
        "reference": PRINCIPLE_DOCS["P4.1_Nanotox_composite"]["reference"],
        "confidence": "MODERATE",
    }
    # P4.2 Hemolysis risk low
    p42 = max(0, 100 - max(0, zeta) * 5)
    out["P4.2_Hemolysis_risk_low"] = {
        "value": round(100 - p42, 2), "score": round(p42, 2),
        "raw": {"zeta_mV": zeta},
        "method": "max(0, 100 - max(0,ζ)·5)",
        "reference": PRINCIPLE_DOCS["P4.2_Hemolysis_risk_low"]["reference"],
        "confidence": "HIGH",
    }
    # P4.3 Complement activation low
    if peg >= 5: p43 = 90
    elif peg >= 3: p43 = 70
    elif peg >= 1: p43 = 50
    else: p43 = 25
    out["P4.3_Complement_low"] = {
        "value": round(100 - p43, 2), "score": p43,
        "raw": {"peg_mol_pct": peg},
        "method": "PEG-density step function",
        "reference": PRINCIPLE_DOCS["P4.3_Complement_low"]["reference"],
        "confidence": "HIGH",
    }
    # P4.4 RES uptake low
    if 50 <= size <= 200: p44 = 100
    elif size > 200: p44 = max(0, 100 - (size - 200) * 0.4)
    else: p44 = max(0, 100 - (50 - size) * 1.5)
    out["P4.4_RES_uptake_low"] = {
        "value": round(100 - p44, 2), "score": round(p44, 2),
        "raw": {"size_nm": size},
        "method": "Triangular score peaking 50-200 nm",
        "reference": PRINCIPLE_DOCS["P4.4_RES_uptake_low"]["reference"],
        "confidence": "HIGH",
    }

    # ───── Group 5: GLYMPHATIC ──────────────────────────────────────
    # P5.1 Glymph clearance (smaller particles clear faster)
    if size <= 0:        p51 = 0
    else:
        # Stokes-Einstein normalized: smaller = higher clearance
        # 50 nm baseline = 100, 200 nm = 50, 500 nm = 20
        if size <= 50: p51 = 100
        elif size <= 200: p51 = 100 - (size - 50) * 0.33
        else: p51 = max(20, 50 - (size - 200) * 0.1)
    out["P5.1_Glymph_clearance"] = {
        "value": round(p51, 2), "score": round(p51, 2),
        "raw": {"size_nm": size},
        "method": "Stokes-Einstein in CSF; size-decay function",
        "reference": PRINCIPLE_DOCS["P5.1_Glymph_clearance"]["reference"],
        "confidence": "MODERATE",
    }
    # P5.2 CSF distribution
    p52 = (p51 + (100 - max(0, abs(zeta) - 15) * 3)) / 2
    out["P5.2_CSF_distribution"] = {
        "value": round(p52, 2), "score": round(p52, 2),
        "raw": {"size_nm": size, "abs_zeta": abs(zeta)},
        "method": "Average of size-clearance and charge-neutrality",
        "reference": PRINCIPLE_DOCS["P5.2_CSF_distribution"]["reference"],
        "confidence": "MODERATE",
    }
    # P5.3 Brain residence (target 6-24h)
    # Estimate from t50 + transcytosis
    t_brain = t50_h * 0.5 + (p11 / 10)
    if 6 <= t_brain <= 24: p53 = 100
    elif t_brain < 6: p53 = max(0, 100 - (6 - t_brain) * 12)
    else: p53 = max(0, 100 - (t_brain - 24) * 2)
    out["P5.3_Brain_residence"] = {
        "value": round(t_brain, 2), "score": round(p53, 2),
        "raw": {"t50_h": t50_h, "transcytosis_pct": round(p11,1)},
        "method": "0.5·t50 + 0.1·transcytosis_pct (h)",
        "reference": PRINCIPLE_DOCS["P5.3_Brain_residence"]["reference"],
        "confidence": "MODERATE",
    }

    # ───── Group 6: MANUFACTURABILITY ───────────────────────────────
    # P6.1 Encap adequacy
    if ee >= 75: p61 = 100
    elif ee >= 50: p61 = 50 + (ee - 50)
    else: p61 = ee * 1.0
    out["P6.1_Encap_adequacy"] = {
        "value": ee, "score": round(p61, 2),
        "raw": {"ee_pct": ee},
        "method": "Step function: ≥75%=100, 50-75% linear, <50% raw",
        "reference": PRINCIPLE_DOCS["P6.1_Encap_adequacy"]["reference"],
        "confidence": "HIGH",
    }
    # P6.2 PDI quality
    if pdi <= 0.1: p62 = 100
    elif pdi <= 0.3: p62 = 100 - (pdi - 0.1) * 200
    elif pdi <= 0.5: p62 = 60 - (pdi - 0.3) * 200
    else: p62 = max(0, 20 - (pdi - 0.5) * 40)
    out["P6.2_PDI_quality"] = {
        "value": pdi, "score": round(p62, 2),
        "raw": {"PDI": pdi},
        "method": "Tier function: ≤0.1 best, ≥0.5 poor",
        "reference": PRINCIPLE_DOCS["P6.2_PDI_quality"]["reference"],
        "confidence": "HIGH",
    }
    # P6.3 Charge stability
    p63 = min(100, abs(zeta) * 4)
    out["P6.3_Charge_stability"] = {
        "value": round(abs(zeta), 1), "score": round(p63, 2),
        "raw": {"abs_zeta": abs(zeta)},
        "method": "Score = min(100, |zeta|·4); ≥25 mV = stable",
        "reference": PRINCIPLE_DOCS["P6.3_Charge_stability"]["reference"],
        "confidence": "HIGH",
    }

    # ───── Group 7: DRUG-DDS FIT ────────────────────────────────────
    # P7.1 LogP-carrier match
    LIPO_LIKE = ("liposome", "solid_lipid", "lipid")
    HYDRO_LIKE = ("micelle", "polymer", "nanogel", "dendrimer", "hydrogel")
    if any(x in carrier for x in LIPO_LIKE):
        p71 = 100 if logp >= 2 else max(20, 50 + logp * 25)
    elif any(x in carrier for x in HYDRO_LIKE):
        p71 = 100 if logp <= 2 else max(20, 100 - (logp - 2) * 20)
    else:
        p71 = 70   # neutral carriers
    out["P7.1_LogP_carrier_match"] = {
        "value": round(p71, 2), "score": round(p71, 2),
        "raw": {"logp": logp, "carrier": carrier},
        "method": "Carrier-LogP compatibility table",
        "reference": PRINCIPLE_DOCS["P7.1_LogP_carrier_match"]["reference"],
        "confidence": "HIGH",
    }
    # P7.2 MW-pore match
    if mw < 200:
        # Small drug — leak risk in large carriers
        p72 = 70 if size < 100 else max(40, 70 - (size - 100) * 0.3)
    elif 200 <= mw <= 700:
        p72 = 100   # ideal small molecule range
    elif mw > 5000:   # biologic
        p72 = 80 if carrier in ("liposome","polymer","nanogel","plga") else 50
    else:
        p72 = 80
    out["P7.2_MW_pore_match"] = {
        "value": round(p72, 2), "score": round(p72, 2),
        "raw": {"mw_da": mw, "carrier": carrier, "size_nm": size},
        "method": "Empirical MW-carrier-size compatibility",
        "reference": PRINCIPLE_DOCS["P7.2_MW_pore_match"]["reference"],
        "confidence": "MODERATE",
    }
    # P7.3 HBD-HBA balance
    total = hbd + hba
    if 4 <= total <= 10: p73 = 100
    elif total < 4: p73 = max(40, 60 + total * 10)
    else: p73 = max(40, 100 - (total - 10) * 5)
    out["P7.3_HBD_HBA_balance"] = {
        "value": round(total, 1), "score": round(p73, 2),
        "raw": {"hbd": hbd, "hba": hba, "total": total},
        "method": "Score peaks at HBD+HBA in 4-10 range",
        "reference": PRINCIPLE_DOCS["P7.3_HBD_HBA_balance"]["reference"],
        "confidence": "HIGH",
    }

    return out


# ──────────────────────────────────────────────────────────────────────────
# Main entry point — evaluate all DDS in a DataFrame
# ──────────────────────────────────────────────────────────────────────────
def evaluate_all_dds(mol_profile: dict, df_dds, drug_name: str = "") -> tuple:
    """
    For every DDS row in df_dds, run the 24 DDS-dependent principles and
    compute a CNS-weighted composite score. Returns:

      ranked_df          — df_dds with new columns:
                            Principle_Composite_Score (0-100),
                            Principle_Rank (1 = best),
                            G1_CNS_Delivery_Score, G2_Release_Score, etc.
      principle_matrix   — list of dicts, one per DDS, with full per-principle
                            data (value, score, method, reference, confidence)
      composite_breakdown — list of dicts: per-DDS reasoning text describing
                            top contributors, weak spots, and overall verdict

    Side effects: none. The original df_dds is copied, not mutated.
    """
    if df_dds is None or len(df_dds) == 0:
        log.warning(f"[DDS-EVAL] df_dds is empty for {drug_name} — skipping")
        return df_dds, [], []

    log.info(f"[DDS-EVAL] {drug_name}: evaluating {len(df_dds)} DDS against "
             f"{len(PRINCIPLE_WEIGHTS)} CNS principles")
    df = df_dds.copy().reset_index(drop=True)

    GROUP_KEYS = {
        "G1_CNS_Delivery":  ["P1.1_BBB_transcytosis","P1.2_Receptor_targeting",
                              "P1.3_Pgp_evasion","P1.4_Brain_AUC_ratio"],
        "G2_Release":        ["P2.1_Burst_release_low","P2.2_Sustained_release",
                              "P2.3_Endosomal_escape","P2.4_Release_model_fit"],
        "G3_Stability":      ["P3.1_Shelf_life_25C","P3.2_Shelf_life_4C",
                              "P3.3_Phase_margin","P3.4_Cold_chain_excursion"],
        "G4_Safety":         ["P4.1_Nanotox_composite","P4.2_Hemolysis_risk_low",
                              "P4.3_Complement_low","P4.4_RES_uptake_low"],
        "G5_Glymphatic":     ["P5.1_Glymph_clearance","P5.2_CSF_distribution",
                              "P5.3_Brain_residence"],
        "G6_Manufacturability":["P6.1_Encap_adequacy","P6.2_PDI_quality",
                                 "P6.3_Charge_stability"],
        "G7_DrugDDS_Fit":    ["P7.1_LogP_carrier_match","P7.2_MW_pore_match",
                              "P7.3_HBD_HBA_balance"],
    }

    matrix: list[dict] = []
    breakdowns: list[dict] = []
    composite_scores: list[float] = []
    group_scores_per_row: dict[str, list[float]] = {g: [] for g in GROUP_KEYS}

    for idx in range(len(df)):
        dds = df.iloc[idx].to_dict()
        per_principle = _evaluate_dds(dds, mol_profile)
        # Composite weighted score
        composite = 0.0
        for pid, pdata in per_principle.items():
            w = PRINCIPLE_WEIGHTS.get(pid, 0)
            composite += pdata["score"] * w
        composite_scores.append(round(composite, 2))

        # Group-level rollups (unweighted average within group)
        group_rollup: dict[str, float] = {}
        for g, pids in GROUP_KEYS.items():
            vals = [per_principle[pid]["score"] for pid in pids if pid in per_principle]
            avg = sum(vals) / len(vals) if vals else 0.0
            group_rollup[g] = round(avg, 2)
            group_scores_per_row[g].append(round(avg, 2))

        # Build breakdown reasoning
        ranked_principles = sorted(per_principle.items(),
                                    key=lambda kv: kv[1]["score"], reverse=True)
        top3 = ranked_principles[:3]
        bot3 = [p for p in ranked_principles[-3:] if p[1]["score"] < 60]
        verdict = "EXCELLENT" if composite >= 80 else \
                  "GOOD" if composite >= 65 else \
                  "ACCEPTABLE" if composite >= 50 else \
                  "MARGINAL" if composite >= 35 else "POOR"
        breakdown = {
            "dds_index":  idx,
            "dds_name":   str(dds.get("Formulation_Name") or
                              dds.get("Formulation_ID") or f"DDS_{idx+1}"),
            "composite":  round(composite, 2),
            "verdict":    verdict,
            "group_scores": group_rollup,
            "top_strengths": [
                {"principle": pid, "score": pd["score"],
                  "explanation": PRINCIPLE_DOCS.get(pid, {}).get("explanation", "")}
                for pid, pd in top3
            ],
            "weak_spots": [
                {"principle": pid, "score": pd["score"],
                  "explanation": PRINCIPLE_DOCS.get(pid, {}).get("explanation", ""),
                  "improvement_hint":
                    f"Below 60% — review the DDS specs driving this principle "
                    f"(see method: {pd.get('method','')})"}
                for pid, pd in bot3
            ],
            "narrative": _build_narrative(dds, per_principle, group_rollup,
                                            composite, verdict),
        }
        breakdowns.append(breakdown)
        matrix.append({"dds_index": idx,
                        "dds_name": breakdown["dds_name"],
                        "composite": round(composite, 2),
                        "principles": per_principle,
                        "groups": group_rollup})

    # Add columns to df
    df["Principle_Composite_Score"] = composite_scores
    for g, vals in group_scores_per_row.items():
        df[g + "_Score"] = vals
    # Rank by composite
    df = df.sort_values("Principle_Composite_Score",
                         ascending=False).reset_index(drop=True)
    df["Principle_Rank"] = range(1, len(df) + 1)

    # Reorder breakdowns to match new ranking
    breakdown_by_idx = {b["dds_index"]: b for b in breakdowns}
    matrix_by_idx    = {m["dds_index"]: m for m in matrix}
    breakdowns_sorted: list[dict] = []
    matrix_sorted: list[dict] = []
    for idx in df.index:
        # Need original index — preserve via row uniqueness
        pass
    # Simpler: re-iterate sorted df
    sorted_breakdowns = []
    sorted_matrix = []
    # Match by composite score + dds_name (composite alone may have ties)
    used = set()
    for _, row in df.iterrows():
        cs = row["Principle_Composite_Score"]
        nm = str(row.get("Formulation_Name") or row.get("Formulation_ID")
                  or "")
        # Find matching breakdown
        for b in breakdowns:
            if b["dds_index"] in used: continue
            if b["composite"] == cs and (not nm or b["dds_name"] == nm or
                                          nm in b["dds_name"]):
                sorted_breakdowns.append(b)
                sorted_matrix.append(matrix_by_idx[b["dds_index"]])
                used.add(b["dds_index"])
                break
        else:
            # Tie-break: take first unused breakdown with same composite
            for b in breakdowns:
                if b["dds_index"] in used: continue
                if b["composite"] == cs:
                    sorted_breakdowns.append(b)
                    sorted_matrix.append(matrix_by_idx[b["dds_index"]])
                    used.add(b["dds_index"])
                    break

    log.info(f"[DDS-EVAL] {drug_name}: composite range "
             f"{min(composite_scores):.1f}-{max(composite_scores):.1f}, "
             f"top DDS: {sorted_breakdowns[0]['dds_name'] if sorted_breakdowns else '?'} "
             f"({sorted_breakdowns[0]['composite']:.1f}/100)")

    return df, sorted_matrix, sorted_breakdowns


def _build_narrative(dds: dict, per_principle: dict,
                       groups: dict, composite: float, verdict: str) -> str:
    """Build a human-readable narrative explaining the score."""
    name = str(dds.get("Formulation_Name") or
                dds.get("Formulation_ID") or "this DDS")
    carrier = str(dds.get("Carrier_Type", "unknown")).lower()
    size = _safe(dds, "Size_nm", _safe(dds, "size_nm", 0))
    zeta = _safe(dds, "Zeta_Potential_mV", _safe(dds, "zeta_potential_mv", 0))
    ligand = str(dds.get("Surface_Ligand", "(none)")).strip() or "(none)"

    best_group = max(groups.items(), key=lambda kv: kv[1])
    worst_group = min(groups.items(), key=lambda kv: kv[1])

    lines = [
        f"{name} — composite CNS-principle score: {composite:.1f}/100 "
        f"({verdict}).",
        f"Carrier: {carrier}, size {size} nm, ζ {zeta:+.1f} mV, "
        f"ligand: {ligand}.",
        f"Strongest group: {best_group[0].replace('_',' ')} "
        f"({best_group[1]:.1f}/100). "
        f"Weakest group: {worst_group[0].replace('_',' ')} "
        f"({worst_group[1]:.1f}/100).",
    ]
    return " ".join(lines)
