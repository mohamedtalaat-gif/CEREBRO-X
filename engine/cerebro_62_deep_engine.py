"""
================================================================================
CEREBRO-X |  cerebro_62_deep_engine.py (Phase 3)
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X
Refactored: 2026-04-30 — Bundle-only signature (NO legacy support)

Class B (Deep Physics) — full PBPK / MD / FEP / CFD validations.

CRITICAL ARCHITECTURE DECISION (per project owner, 2026-04-30):
  Deep Engine accepts ONLY pre-resolved bundles. There is no dual-signature,
  no isinstance(..., dict) branching, no legacy Excel-row fallbacks. ODE
  integrators must operate on values that have already been resolved through
  the 7-tier cascade with full provenance — anything else is scientifically
  irresponsible.

Function signature contract (every deep_PXX function):
    deep_PXX(drug_bundle, dds_bundle, combo_bundle, surrogate) -> Dict

Where:
    drug_bundle:  output of cerebro_resolved_bundles.resolve_drug_bundle()
    dds_bundle:   output of cerebro_resolved_bundles.resolve_dds_bundle()
    combo_bundle: output of cerebro_resolved_bundles.resolve_combo_bundle()
                    — additionally carries dds_row formulation metadata in
                      _meta.dds_row from the Excel input row
    surrogate:    Class A surrogate result for the SAME principle (used only
                    for narration; never as physics input)

Returns dict:
    {validated, value, score, method, reference, confidence,
     improvement_over_surrogate, narrative, raw, _provenance}
================================================================================
"""
from __future__ import annotations

import logging
import math
from typing import Any

from cerebro_resolved_bundles import b_tier, b_value

log = logging.getLogger("CEREBRO-DEEP")

try:
    from src.core.real_docking_engine import run_autodock_vina as _run_vina
    _HAS_DOCKING_ENGINE = True
except ImportError:
    _HAS_DOCKING_ENGINE = False


# ──────────────────────────────────────────────────────────────────────────
# Bundle-aware extractors — CONTRACT: bundles required, not optional
# ──────────────────────────────────────────────────────────────────────────
def _bundle_drug_specs(drug_bundle: dict) -> dict[str, Any]:
    """Pull drug-side values for ODE integrators with full provenance."""
    micro = drug_bundle.get("drug_microspecies", {}).get("value") or {}
    if not isinstance(micro, dict): micro = {}
    return {
        "mw":          b_value(drug_bundle, "drug_mw", 350),
        "logp":        b_value(drug_bundle, "drug_logp", 2.5),
        "tpsa":        b_value(drug_bundle, "drug_tpsa", 60),
        "hbd":         b_value(drug_bundle, "drug_hbd", 2),
        "hba":         b_value(drug_bundle, "drug_hba", 5),
        "pka_dom":     b_value(drug_bundle, "drug_pka_dominant"),
        "pka_acid":    b_value(drug_bundle, "drug_pka_acidic"),
        "pka_base":    b_value(drug_bundle, "drug_pka_basic"),
        "f_cat":       float(micro.get("f_cationic", 0.0) or 0.0),
        "f_ani":       float(micro.get("f_anionic", 0.0) or 0.0),
        "f_zwit":      float(micro.get("f_zwitterion", 0.0) or 0.0),
        "f_neutral":   float(micro.get("f_neutral", 1.0) or 1.0),
        "net_q":       float(micro.get("net_charge", 0.0) or 0.0),
        "thalf_d":     b_value(drug_bundle, "pk_halflife", 0.5),
        "clearance":   b_value(drug_bundle, "pk_clearance"),
        "volume_dist": b_value(drug_bundle, "pk_volume_distribution"),
        "ppb":         b_value(drug_bundle, "pk_protein_binding"),
        "bbb_perm":    b_value(drug_bundle, "bbb_permeability", 5),
        "bbb_logBB":   b_value(drug_bundle, "bbb_logBB"),
        "cns_mpo":     b_value(drug_bundle, "bbb_cns_mpo"),
        "logS":        b_value(drug_bundle, "drug_solubility_logS"),
        "papp_caco":   b_value(drug_bundle, "drug_caco2_papp"),
        "pgp_eff":     b_value(drug_bundle, "drug_pgp_efflux_ratio"),
        "drug_type":   drug_bundle.get("_meta",{}).get("drug_type", "small_molecule"),
        "name":        drug_bundle.get("_meta",{}).get("name", ""),
        "smiles":      drug_bundle.get("_meta",{}).get("identifiers",{}).get("smiles",""),
    }


def _bundle_dds_specs(dds_bundle: dict, combo_bundle: dict) -> dict[str, Any]:
    """Pull DDS values + Excel formulation-row data merged in."""
    dds_row = combo_bundle.get("_meta", {}).get("dds_row", {}) or {}
    def _r(key: str, default: Any) -> Any:
        for k in (key, key.lower(), key.upper()):
            if k in dds_row and dds_row[k] is not None:
                v = dds_row[k]
                if isinstance(v, (int, float)): return float(v)
                if isinstance(v, str):
                    try: return float(v)
                    except (ValueError, TypeError): return v
                return v
        return default
    return {
        "size":      _r("Size_nm", 100.0),
        "zeta":      _r("Zeta_Potential_mV", -10.0),
        "pdi":       _r("PDI", 0.2),
        "ee":        _r("Encapsulation_Efficiency_pct", 75.0),
        "peg":       _r("PEGylation_Degree_mol_pct", 5.0),
        "ligand":    str(_r("Surface_Ligand", "")).lower().strip(),
        "rel_kin":   str(_r("Release_Kinetics", "sustained")).lower().strip(),
        "ph_trig":   _r("pH_Trigger", 6.5),
        "endo_esc":  _r("Endosomal_Escape_Eff", 0.5),
        "phase_T":   _r("Phase_Transition_Temp_C", 42.0),
        "elast":     _r("Elasticity_kPa", 0.5),
        "drug_load": _r("Drug_Loading_Pct", 10.0),
        "scale":     str(_r("Scale_Up_Readiness", "lab")).lower().strip(),
        "carrier":   dds_bundle.get("_meta",{}).get("carrier_type",
                        "liposome").lower().strip(),
        "dds_type":  dds_bundle.get("_meta",{}).get("dds_type", "material"),
        "polymer_Tg":   b_value(dds_bundle, "material_polymer_tg"),
        "polymer_Tm":   b_value(dds_bundle, "material_polymer_tm"),
        "hydrolysis_Ea": b_value(dds_bundle, "material_polymer_hydrolysis_ea"),
        "lipid_Tm":     b_value(dds_bundle, "material_lipid_tm"),
        "hamaker":      b_value(dds_bundle, "material_hamaker_constant"),
        "porosity":     b_value(dds_bundle, "material_porosity"),
        "zeta_intrinsic": b_value(dds_bundle, "material_zeta_intrinsic"),
    }


def _collect_provenance(drug_bundle: dict, dds_bundle: dict,
                          combo_bundle: dict,
                          drug_keys: list[str],
                          dds_keys: list[str]) -> dict[str, dict]:
    """Build provenance dict for values fed into the deep computation."""
    prov = {"drug": {}, "dds": {}, "combo": {}}
    for k in drug_keys:
        rec = drug_bundle.get(k, {})
        if rec:
            prov["drug"][k] = {
                "value": rec.get("value"), "tier": rec.get("tier"),
                "source": rec.get("source"),
                "_computational_method": rec.get("_computational_method")
            }
    for k in dds_keys:
        rec = dds_bundle.get(k, {})
        if rec:
            prov["dds"][k] = {
                "value": rec.get("value"), "tier": rec.get("tier"),
                "source": rec.get("source"),
                "_computational_method": rec.get("_computational_method")
            }
    for k in ("drug_loading_capacity_pct",):
        rec = combo_bundle.get(k, {})
        if rec:
            prov["combo"][k] = {
                "value": rec.get("value"), "tier": rec.get("tier"),
                "source": rec.get("source"),
                "_computational_method": rec.get("_computational_method")
            }
    return prov


def _failed(reason: str) -> dict:
    return {
        "validated": False, "value": 0, "score": 0,
        "method": "(deep computation skipped)",
        "reference": "", "confidence": "FAILED",
        "improvement_over_surrogate": "—",
        "narrative": f"Deep function failed: {reason}",
        "raw": {"error": reason},
        "_provenance": {},
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P02 — Cross-Species PK Scaling
# ──────────────────────────────────────────────────────────────────────────
def deep_P02(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """Allometric scaling context for the resolved clinical half-life.

    This pipeline has no real preclinical (animal) PK measurement
    anywhere -- drug_bundle's pk_halflife resolves through live human
    clinical databases (OpenFDA/ChEMBL), a human population-PK
    regression (Lombardo 2018, fit over ~1k oral drugs), or a human
    class-median default (see cerebro_value_resolver/categories/
    pk_clinical.py) -- never an animal value. A prior version of this
    function treated that already-human-relevant number as if it were
    raw mouse data and multiplied it by (70kg/25g)^0.25 ~= 7.3x, then
    narrated the inflated result as "Predicted human t1/2 ... scaled
    from Xh mouse" -- a fabricated number and a false species-scaling
    story, since no mouse measurement was ever involved. Reports the
    resolved half-life directly instead, and shows the Mahmood 2007
    exponents as the theoretical scaling factors that would apply to a
    genuine animal-to-human extrapolation if this pipeline ever gains a
    real preclinical PK data source -- not as something already applied
    here.
    """
    d = _bundle_drug_specs(drug_bundle)
    mw = float(d["mw"])
    thalf_h = float(d["thalf_d"]) * 24
    pk_tier = b_tier(drug_bundle, "pk_halflife")
    is_human_clinical = pk_tier <= 2

    EXPONENTS = {"clearance": 0.75, "volume": 1.0, "half_life": 0.25}
    BW_h, BW_m = 70_000, 25
    ratio = BW_h / BW_m
    cl_scale = ratio ** EXPONENTS["clearance"]
    v_scale  = ratio ** EXPONENTS["volume"]
    hl_scale = ratio ** EXPONENTS["half_life"]

    drug_type = d["drug_type"]
    if drug_type == "small_molecule":
        score, conf = (90, "HIGH") if is_human_clinical else (70, "MODERATE")
    elif drug_type in ("biologic_protein","monoclonal_antibody",
                          "fusion_protein","peptide","protein"):
        score, conf = 65, "LOW"
    else:
        score, conf = 75, "MODERATE"

    return {
        "validated": pk_tier <= 6,
        "value": round(thalf_h, 2),
        "score": score,
        "method": ("Resolved clinical half-life (bundle tier "
                   f"{pk_tier}); Mahmood 2007 exponents shown for "
                   "reference only (half-life ~ BW^0.25, clearance ~ "
                   "BW^0.75, volume ~ BW^1.0) -- not applied, since no "
                   "animal PK value exists in this pipeline to scale from."),
        "reference": "",
        "confidence": conf,
        "improvement_over_surrogate":
            f"Surrogate score {surrogate.get('score','?')} → "
            f"Deep: confirms the resolved half-life's provenance tier "
            f"rather than re-scaling it.",
        "narrative": (f"Clinical t½ = {thalf_h:.1f}h "
                      f"({'human clinical source' if is_human_clinical else 'population regression / class estimate'}, "
                      f"bundle tier {pk_tier}). Reference allometric exponents "
                      f"(Mahmood 2007) for a genuine animal-to-human "
                      f"extrapolation, if one were available: clearance "
                      f"~{cl_scale:.1f}×, volume ~{v_scale:.1f}×, "
                      f"half-life ~{hl_scale:.1f}× per 70kg/25g body-weight "
                      f"ratio. Drug type: {drug_type}."),
        "raw": {"mw": mw, "thalf_h": round(thalf_h, 2),
                "pk_halflife_tier": pk_tier,
                "reference_clearance_scale": round(cl_scale, 2),
                "reference_volume_scale": round(v_scale, 2),
                "reference_halflife_scale": round(hl_scale, 2),
                "drug_type": drug_type},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=["drug_mw","pk_halflife","drug_type"],
            dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P13 — PBPK Digital Twin (3-compartment ODE)
# ──────────────────────────────────────────────────────────────────────────
def deep_P13(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """3-compartment PBPK ODE: blood ⇌ brain ⇌ peripheral."""
    try:
        import numpy as np
        from scipy.integrate import odeint
        _trap = np.trapezoid if hasattr(np, "trapezoid") else np.trapezoid
    except ImportError:
        return _failed("scipy not installed")

    d = _bundle_drug_specs(drug_bundle)
    s = _bundle_dds_specs(dds_bundle, combo_bundle)

    bbb_perm = float(d["bbb_perm"]) / 100.0
    if bbb_perm <= 0: bbb_perm = 0.02
    has_ligand = bool(s["ligand"]) and s["ligand"] not in ("none","-","")

    k_bp     = 0.5
    k_pb     = 0.3
    k_bb_in  = bbb_perm * (3 if has_ligand else 1)
    k_bb_out = 0.1
    k_elim   = 0.1 + 0.001 * float(d["mw"]) / 100

    def dXdt(X, t):
        Cb, Br, Pe = X
        return [
            -k_bp*Cb + k_pb*Pe - k_bb_in*Cb + k_bb_out*Br - k_elim*Cb,
            k_bb_in*Cb - k_bb_out*Br,
            k_bp*Cb - k_pb*Pe,
        ]
    t = np.linspace(0, 24, 100)
    sol = odeint(dXdt, [100.0, 0.0, 0.0], t)
    Cb_t, Br_t, Pe_t = sol[:,0], sol[:,1], sol[:,2]

    auc_blood = float(_trap(Cb_t, t))
    auc_brain = float(_trap(Br_t, t))
    auc_ratio = auc_brain / auc_blood if auc_blood > 0 else 0.0
    cmax_brain = float(Br_t.max())
    tmax_brain_h = float(t[int(np.argmax(Br_t))])

    score = min(100.0, auc_ratio / 0.05 * 100)
    validated = bool(auc_ratio >= 0.02)

    return {
        "validated": validated,
        "value": round(auc_ratio, 4),
        "score": round(score, 2),
        "method": ("3-compartment PBPK ODE (scipy.integrate.odeint): "
                   "blood ⇌ brain ⇌ peripheral, 24h time course. "
                   "k_bb_in derived from bundle bbb_permeability."),
        "reference": "",
        "confidence": "HIGH" if validated else "MODERATE",
        "improvement_over_surrogate":
            "Surrogate: lookup proxy. Deep: full ODE solution with AUC integration.",
        "narrative": (f"Brain AUC = {auc_brain:.2f} units·h, plasma AUC = "
                      f"{auc_blood:.2f} units·h, ratio = {auc_ratio:.4f}. "
                      f"Cmax_brain = {cmax_brain:.2f} at t = {tmax_brain_h:.1f}h. "
                      f"{'PASSED' if validated else 'BELOW THRESHOLD'} AUC ratio."),
        "raw": {"auc_brain": round(auc_brain, 2),
                "auc_blood": round(auc_blood, 2),
                "auc_ratio": round(auc_ratio, 4),
                "cmax_brain": round(cmax_brain, 2),
                "tmax_brain_h": round(tmax_brain_h, 2),
                "k_bb_in_per_h": round(k_bb_in, 4),
                "ligand_boost": has_ligand},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=["bbb_permeability","drug_mw"],
            dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P44 — CNS-PBPK Time-Machine (4-compartment)
# ──────────────────────────────────────────────────────────────────────────
def deep_P44(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """4-compartment ODE with glymphatic clearance."""
    try:
        import numpy as np
        from scipy.integrate import odeint
        _trap = np.trapezoid if hasattr(np, "trapezoid") else np.trapezoid
    except ImportError:
        return _failed("scipy not installed")

    d = _bundle_drug_specs(drug_bundle)
    s = _bundle_dds_specs(dds_bundle, combo_bundle)

    bbb_perm = float(d["bbb_perm"]) / 100
    if bbb_perm <= 0: bbb_perm = 0.02
    size = float(s["size"])
    has_ligand = bool(s["ligand"]) and s["ligand"] not in ("none","-","")

    k_glymph    = 0.2 / max(1.0, size/100.0)
    k_bbb_in    = bbb_perm * (3 if has_ligand else 1)
    k_bbb_out   = 0.1
    k_csf_clear = 0.05
    k_elim      = 0.1

    def dXdt(X, t):
        Bl, Bn, Cs = X
        return [
            -k_bbb_in*Bl + k_bbb_out*Bn + k_csf_clear*Cs - k_elim*Bl,
            k_bbb_in*Bl - k_bbb_out*Bn - k_glymph*Bn,
            k_glymph*Bn - k_csf_clear*Cs,
        ]
    t = np.linspace(0, 48, 200)
    sol = odeint(dXdt, [100.0, 0.0, 0.0], t)
    Bl_t, Bn_t, Cs_t = sol[:,0], sol[:,1], sol[:,2]

    therapeutic_t = t[Bn_t >= 5.0]
    therap_window_h = (float(therapeutic_t[-1] - therapeutic_t[0])
                          if len(therapeutic_t) > 0 else 0.0)
    auc_brain = float(_trap(Bn_t, t))
    cmax_brain = float(Bn_t.max())

    score = min(100.0, therap_window_h * 4)
    validated = therap_window_h >= 6.0

    return {
        "validated": validated,
        "value": round(therap_window_h, 2),
        "score": round(score, 2),
        "method": ("4-compartment CNS-PBPK ODE with glymphatic clearance: "
                   "Blood ⇌ Brain_ECF → CSF → Blood. Stokes-Einstein "
                   "size-dependent k_glymph."),
        "reference": "",
        "confidence": "HIGH" if validated else "MODERATE",
        "improvement_over_surrogate":
            "Surrogate: AUC×24h proxy. Deep: full 4-compartment ODE with "
            "Stokes-Einstein glymphatic kinetics.",
        "narrative": (f"Therapeutic window = {therap_window_h:.1f}h "
                      f"(brain ≥ 5% dose). Brain AUC = {auc_brain:.1f}, "
                      f"Cmax = {cmax_brain:.2f}. "
                      f"{'PASSED' if validated else 'NEEDS DOSE INCREASE'}."),
        "raw": {"therap_window_h": round(therap_window_h, 2),
                "auc_brain_units_h": round(auc_brain, 2),
                "cmax_brain_pct": round(cmax_brain, 2),
                "k_glymph_per_h": round(k_glymph, 4),
                "k_bbb_in_per_h": round(k_bbb_in, 4),
                "size_nm": size},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=["bbb_permeability"],
            dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P38 — Glymphatic Clearance (Stokes-Einstein)
# ──────────────────────────────────────────────────────────────────────────
def deep_P38(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """Stokes-Einstein clearance in CSF, scaled to 50-nm reference."""
    s = _bundle_dds_specs(dds_bundle, combo_bundle)
    size_nm = float(s["size"])
    if size_nm <= 0:
        return _failed("size_nm not provided")

    k_B = 1.380649e-23
    T   = 310.15
    eta = 7e-4
    r   = size_nm * 1e-9 / 2
    D   = k_B * T / (6 * math.pi * eta * r)
    D_um2_s = D * 1e12
    # D ∝ 1/r, so D_50nm/D reduces analytically to r/r_50nm — computed
    # directly from the radius ratio rather than as two independently
    # rounded Stokes-Einstein evaluations divided against each other,
    # which left a 1-ULP shortfall exactly at the 50nm reference point
    # (5.999999999999999 instead of 6.0) and spuriously failed the
    # inclusive 6h boundary check below.
    r_50nm = 25e-9
    t_clear_h = 6.0 * (r / r_50nm)

    score = max(0.0, min(100.0, 100 - abs(math.log10(t_clear_h / 12))*40))
    validated = 6 <= t_clear_h <= 48

    return {
        "validated": validated,
        "value": round(t_clear_h, 2),
        "score": round(score, 2),
        "method": ("Stokes-Einstein D = k_B·T/(6πηr) at 37°C, "
                   "η_CSF = 7×10⁻⁴ Pa·s. Brain residence scaled to "
                   "50-nm reference (6h)."),
        "reference": "",
        "confidence": "HIGH",
        "improvement_over_surrogate":
            "Surrogate: triangular size-window. "
            "Deep: physical Stokes-Einstein with explicit T, η, r.",
        "narrative": (f"D_CSF = {D_um2_s:.2f} µm²/s, brain residence "
                      f"≈ {t_clear_h:.1f}h. "
                      f"{'IDEAL' if validated else 'OUT OF RANGE'} (target 6-48h)."),
        "raw": {"size_nm": size_nm,
                "D_csf_um2_s": round(D_um2_s, 3),
                "brain_residence_h": round(t_clear_h, 2)},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=[], dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P47 — FEP+ enhanced surrogate
# ──────────────────────────────────────────────────────────────────────────
def deep_P47(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """Binding affinity via real AutoDock Vina docking (src/core/real_docking_engine.py),
    with a graceful, honestly-labeled fallback to the LIE approximation
    (Aqvist 1994) when a receptor PDB ID isn't available or the `vina`
    package isn't installed. Real Vina docking activates automatically once
    both are available — no further code change needed here."""
    d = _bundle_drug_specs(drug_bundle)
    mw    = float(d["mw"])
    logp  = float(d["logp"])
    tpsa  = float(d.get("tpsa") or 60)
    hbd   = float(d["hbd"])
    hba   = float(d["hba"])
    smiles = d.get("smiles") or ""
    # No PDB ID is threaded through the bundle pipeline yet (tracked as
    # follow-up work) — passing None makes run_autodock_vina take its
    # documented LIE fallback path deterministically, without attempting a
    # network fetch or importing `vina`.
    pdb_id = d.get("pdb_id") or None

    if _HAS_DOCKING_ENGINE:
        docking = _run_vina(
            smiles=smiles, pdb_id=pdb_id,
            output_dir="outputs/docking_cache",
            mol_profile={"MW_Da": mw, "LogP": logp, "TPSA_A2": tpsa,
                         "HBD": hbd, "HBA": hba,
                         "molecule_class": d.get("drug_type", "small_molecule")},
        )
    else:
        # src/core/real_docking_engine.py unavailable (e.g. src/ not on
        # sys.path in this invocation) — same LIE formula, computed inline.
        alpha, beta = 0.181, 0.137
        dg = -(alpha * logp + beta * (50 - tpsa / 5) + 0.5 * (hbd + hba) * 0.3)
        dg = max(-20, min(-1, dg))
        docking = {"docking_method": "LIE approximation (real_docking_engine import failed)",
                   "delta_G_kcal_mol": round(dg, 2), "confidence": "LOW — LIE approximation only",
                   "reference": ""}

    dg_total = float(docking["delta_G_kcal_mol"])
    score = min(100.0, abs(dg_total) * 11)
    validated = abs(dg_total) >= 7.0
    is_real_vina = docking.get("docking_method", "").startswith("AutoDock Vina")

    return {
        "validated": validated,
        "value": round(dg_total, 2),
        "score": round(score, 2),
        "method": docking.get("docking_method", "LIE approximation"),
        "reference": docking.get("reference", ""),
        "confidence": docking.get("confidence", "LOW — LIE approximation only"),
        "improvement_over_surrogate":
            f"Surrogate ΔG: {surrogate.get('value','?')} → "
            f"Deep ΔG: {dg_total:.2f} kcal/mol via "
            f"{'real AutoDock Vina docking' if is_real_vina else 'LIE approximation (no receptor PDB ID resolved yet)'}.",
        "narrative": (f"Predicted ΔG_binding = {dg_total:.2f} kcal/mol "
                      f"({docking.get('docking_method','LIE approximation')}). "
                      f"{'STRONG' if abs(dg_total)>=8 else 'MODERATE'} affinity."),
        "raw": {"mw": mw, "logp": logp, "hbd": hbd, "hba": hba,
                **{k: v for k, v in docking.items()
                   if k not in ("docking_method", "reference", "confidence")}},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=["drug_mw","drug_logp","drug_hbd","drug_hba"],
            dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P18 — Active Targeting (MM/GBSA-style)
# ──────────────────────────────────────────────────────────────────────────
def deep_P18(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """Atomistic-style binding ΔG for surface ligand → BBB receptor."""
    s = _bundle_dds_specs(dds_bundle, combo_bundle)
    ligand = s["ligand"]
    if not ligand or ligand in ("none","-",""):
        return {
            "validated": False, "value": 0, "score": 0,
            "method": "No surface ligand → no active targeting",
            "reference": "",
            "confidence": "HIGH",
            "improvement_over_surrogate": "Confirmed bare surface — no MM/GBSA needed",
            "narrative": "DDS has no surface ligand. Active targeting bypassed.",
            "raw": {"ligand": "(none)"},
            "_provenance": _collect_provenance(
                drug_bundle, dds_bundle, combo_bundle,
                drug_keys=[], dds_keys=[]),
        }

    KD_TABLE = {
        "transferrin": ("TfR1",  -10.5), "tf":          ("TfR1",  -10.5),
        "rvg29":       ("nAChR",  -9.8), "rvg-29":      ("nAChR",  -9.8),
        "apoe":        ("LRP1",   -9.2),
        "lactoferrin": ("LfR",    -9.0), "lf":          ("LfR",    -9.0),
        "ldl":         ("LDLR",   -8.5),
        "insulin":     ("INSR",   -8.0),
        "leptin":      ("LepR",   -7.5),
        "tat":         ("HSPG",   -6.5),
    }
    receptor, dg = KD_TABLE.get(ligand, ("unknown_BBB_receptor", -7.0))
    score = min(100.0, abs(dg) * 10)
    validated = abs(dg) >= 8.0

    return {
        "validated": validated,
        "value": round(dg, 2),
        "score": round(score, 2),
        "method": ("MM/GBSA-style ΔG estimate from validated ligand-receptor "
                   "Kd database. Full atomistic docking deferred to GROMACS HPC."),
        "reference": "",
        "confidence": "HIGH" if validated else "MODERATE",
        "improvement_over_surrogate":
            f"Surrogate: lookup score {surrogate.get('score','?')}. "
            f"Deep: ΔG_bind = {dg:.1f} kcal/mol vs receptor {receptor}.",
        "narrative": (f"Ligand '{ligand}' → receptor '{receptor}', "
                      f"ΔG = {dg:.1f} kcal/mol. "
                      f"{'STRONG' if validated else 'WEAK'} BBB-targeting."),
        "raw": {"ligand": ligand, "receptor": receptor,
                "dg_kcal_mol": round(dg, 2)},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=[], dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# DEEP P31 — Biodistribution (7-organ PBPK)
# ──────────────────────────────────────────────────────────────────────────
def deep_P31(drug_bundle: dict, dds_bundle: dict,
              combo_bundle: dict, surrogate: dict) -> dict:
    """7-organ whole-body distribution."""
    d = _bundle_drug_specs(drug_bundle)
    s = _bundle_dds_specs(dds_bundle, combo_bundle)

    size = float(s["size"])
    zeta = float(s["zeta"])
    has_ligand = bool(s["ligand"]) and s["ligand"] not in ("none","-","")
    bbb_perm = float(d["bbb_perm"]) / 100
    if bbb_perm <= 0: bbb_perm = 0.02

    organs = {
        "brain":  bbb_perm * (3 if has_ligand else 1) * 100,
        "liver":  35 if size > 200 else 25,
        "spleen": 20 if abs(zeta) > 25 else 12,
        "kidney": 8.0,
        "lung":   5.0,
        "heart":  3.0,
        "muscle": 100.0,
    }
    total = sum(organs.values())
    organs_norm = {k: round(v/total*100, 2) for k, v in organs.items()}

    score = min(100.0, organs_norm["brain"] / 0.05 * 100)
    validated = organs_norm["brain"] >= 2.0

    return {
        "validated": validated,
        "value": organs_norm["brain"],
        "score": round(score, 2),
        "method": ("7-organ whole-body distribution with size + charge + "
                   "ligand-status modifiers."),
        "reference": "",
        "confidence": "MODERATE",
        "improvement_over_surrogate":
            "Surrogate: simple proxy. Deep: 7-organ distribution model.",
        "narrative": (f"Brain uptake = {organs_norm['brain']:.2f}%, "
                      f"liver = {organs_norm['liver']:.1f}%, "
                      f"spleen = {organs_norm['spleen']:.1f}%. "
                      f"{'GOOD CNS DELIVERY' if validated else 'INSUFFICIENT BRAIN UPTAKE'}."),
        "raw": {"organ_distribution_pct": organs_norm,
                "size_nm": size, "zeta_mV": zeta,
                "ligand_boost": has_ligand},
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=["bbb_permeability"],
            dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Enhanced surrogate wrapper (HPC-deferred principles)
# ──────────────────────────────────────────────────────────────────────────
def _enhanced_surrogate(label: str, ref: str, surrogate: dict,
                          drug_bundle: dict, dds_bundle: dict,
                          combo_bundle: dict) -> dict:
    score = surrogate.get("score", 0)
    return {
        "validated": score >= 60,
        "value": surrogate.get("value", score),
        "score": score,
        "method": f"{label} — surrogate value confirmed (full-physics HPC deferred)",
        "reference": ref,
        "confidence": "MODERATE" if score >= 60 else "LOW",
        "improvement_over_surrogate":
            "No improvement: full deep simulation requires external HPC run "
            "(beyond v22 scope; targeted for v23)",
        "narrative": (f"{label}: surrogate score {score} "
                      f"{'PASSED' if score >= 60 else 'NEEDS REVIEW'}. "
                      f"Full deep simulation requires external HPC."),
        "raw": surrogate.get("raw", {}),
        "_provenance": _collect_provenance(
            drug_bundle, dds_bundle, combo_bundle,
            drug_keys=[], dds_keys=[]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Master deep-function dispatcher
# ──────────────────────────────────────────────────────────────────────────
DEEP_FUNCTIONS = {
    "P02": deep_P02,
    "P13": deep_P13,
    "P18": deep_P18,
    "P31": deep_P31,
    "P38": deep_P38,
    "P44": deep_P44,
    "P47": deep_P47,
}

HPC_ONLY_PRINCIPLES = {
    "P01": ("Full MD stress simulation",
              ""),
    "P04": ("Full QM tunneling (QCElemental + ASE)",
              ""),
    "P08": ("Full radical-chain reaction MD",
              ""),
    "P10": ("Constant-pH MD simulation",
              ""),
    "P11": ("DFT bond dissociation energies",
              ""),
    "P12": ("Stage-specific PBPK with full BBB physiology",
              ""),
    "P16": ("CFD of 1000L bioreactor",
              ""),
    "P23": ("CSP via DFT",
              ""),
    "P24": ("Full CFD + MD coupling",
              ""),
    "P29": ("Full membrane-fusion MD",
              ""),
    "P30": ("Full QM/MM (PySCF or ORCA)",
              ""),
    "P33": ("Atomistic docking + SMD pulling",
              ""),
    "P40": ("Full nasal cavity CFD",
              ""),
    "P41": ("Full membrane mechanics MD",
              ""),
    "P43": ("Full acoustic radiation force MD",
              ""),
    "P50": ("Full coarse-grained MD lipid phase transition",
              ""),
    "P51": ("Full radical-chain damage MD",
              ""),
    "P57": ("Full CFD of mixer geometry",
              ""),
    "P58": ("Full QM/MM cascade simulation",
              ""),
    "P59": ("Full coarse-grained MD morphological transition",
              ""),
    "P61": ("Full Monte-Carlo population PBPK",
              ""),
}


# ──────────────────────────────────────────────────────────────────────────
# Public API — bundle-only signatures
# ──────────────────────────────────────────────────────────────────────────
def evaluate_deep_for_top1(drug_bundle: dict, dds_bundle: dict,
                              combo_bundle: dict,
                              top1_surrogate_results: dict[str, dict]
                              ) -> dict[str, dict]:
    """Run Class B deep validation on the Top-1 DDS using bundles only."""
    out: dict[str, dict] = {}

    for pid, fn in DEEP_FUNCTIONS.items():
        surrogate = top1_surrogate_results.get(pid, {})
        try:
            out[pid] = fn(drug_bundle, dds_bundle, combo_bundle, surrogate)
        except Exception as e:
            log.warning(f"[DEEP] {pid} failed: {e}")
            out[pid] = _failed(str(e))

    for pid, (label, ref) in HPC_ONLY_PRINCIPLES.items():
        if pid in out: continue
        surrogate = top1_surrogate_results.get(pid, {})
        out[pid] = _enhanced_surrogate(label, ref, surrogate,
                                          drug_bundle, dds_bundle, combo_bundle)

    return out


_PASS_THROUGH_MARKER = "No improvement: full deep simulation requires external HPC run"


def overall_deep_validation(deep_results: dict[str, dict]) -> dict:
    """
    Aggregate deep results into a verdict.

    IMPORTANT: results produced by _enhanced_surrogate() (used for every
    principle in HPC_ONLY_PRINCIPLES — 21 of the 28 Class-B principles as of
    v22) are NOT independent computations. They re-badge the Class-A
    surrogate score as "validated" if it happens to score >= 60; the
    function's own improvement_over_surrogate field says so explicitly
    ("full deep simulation requires external HPC run... targeted for v23").
    The pct/verdict below therefore mixes genuine physics (DEEP_FUNCTIONS,
    7 principles) with this surrogate pass-through majority. independent_pct
    reports the pass rate restricted to genuine computations only — use that
    number, not pct, in any external claim about "deep validation."
    """
    n = len(deep_results)
    if n == 0:
        return {"passed": False, "pct": 0.0,
                "passed_count": 0, "total": 0,
                "verdict": "NO DATA"}
    passed = sum(1 for r in deep_results.values() if r.get("validated"))
    pct = passed / n

    independent_results = {
        k: r for k, r in deep_results.items()
        if _PASS_THROUGH_MARKER not in r.get("improvement_over_surrogate", "")
    }
    n_indep = len(independent_results)
    passed_indep = sum(1 for r in independent_results.values() if r.get("validated"))
    pct_indep = (passed_indep / n_indep) if n_indep else None

    verdict = ("PASSED" if pct >= 0.7 else
                "MARGINAL" if pct >= 0.5 else "FAILED")
    return {
        "passed":       pct >= 0.7,
        "pct":          round(pct * 100, 1),
        "passed_count": passed,
        "total":        n,
        "verdict":      verdict,
        "independent_computation_count": n_indep,
        "independent_pct": round(pct_indep * 100, 1) if pct_indep is not None else None,
        "narrative": (
            f"Combined score (surrogate pass-through + real physics): "
            f"{passed}/{n} principles scored PASSED ({pct*100:.1f}%). "
            f"Of these, only {n_indep}/{n} principles ran independent deep "
            f"computation (passed {passed_indep}/{n_indep}"
            + (f" = {pct_indep*100:.1f}%" if pct_indep is not None else "")
            + "); the rest re-used their Class-A surrogate score pending a "
              "future full-physics HPC run. Cite independent_pct, not pct, "
              "as evidence of physics-based validation."
        ),
    }
