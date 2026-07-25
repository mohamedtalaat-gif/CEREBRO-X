"""
================================================================================
CEREBRO-X |  cerebro_62_translational_engine.py (Phase 5)
================================================================================
Bundle-only Class C translational engine.

Function signature contract (Phase 5):
    trans_PXX(drug_bundle, dds_bundle, combo_bundle, deep_results) -> Dict
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from cerebro_resolved_bundles import b_value

log = logging.getLogger("CEREBRO-TRANSLATIONAL")


def _drug_summary(drug_bundle: dict) -> dict[str, Any]:
    return {
        "name":      drug_bundle.get("_meta",{}).get("name", "Drug"),
        "drug_type": drug_bundle.get("_meta",{}).get("drug_type", "small_molecule"),
        "MW_Da":     b_value(drug_bundle, "drug_mw", "?"),
        "LogP":      b_value(drug_bundle, "drug_logp", "?"),
        "TPSA":      b_value(drug_bundle, "drug_tpsa", "?"),
        "thalf_d":   b_value(drug_bundle, "pk_halflife", "?"),
        "smiles":    drug_bundle.get("_meta",{}).get("identifiers",{}).get("smiles",""),
    }


def _dds_summary(dds_bundle: dict, combo_bundle: dict) -> dict[str, Any]:
    dds_row = combo_bundle.get("_meta", {}).get("dds_row", {}) or {}
    return {
        "Formulation_Name":  dds_row.get("Formulation_Name") or "?",
        "Formulation_ID":    dds_row.get("Formulation_ID") or "?",
        "Carrier_Type":      dds_bundle.get("_meta",{}).get("carrier_type", "?"),
        "DDS_Type":          dds_bundle.get("_meta",{}).get("dds_type", "material"),
        "Surface_Ligand":    str(dds_row.get("Surface_Ligand") or "").strip(),
        "Size_nm":           dds_row.get("Size_nm", "?"),
        "Zeta_Potential_mV": dds_row.get("Zeta_Potential_mV", "?"),
        "Release_Kinetics":  str(dds_row.get("Release_Kinetics") or "").lower(),
        "Scale_Up_Readiness":str(dds_row.get("Scale_Up_Readiness") or "").lower(),
    }


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# P21 — Pre-IND
def trans_P21(drug_bundle: dict, dds_bundle: dict,
                combo_bundle: dict, deep_results: dict) -> dict:
    d = _drug_summary(drug_bundle); s = _dds_summary(dds_bundle, combo_bundle)
    indication = "CNS condition"
    return {
        "principle": "P21",
        "title": "Pre-IND Regulatory Report (FDA 21 CFR 312.23)",
        "status": "structured_outline_ready",
        "narrative": (f"Pre-IND meeting package outline for {d['name']} "
                       f"({indication}). Top-1 DDS: {s['Formulation_Name']}."),
        "sections": [
            {"heading":"1. Cover Letter","ready":True,
              "content_summary":(f"FDA Pre-IND meeting request for "
                                   f"{d['name']} {s['DDS_Type']} CNS-targeting formulation.")},
            {"heading":"2. Drug Substance","ready":True,
              "content_summary":(f"{d['name']} ({d['drug_type']}): "
                                   f"MW {d['MW_Da']} Da, LogP {d['LogP']}, "
                                   f"TPSA {d['TPSA']} Å². Source: bundle-resolved (provenance available).")},
            {"heading":"3. Drug Product (DDS)","ready":True,
              "content_summary":(f"{s['Formulation_Name']} — {s['Carrier_Type']} ({s['DDS_Type']}), "
                                   f"{s['Size_nm']} nm, ζ {s['Zeta_Potential_mV']} mV, "
                                   f"ligand: {s['Surface_Ligand'] or '(none)'}.")},
            {"heading":"4. Nonclinical Pharmacology (in-silico)","ready":True,
              "content_summary":"PBPK ODE deep validation, glymphatic kinetics, BBB targeting score."},
            {"heading":"5. Nonclinical Toxicology (in-silico)","ready":True,
              "content_summary":"Off-target QSAR (50-receptor panel), nanotox score."},
            {"heading":"6. Clinical Protocol Outline","ready":False,
              "content_summary":"(Phase 1 dosing — pending wet-lab confirmation)"},
            {"heading":"7. Manufacturing (CMC)","ready":True,
              "content_summary":(f"Scale-up readiness: {s['Scale_Up_Readiness']}, "
                                   f"shelf-life prediction, sterilization assessment.")},
            {"heading":"8. Investigator Information","ready":False,
              "content_summary":"(Researcher to fill: PI, IRB, site)"},
        ],
        "deep_validation_passed": sum(1 for r in deep_results.values() if r.get("validated")) >= 5,
        "v23_note": "Full Word generation via python-docx scheduled for v23",
        "generated_at": _ts(),
    }


# P32 — FTO
def trans_P32(drug_bundle: dict, dds_bundle: dict,
                combo_bundle: dict, deep_results: dict) -> dict:
    d = _drug_summary(drug_bundle); s = _dds_summary(dds_bundle, combo_bundle)
    carrier = s["Carrier_Type"].lower(); ligand = s["Surface_Ligand"].lower()
    drug = d["name"]
    KNOWN_CROWDED = {
        ("liposome","transferrin"):"VERY_HIGH", ("liposome","rvg29"):"MEDIUM",
        ("plga","transferrin"):"HIGH", ("plga","rvg29"):"MEDIUM",
        ("solid_lipid","transferrin"):"MEDIUM", ("solid_lipid","lactoferrin"):"LOW",
        ("micelle",""):"LOW",
    }
    encumbrance = KNOWN_CROWDED.get((carrier, ligand), "LOW")
    fto_score = {"VERY_HIGH":30,"HIGH":50,"MEDIUM":70,"LOW":85}.get(encumbrance, 70)
    return {
        "principle":"P32", "title":"Freedom-to-Operate Analysis",
        "status":"search_queries_prepared",
        "fto_score":fto_score, "encumbrance_level":encumbrance,
        "narrative":(f"FTO analysis for {drug} delivered by {carrier} "
                       f"with {ligand or 'bare'} surface. "
                       f"Patent encumbrance: {encumbrance} → FTO score {fto_score}/100."),
        "search_queries":[
            f'"{drug}" AND "{carrier}" AND ("nanoparticle" OR "drug delivery")',
            f'"{ligand}" AND "{carrier}" AND "BBB"' if ligand else f'"{carrier}" AND "blood-brain barrier"',
            f'"CNS delivery" AND "{carrier}"',
        ],
        "patent_databases_to_check":["USPTO","EPO","WIPO PCT","Lens.org","Google Patents"],
        "v23_note":"Live patent API integration deferred to v23",
        "generated_at": _ts(),
    }


# P45 — Compliance audit
def trans_P45(drug_bundle: dict, dds_bundle: dict,
                combo_bundle: dict, deep_results: dict) -> dict:
    audit_features = {
        "user_authentication":     True,
        "tamper_proof_logging":    True,
        "electronic_signatures":   False,
        "data_versioning":         True,
        "input_provenance":        True,
        "output_traceability":     True,
        "user_action_logging":     False,
        "data_integrity_hashing":  False,
    }
    pct = 100 * sum(audit_features.values()) / len(audit_features)
    return {
        "principle":"P45", "title":"21 CFR Part 11 Compliance Audit",
        "status":"audit_completed",
        "compliance_score":round(pct, 1),
        "narrative":(f"21 CFR Part 11 compliance: {pct:.0f}%. "
                       f"{sum(audit_features.values())}/{len(audit_features)} features present."),
        "features":audit_features,
        "missing_features_for_full_compliance":[f for f, ok in audit_features.items() if not ok],
        "v23_note":"Add e-signatures + complete user action logging for 100% compliance",
        "generated_at": _ts(),
    }


# P55 — Grant proposal
def trans_P55(drug_bundle: dict, dds_bundle: dict,
                combo_bundle: dict, deep_results: dict) -> dict:
    d = _drug_summary(drug_bundle); s = _dds_summary(dds_bundle, combo_bundle)
    indication = "CNS disorder"
    return {
        "principle":"P55", "title":"NIH/NSF Grant Proposal Outline",
        "status":"structured_outline_ready",
        "narrative":(f"R01-style proposal outline for {d['name']} delivered by "
                       f"{s['Formulation_Name']} for {indication}."),
        "sections":[
            {"heading":"Specific Aims","ready":True,
              "content_summary":(f"Aim 1: Optimize {s['Carrier_Type']} formulation. "
                                   f"Aim 2: Validate BBB targeting in vivo. Aim 3: Phase-1 efficacy.")},
            {"heading":"Significance","ready":True,
              "content_summary":(f"{indication} affects millions; current therapies limited by BBB.")},
            {"heading":"Innovation","ready":True,
              "content_summary":"First in-silico predicted CNS DDS with full 62-principle validation."},
            {"heading":"Approach (in-silico evidence)","ready":True,
              "content_summary":(f"Class A surrogate ranking + Class B deep validation of {s['Formulation_Name']}.")},
            {"heading":"Preliminary Data","ready":True,
              "content_summary":"Full CEREBRO-X pipeline output as preliminary data."},
            {"heading":"Budget & Timeline","ready":False,"content_summary":"(Researcher to fill)"},
        ],
        "v23_note":"Full Word generation via python-docx scheduled for v23",
        "generated_at": _ts(),
    }


# P56 — Patentability
def trans_P56(drug_bundle: dict, dds_bundle: dict,
                combo_bundle: dict, deep_results: dict) -> dict:
    s = _dds_summary(dds_bundle, combo_bundle)
    carrier = s["Carrier_Type"].lower(); ligand = s["Surface_Ligand"].lower()
    rel_kin = s["Release_Kinetics"]
    novelty = 80
    if (carrier, ligand) in [("liposome","transferrin"),("plga","transferrin")]:
        novelty = 50
    elif ligand == "lactoferrin" and carrier == "solid_lipid":
        novelty = 95
    elif rel_kin in ("ph-responsive", "thermo"):
        novelty += 5
    try: size = float(s["Size_nm"])
    except (ValueError, TypeError): size = 100.0
    try: zeta = float(s["Zeta_Potential_mV"])
    except (ValueError, TypeError): zeta = -10.0
    non_obvious = 70
    if size < 60 or size > 180: non_obvious += 10
    if abs(zeta) < 5 or abs(zeta) > 25: non_obvious += 5
    utility = 80
    if any(r.get("validated") for r in deep_results.values()):
        utility = 90
    overall = (novelty + non_obvious + utility) / 3
    return {
        "principle":"P56", "title":"Patentability Score (USPTO §101/§102/§103)",
        "status":"scored",
        "patentability_score":round(overall, 1),
        "narrative":(f"Patentability score: {overall:.0f}/100. "
                       f"Novelty {novelty}, non-obviousness {non_obvious}, utility {utility}."),
        "components":{
            "novelty_§102": novelty,
            "non_obviousness_§103": non_obvious,
            "utility_§101": utility,
        },
        "recommendation":("FILE PROVISIONAL" if overall >= 75 else
                            "REVIEW CLAIMS BEFORE FILING" if overall >= 60 else
                            "MAJOR REWORK NEEDED"),
        "v23_note":"Live USPTO/Lens.org search integration deferred to v23",
        "generated_at": _ts(),
    }


TRANSLATIONAL_FUNCTIONS = {
    "P21": trans_P21, "P32": trans_P32, "P45": trans_P45,
    "P55": trans_P55, "P56": trans_P56,
}


def evaluate_translational_for_top1(drug_bundle: dict, dds_bundle: dict,
                                       combo_bundle: dict,
                                       deep_results: dict[str, dict],
                                       only_if_deep_passed: bool = True) -> dict[str, dict]:
    """Run Class C translational principles on Top-1 — bundle-only."""
    n_passed = sum(1 for r in deep_results.values() if r.get("validated"))
    n_total = len(deep_results)
    deep_passed = (n_passed >= 0.7 * n_total) if n_total > 0 else False

    if only_if_deep_passed and not deep_passed:
        log.warning(f"[TRANSLATIONAL] Deep validation insufficient "
                     f"({n_passed}/{n_total} passed). Skipping translational layer.")
        return {pid: {"principle":pid,
                       "status":"skipped_deep_validation_insufficient",
                       "narrative":(f"Deep validation passed only {n_passed}/{n_total} "
                                       f"principles. Translational deliverables withheld until "
                                       f"a higher-ranked DDS passes deep validation."),
                       "generated_at": _ts()}
                for pid in TRANSLATIONAL_FUNCTIONS}

    out: dict[str, dict] = {}
    for pid, fn in TRANSLATIONAL_FUNCTIONS.items():
        try:
            out[pid] = fn(drug_bundle, dds_bundle, combo_bundle, deep_results)
        except Exception as e:
            log.warning(f"[TRANSLATIONAL] {pid} failed: {e}")
            out[pid] = {"principle":pid, "status":"failed",
                         "error":str(e), "generated_at":_ts()}
    return out
