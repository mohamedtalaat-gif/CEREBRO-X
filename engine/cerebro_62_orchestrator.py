# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  cerebro_62_orchestrator.py
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X

The C+ Flow orchestrator:
  1. Class A surrogate → ALL DDS → ranking
  2. Class B deep physics → Top-1 (with fallback to Top-2 on failure)
  3. Class C translational → Top-1 (only if Class B passes)

Replaces the v21 25-principle evaluator.

Output structure (returned to run.py):
  {
      "ranked_df":           pd.DataFrame with all DDS scored + ranked,
      "all_dds_principles":  list of dicts, one per DDS, with all 57 scores,
      "all_dds_breakdown":   list of dicts, one per DDS, with reasoning,
      "top1_dds_name":       str,
      "top1_index_in_ranked": int,
      "deep_results":        dict of P# → deep validation,
      "deep_summary":        {"passed", "pct", "verdict", ...},
      "translational":       dict of P# → translational deliverable,
      "principle_weights":   dict of P# → CNS-focused weight,
      "fallback_chain":      list of dicts (which DDS were tried, and why),
  }
================================================================================
"""
from __future__ import annotations
import logging, math
from typing import Dict, List, Tuple, Any, Optional

log = logging.getLogger("CEREBRO-62-ORCHESTRATOR")


# ──────────────────────────────────────────────────────────────────────────
# Composite scoring with CNS-focused weights from the catalog
# ──────────────────────────────────────────────────────────────────────────
def _compute_composite_score(per_principle: Dict[str, Dict],
                              weights: Dict[str, float]) -> float:
    """Weighted average of all principle scores. Weights from catalog."""
    total_w = 0.0
    total_score = 0.0
    for pid, pdata in per_principle.items():
        w = weights.get(pid, 0.0)
        if w > 0:
            total_score += pdata["score"] * w
            total_w += w
    return total_score / total_w if total_w > 0 else 0.0


def _verdict_for(score: float) -> str:
    if score >= 80: return "EXCELLENT"
    if score >= 65: return "GOOD"
    if score >= 50: return "ACCEPTABLE"
    if score >= 35: return "MARGINAL"
    return "POOR"


def _drug_dds_compatibility_multiplier(drug_type: str,
                                          carrier_type: str) -> Tuple[float, str]:
    """Phase 5 (2026-04-30): pathway-aware composite multiplier.

    Different drug modalities need fundamentally different DDS architectures.
    A monoclonal antibody (~150 kDa, hydrophilic) cannot diffuse into a PLGA
    matrix, no matter how good the surface ligand is. An siRNA needs ionizable
    lipid endosomal escape, not a passive polymer carrier.

    This function returns a multiplier ∈ [0.4, 1.20] applied to the composite
    score AFTER all 57 surrogate principles vote. It encodes the FDA-
    documented compatibility logic that the surrogate engine alone cannot
    capture from physicochemical metrics.

    Returns (multiplier, reason):
      • 1.20 — IDEAL pairing (e.g. AAV9 for gene therapy, LNP for siRNA)
      • 1.00 — NEUTRAL (small molecule + most carriers)
      • 0.80 — SUBOPTIMAL (mAb + PLGA — works but loses payload activity)
      • 0.60 — POOR (oligonucleotide + bare polymer micelle, no escape)
      • 0.40 — INCOMPATIBLE (siRNA + non-ionizable lipid)

    Reference logic:
      - mAbs/proteins: best in PEG-Liposome (long circulation), Nanocrystal,
                          AAV (for gene-encoded biologics)
      - Oligonucleotides (siRNA/ASO): require LNP (ionizable lipid + endosomal
                          escape), or AAV-encoded gene therapy
      - Gene therapy (DNA/RNA): AAV9 = gold standard CNS delivery
      - Small molecules: most carriers viable; carrier choice driven by
                          release kinetics + targeting
    """
    if not drug_type or not carrier_type:
        return 1.0, "no_class_data"
    dt = (drug_type or "").lower().strip()
    ct = (carrier_type or "").lower().strip()

    # Map raw types to broad categories
    is_biologic = any(s in dt for s in [
        "monoclonal_antibody", "mab", "antibody", "biologic",
        "fusion_protein", "blood_product", "enzyme", "peptide_hormone",
        "protein",  # the bundle resolver categorizes mAbs/proteins as "protein"
    ])
    is_protein = is_biologic or "peptide" in dt
    is_oligo = any(s in dt for s in [
        "oligonucleotide", "siRNA", "aso", "antisense", "miRNA",
    ])
    is_gene = any(s in dt for s in [
        "gene_therapy", "gene_dna", "gene_rna", "mrna", "saRNA", "vaccine_mrna",
    ]) or is_oligo
    is_small = "small_molecule" in dt or dt == "small"

    # Carrier categories
    is_lnp        = ct in ("lnp", "ionizable_lipid_np", "ionizable_lnp")
    is_aav        = ct in ("aav9", "aav", "aav2", "aav5", "aav-rh10",
                              "viral_envelope", "lentivirus")
    is_liposome   = ct == "liposome"
    is_solid_lipid= ct in ("solid_lipid", "sln", "nlc")
    is_plga       = ct in ("plga", "polymer", "plg")
    is_micelle    = ct == "micelle"
    is_dendrimer  = ct == "dendrimer"
    is_metallic   = ct in ("metallic", "gold", "iron_oxide", "spion")

    # ─── DECISION MATRIX ────────────────────────────────────────────────
    # 1.20 — IDEAL pairings
    if is_gene and is_lnp:           return 1.20, "ideal: LNP→gene-therapy (FDA-validated for siRNA Patisiran, mRNA vaccines)"
    if is_gene and is_aav:           return 1.20, "ideal: AAV→gene-therapy (Zolgensma; CNS gold standard)"
    if is_oligo and is_lnp:          return 1.20, "ideal: LNP→oligonucleotide (ionizable lipid, endosomal escape)"
    if is_biologic and is_aav:       return 1.18, "ideal: AAV→biologic (gene-encoded antibody platforms)"
    if is_biologic and is_liposome:  return 1.10, "good: PEG-liposome→biologic (long circulation, low immunogenicity)"
    if is_small and is_plga:         return 1.05, "good: PLGA→small-mol (FDA-approved sustained release)"
    if is_small and is_solid_lipid:  return 1.05, "good: SLN→small-mol (lipophilic loading, BBB transit)"
    if is_small and is_liposome:     return 1.05, "good: liposome→small-mol (versatile, FDA-validated)"

    # 1.00 — NEUTRAL (functional but not optimal)
    if is_small and (is_micelle or is_dendrimer or is_lnp or is_metallic):
        return 1.00, "neutral: carrier supports small-molecule delivery"

    # 0.80 — SUBOPTIMAL (works, loses some efficacy)
    if is_biologic and (is_solid_lipid or is_micelle):
        return 0.80, "suboptimal: biologic in lipid matrix (loading + stability concerns)"
    if is_biologic and is_plga:
        return 0.75, "suboptimal: PLGA→biologic (organic-solvent denaturation; acidic degradation)"
    if is_oligo and is_liposome:
        return 0.85, "suboptimal: liposome→oligo (no endosomal escape vs LNP)"

    # 0.60 — POOR
    if is_oligo and (is_plga or is_solid_lipid or is_micelle):
        return 0.60, "poor: passive polymer/lipid carrier lacks endosomal escape for oligos"
    if is_biologic and is_dendrimer:
        return 0.65, "poor: dendrimer→biologic (size mismatch, surface displacement)"
    if is_protein and is_metallic:
        return 0.55, "poor: metallic NP→protein (corona-driven aggregation)"

    # 0.40 — INCOMPATIBLE (rare; explicit mismatches)
    if is_oligo and is_metallic:
        return 0.45, "incompatible: metallic surface destabilizes oligo backbone"

    # Default: 0.95 (slight skepticism for unmapped pairs)
    return 0.95, "default: pairing not in FDA-validated table — surrogate score retained"


def _group_score(per_principle: Dict[str, Dict], pids: List[str]) -> float:
    """Average score across a list of principle IDs (skipping missing)."""
    vals = [per_principle[p]["score"] for p in pids if p in per_principle]
    return sum(vals)/len(vals) if vals else 0.0


# CNS-focused principle groups for rollup display
PRINCIPLE_GROUPS = {
    "G1_CNS_Delivery":      ["P12","P13","P18","P31","P33","P38","P42","P44"],
    "G2_Release_Kinetics":  ["P10","P14","P30","P59"],
    "G3_Stability":         ["P01","P08","P11","P15","P50","P51"],
    "G4_Safety":            ["P09","P17","P22","P39","P46","P48","P53"],
    "G5_Glymphatic_BBB":    ["P38","P40","P43"],
    "G6_Manufacturability": ["P16","P19","P20","P24","P25","P27","P28",
                              "P52","P57"],
    "G7_DrugDDS_Fit":       ["P03","P04","P05","P23","P25","P29","P34",
                              "P35","P36","P37","P41","P49","P58","P60","P61","P62"],
    "G8_Translational":     ["P21","P32","P45","P55","P56"],
}


# ──────────────────────────────────────────────────────────────────────────
# Main entry point — replaces evaluate_all_dds in v21
# ──────────────────────────────────────────────────────────────────────────
def evaluate_all_dds_62(drug_bundle: Dict, df_dds, drug_name: str = "",
                          context: Optional[Dict] = None) -> Dict:
    """The full C+ Flow on a single drug's DDS list — BUNDLE-ONLY.

    Phase 5 refactor (2026-04-30):
      - Accepts a pre-resolved drug_bundle (from cerebro_resolved_bundles)
      - Builds dds_bundle + combo_bundle for each formulation row
      - Passes bundles directly to surrogate + deep + translational engines
      - No mol_profile dict anywhere in the call chain

    Args:
      drug_bundle: output of resolve_drug_bundle() with full 65-category
                     resolution and provenance
      df_dds: pandas DataFrame of formulations from Excel input
      drug_name: drug name for logging (also extractable from drug_bundle._meta.name)
      context: optional context (disease_stage, etc.)

    Returns dict (same shape as before for downstream report compatibility):
      ranked_df, all_dds_principles, all_dds_breakdown,
      top1_dds_name, deep_results, deep_summary,
      translational, principle_weights, fallback_chain,
      drug_bundle (for report-level provenance)
    """
    import pandas as pd
    from cerebro_62_surrogate_engine     import evaluate_all_principles_for_dds, SURROGATE_FUNCTIONS
    from cerebro_62_deep_engine          import evaluate_deep_for_top1, overall_deep_validation
    from cerebro_62_translational_engine import evaluate_translational_for_top1
    from cerebro_62_principles_catalog   import PRINCIPLES_62
    from cerebro_resolved_bundles        import resolve_dds_bundle, resolve_combo_bundle, cache_stats

    if df_dds is None or len(df_dds) == 0:
        log.warning(f"[62-ORCH] {drug_name}: empty df_dds")
        return {"ranked_df": df_dds, "all_dds_principles": [],
                "all_dds_breakdown": [], "top1_dds_name": None,
                "deep_results": {}, "deep_summary": {"passed":False,"verdict":"NO DATA"},
                "translational": {}, "principle_weights": {}, "fallback_chain": [],
                "drug_bundle": drug_bundle}

    drug_name = drug_name or drug_bundle.get("_meta",{}).get("name","drug")
    log.info(f"[62-ORCH] {drug_name}: starting Class A surrogate "
              f"on {len(df_dds)} DDS × {len(SURROGATE_FUNCTIONS)} principles "
              f"(bundle-driven; drug_type={drug_bundle.get('_meta',{}).get('drug_type','?')})")

    df = df_dds.copy().reset_index(drop=True)

    # CNS weights from catalog
    weights = {pid: p["weight_cns"] for pid, p in PRINCIPLES_62.items()
                if p["class"] in ("A_surrogate", "B_deep")}

    # ─── Pre-resolve all DDS bundles + combo bundles (cache-friendly) ──
    dds_bundles: List[Dict] = []
    combo_bundles: List[Dict] = []
    for idx in range(len(df)):
        dds_row = df.iloc[idx].to_dict()
        carrier = str(dds_row.get("Carrier_Type", "") or
                        dds_row.get("carrier_type", "")).strip()
        ligand  = str(dds_row.get("Surface_Ligand", "") or "").strip()
        formul_id = str(dds_row.get("Formulation_ID", "") or
                          dds_row.get("formulation_id", f"DDS_{idx+1}"))
        formul_name = str(dds_row.get("Formulation_Name", "") or formul_id)
        ds_b = resolve_dds_bundle(
            carrier_type=carrier, ligand=ligand,
            formulation_id=formul_id, formulation_name=formul_name)
        co_b = resolve_combo_bundle(drug_bundle, ds_b)
        # Critical: surrogate + deep functions use combo._meta.dds_row
        # to read formulation-specific user inputs (Size_nm, Zeta, etc.)
        co_b["_meta"]["dds_row"] = dds_row
        dds_bundles.append(ds_b)
        combo_bundles.append(co_b)
    log.info(f"[62-ORCH] {drug_name}: bundles resolved | cache stats: "
              f"{cache_stats()}")

    # ─── PHASE 1: Class A surrogate on every DDS ────────────────────
    all_principles: List[Dict] = []
    all_breakdowns: List[Dict] = []
    composites: List[float] = []
    group_rollups_per_row: Dict[str, List[float]] = {g: [] for g in PRINCIPLE_GROUPS}

    # Drug type for compatibility multiplier
    drug_type_meta = drug_bundle.get("_meta", {}).get("drug_type", "small_molecule")

    for idx in range(len(df)):
        dds_row = df.iloc[idx].to_dict()
        ds_b = dds_bundles[idx]
        co_b = combo_bundles[idx]
        per_principle = evaluate_all_principles_for_dds(drug_bundle, ds_b, co_b)
        composite_raw = _compute_composite_score(per_principle, weights)

        # Apply drug-DDS pathway compatibility multiplier
        carrier_type = str(dds_row.get("Carrier_Type", "")
                              or dds_row.get("carrier_type", ""))
        compat_mult, compat_reason = _drug_dds_compatibility_multiplier(
            drug_type_meta, carrier_type)
        composite = min(100.0, composite_raw * compat_mult)
        composites.append(round(composite, 2))

        # Group rollups
        groups = {}
        for g, pids in PRINCIPLE_GROUPS.items():
            avg = _group_score(per_principle, pids)
            groups[g] = round(avg, 2)
            group_rollups_per_row[g].append(round(avg, 2))

        # Ranked principles for this DDS
        ranked_p = sorted(per_principle.items(),
                           key=lambda kv: kv[1]["score"], reverse=True)
        top3 = ranked_p[:3]
        bot3 = [(p,d) for p,d in ranked_p[-5:] if d["score"] < 60][:3]

        verdict = _verdict_for(composite)
        breakdown = {
            "dds_index": idx,
            "dds_name":  str(dds_row.get("Formulation_Name") or
                              dds_row.get("Formulation_ID") or f"DDS_{idx+1}"),
            "composite":     round(composite, 2),
            "composite_raw": round(composite_raw, 2),
            "compat_multiplier": round(compat_mult, 3),
            "compat_reason":  compat_reason,
            "verdict":   verdict,
            "group_scores": groups,
            "top_strengths": [
                {"principle": pid, "score": pd["score"],
                  "method":    pd.get("method",""),
                  "reference": pd.get("reference","")}
                for pid, pd in top3
            ],
            "weak_spots": [
                {"principle": pid, "score": pd["score"],
                  "method":    pd.get("method",""),
                  "reference": pd.get("reference",""),
                  "improvement_hint":
                      f"Below 60. Method: {pd.get('method','')[:80]}"}
                for pid, pd in bot3
            ],
            "narrative": _build_narrative(dds_row, per_principle, groups,
                                            composite, verdict),
        }
        all_breakdowns.append(breakdown)
        all_principles.append({
            "dds_index":  idx,
            "dds_name":   breakdown["dds_name"],
            "composite":  round(composite, 2),
            "principles": per_principle,
            "groups":     groups,
        })

    # Add columns to ranked DataFrame
    df["Principle_Composite_Score"] = composites
    for g, vals in group_rollups_per_row.items():
        df[g + "_Score"] = vals

    # Add compatibility multiplier columns BEFORE sorting (so they sort with rows)
    df["Compat_Multiplier"]      = [b["compat_multiplier"] for b in all_breakdowns]
    df["Compat_Reason"]          = [b["compat_reason"]     for b in all_breakdowns]
    df["Composite_Score_Raw"]    = [b["composite_raw"]     for b in all_breakdowns]
    df["Verdict"]                = [b["verdict"]            for b in all_breakdowns]

    df = df.sort_values("Principle_Composite_Score",
                          ascending=False).reset_index(drop=True)
    df["Principle_Rank"] = range(1, len(df) + 1)

    # Re-order breakdowns/matrix to match ranking
    sorted_breakdowns = sorted(all_breakdowns, key=lambda b: b["composite"],
                                 reverse=True)
    sorted_principles = sorted(all_principles, key=lambda p: p["composite"],
                                 reverse=True)
    # Map old idx → new sorted position so we can pick the right bundles
    sorted_idx_to_old: List[int] = [b["dds_index"] for b in sorted_breakdowns]

    # Phase 5 (2026-04-30): inject provenance summary columns into the
    # ranked DataFrame so downstream consumers (PDF/Excel/HTML5 writers)
    # can show every cell's tier + source without re-querying bundles.
    # Drug-side: SAME across all rows (single drug per ranking)
    drug_type = drug_bundle.get("_meta",{}).get("drug_type", "?")
    df["_prov_drug_type"] = drug_type
    df["_prov_drug_name"] = drug_bundle.get("_meta",{}).get("name", drug_name)
    # DDS-side: per-row tier + source for the top-6 material categories
    _prov_cats = [
        ("dds_type", "_prov_dds_type"),
        ("material_polymer_tg", "_prov_polymer_tg"),
        ("material_polymer_hydrolysis_ea", "_prov_hydrolysis"),
        ("material_lipid_tm", "_prov_lipid_tm"),
        ("material_zeta_intrinsic", "_prov_zeta"),
        ("material_pdi", "_prov_pdi"),
    ]
    for bundle_key, col_prefix in _prov_cats:
        tiers   = []
        sources = []
        for new_pos in range(len(df)):
            old_idx = sorted_idx_to_old[new_pos]
            ds_b    = dds_bundles[old_idx]
            rec     = ds_b.get(bundle_key, {}) if isinstance(ds_b, dict) else {}
            tiers.append(rec.get("tier"))
            sources.append(rec.get("source", ""))
        df[f"{col_prefix}_tier"]   = tiers
        df[f"{col_prefix}_source"] = sources

    log.info(f"[62-ORCH] {drug_name}: surrogate complete. "
              f"Top-1: {sorted_breakdowns[0]['dds_name']} "
              f"(composite={sorted_breakdowns[0]['composite']:.1f}/100, "
              f"{sorted_breakdowns[0]['verdict']})")


    # ─── PHASE 2: Class B deep physics on Top-1 (with fallback) ─────
    fallback_chain: List[Dict] = []
    deep_results: Dict[str, Dict] = {}
    deep_summary: Dict[str, Any] = {"passed": False, "verdict": "NOT RUN"}
    top1_used_idx = 0

    n_to_try = min(3, len(sorted_breakdowns))
    for try_idx in range(n_to_try):
        candidate = sorted_breakdowns[try_idx]
        old_idx = sorted_idx_to_old[try_idx]
        candidate_dds_bundle  = dds_bundles[old_idx]
        candidate_combo_bundle = combo_bundles[old_idx]
        candidate_surrogate = sorted_principles[try_idx]["principles"]
        log.info(f"[62-ORCH] {drug_name}: deep validation try #{try_idx+1} "
                  f"on {candidate['dds_name']}")

        deep = evaluate_deep_for_top1(drug_bundle, candidate_dds_bundle,
                                         candidate_combo_bundle, candidate_surrogate)
        summary = overall_deep_validation(deep)

        # Build detailed failure-reason list
        failed_principles = [
            {
                "principle":     pid,
                "deep_score":    r.get("score", 0),
                "deep_value":    r.get("value", ""),
                "method":        (r.get("method", "") or "")[:120],
                "narrative":     (r.get("narrative", "") or "")[:200],
                "confidence":    r.get("confidence", "—"),
            }
            for pid, r in sorted(deep.items()) if not r.get("validated")
        ]
        passed_principles = [
            {
                "principle":  pid,
                "deep_score": r.get("score", 0),
                "deep_value": r.get("value", ""),
            }
            for pid, r in sorted(deep.items()) if r.get("validated")
        ]

        # Compose human-readable transition reason
        if summary["passed"]:
            failure_reason = "—"
            transition_reason = (
                f"Deep validation PASSED on this DDS "
                f"({summary['passed_count']}/{summary['total']} principles "
                f"validated, {summary['pct']}% — threshold is 70%). "
                f"This DDS is the final Top-1.")
        elif summary["verdict"] == "MARGINAL":
            top_failures = ", ".join(p["principle"] for p in failed_principles[:5])
            failure_reason = (
                f"Deep validation MARGINAL: only "
                f"{summary['passed_count']}/{summary['total']} principles "
                f"validated ({summary['pct']}%, threshold 70%). "
                f"Failed principles include: {top_failures}.")
            if try_idx + 1 < n_to_try:
                transition_reason = (
                    f"Falling back to rank #{try_idx+2} because this DDS did "
                    f"not meet the 70% deep-validation threshold.")
            else:
                transition_reason = (
                    f"No more candidates in Top-3 — reverting to rank #1 "
                    f"and reporting with MARGINAL verdict.")
        else:   # FAILED
            top_failures = ", ".join(p["principle"] for p in failed_principles[:5])
            failure_reason = (
                f"Deep validation FAILED: only "
                f"{summary['passed_count']}/{summary['total']} principles "
                f"validated ({summary['pct']}%, threshold 70%). "
                f"Critical failures: {top_failures}.")
            if try_idx + 1 < n_to_try:
                transition_reason = (
                    f"Falling back to rank #{try_idx+2} because deep physics "
                    f"showed insufficient evidence for this DDS.")
            else:
                transition_reason = (
                    f"No more candidates in Top-3 — reverting to rank #1 "
                    f"and reporting with FAILED verdict. "
                    f"Researcher should reformulate.")

        fallback_chain.append({
            "rank":              try_idx + 1,
            "dds_name":          candidate["dds_name"],
            "surrogate_score":   candidate["composite"],
            "deep_passed_pct":   summary["pct"],
            "deep_passed_count": summary["passed_count"],
            "deep_total":        summary["total"],
            "verdict":           summary["verdict"],
            "promoted":          summary["passed"],
            "failure_reason":    failure_reason,
            "transition_reason": transition_reason,
            "failed_principles": failed_principles,
            "passed_principles": passed_principles,
        })

        if summary["passed"]:
            deep_results = deep
            deep_summary = summary
            top1_used_idx = try_idx
            log.info(f"[62-ORCH] {drug_name}: deep PASSED on rank #{try_idx+1} "
                      f"({summary['pct']}% principles validated)")
            break
        else:
            log.warning(f"[62-ORCH] {drug_name}: rank #{try_idx+1} "
                         f"failed deep ({summary['pct']}%, "
                         f"{summary['verdict']}). "
                         f"{transition_reason}")
    else:
        # No DDS passed deep validation in top-3; report Top-1 anyway
        log.warning(f"[62-ORCH] {drug_name}: NO DDS passed deep validation. "
                     f"Reporting Top-1 with FAILED verdict.")
        old_idx = sorted_idx_to_old[0]
        deep_results = evaluate_deep_for_top1(
            drug_bundle, dds_bundles[old_idx], combo_bundles[old_idx],
            sorted_principles[0]["principles"])
        deep_summary = overall_deep_validation(deep_results)

    # ─── PHASE 3: Class C translational on validated Top-1 ──────────
    final_top1_idx = top1_used_idx
    final_old_idx = sorted_idx_to_old[final_top1_idx]
    log.info(f"[62-ORCH] {drug_name}: translational layer for "
              f"{sorted_breakdowns[final_top1_idx]['dds_name']}")
    translational = evaluate_translational_for_top1(
        drug_bundle, dds_bundles[final_old_idx], combo_bundles[final_old_idx],
        deep_results, only_if_deep_passed=True)

    return {
        "ranked_df":              df,
        "all_dds_principles":     sorted_principles,
        "all_dds_breakdown":      sorted_breakdowns,
        "top1_dds_name":          sorted_breakdowns[final_top1_idx]["dds_name"],
        "top1_index_in_ranked":   final_top1_idx,
        "deep_results":           deep_results,
        "deep_summary":           deep_summary,
        "translational":          translational,
        "principle_weights":      weights,
        "fallback_chain":         fallback_chain,
        "drug_bundle":            drug_bundle,
        "dds_bundles":            dds_bundles,
        "combo_bundles":          combo_bundles,
    }


# ──────────────────────────────────────────────────────────────────────────
# Narrative builder
# ──────────────────────────────────────────────────────────────────────────
def _build_narrative(dds: Dict, per_principle: Dict,
                       groups: Dict, composite: float, verdict: str) -> str:
    name = str(dds.get("Formulation_Name") or
                dds.get("Formulation_ID") or "this DDS")
    carrier = str(dds.get("Carrier_Type", "unknown")).lower()
    size = float(dds.get("Size_nm", 0) or 0)
    zeta = float(dds.get("Zeta_Potential_mV", 0) or 0)
    ligand = str(dds.get("Surface_Ligand", "(none)")).strip() or "(none)"
    best_group = max(groups.items(), key=lambda kv: kv[1])
    worst_group = min(groups.items(), key=lambda kv: kv[1])
    return (f"{name}: composite CNS-principle score = {composite:.1f}/100 "
            f"({verdict}). Carrier: {carrier}, size {size} nm, ζ {zeta:+.1f} mV, "
            f"ligand: {ligand}. Strongest group: "
            f"{best_group[0].replace('_',' ')} ({best_group[1]:.1f}/100); "
            f"weakest: {worst_group[0].replace('_',' ')} ({worst_group[1]:.1f}/100). "
            f"Evaluated against all 57 Class A surrogate principles.")
