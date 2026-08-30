"""
================================================================================
CEREBRO-X |  cerebro_62_surrogate_engine.py (Phase 5 — bundle-only)
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead) — CEREBRO-X
Refactored: 2026-04-30 — bundle-only signature, NO legacy support

Class A (Fast Surrogate) implementations for 57 of the 62 principles.
These functions are called for EVERY DDS in the input list and drive the
principle-composite score that determines the ranking.

CONTRACT — every P-function signature is:
    PXX(drug_bundle: Dict, dds_bundle: Dict,
        combo_bundle: Optional[Dict] = None) -> Dict

Where:
    drug_bundle:  output of cerebro_resolved_bundles.resolve_drug_bundle()
                    → 36+ drug-side resolved values with full provenance
    dds_bundle:   output of cerebro_resolved_bundles.resolve_dds_bundle()
                    → 17+ DDS-side resolved material properties
    combo_bundle: output of cerebro_resolved_bundles.resolve_combo_bundle()
                    → drug × DDS interaction properties; carries
                      _meta.dds_row with the original Excel formulation row
                      so surrogates can read user-provided formulation specs
                      (Size_nm, Zeta_Potential_mV, PDI, Drug_Loading_Pct, …)

Returns dict:
    {
      "value":       raw or normalized value,
      "score":       0-100 score for composite ranking,
      "method":      short description of formula used,
      "reference":   literature citation,
      "confidence":  HIGH | MODERATE | LOW,
      "raw":         dict of input values used (incl. _provenance),
      "warnings":    list of warning strings (or empty),
    }

The 5 non-Class-A principles (P21, P32, P45, P55, P56) are handled by the
Deep Engine (cerebro_62_deep_engine.py) and are NOT in this file.
================================================================================
"""
from __future__ import annotations

import logging
import math

log = logging.getLogger("CEREBRO-SURROGATE")

# Bundle helpers from cerebro_resolved_bundles (REQUIRED — no fallback)
from cerebro_resolved_bundles import b_value


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _safe(d: dict, key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None: return float(default)
    try:    return float(v)
    except (ValueError, TypeError): return float(default)


def _str(d: dict, key: str, default: str = "") -> str:
    v = d.get(key)
    return (str(v).lower().strip() if v is not None else default).lower()


def _triangular(value: float, low_opt: float, high_opt: float,
                  decay_low: float = 2.0, decay_high: float = 0.5) -> float:
    """100 inside [low_opt, high_opt], decays linearly outside."""
    if value <= 0: return 0.0
    if low_opt <= value <= high_opt: return 100.0
    if value < low_opt:
        return max(0, 100 - (low_opt - value) * decay_low)
    return max(0, 100 - (value - high_opt) * decay_high)


def _hb(score: float, ref: str, method: str, raw: dict,
         conf: str = "MODERATE", value=None,
         warnings: list[str] | None = None) -> dict:
    """Helper to build a uniform return record."""
    return {
        "value":      value if value is not None else round(score, 2),
        "score":      round(max(0.0, min(100.0, score)), 2),
        "method":     method,
        "reference":  ref,
        "confidence": conf,
        "raw":        raw,
        "warnings":   warnings or [],
    }


# ──────────────────────────────────────────────────────────────────────────
# Milestone 3 — Bundle-based extractors (provenance-preserving)
# ──────────────────────────────────────────────────────────────────────────
def _drug_specs_from_bundle(drug_bundle: dict) -> dict:
    """Extract the standard drug spec dict shape from a resolver bundle.

    Every value comes from a ResolvedValue dict with full provenance
    (tier, source, _computational_method). The provenance is collected
    in the `_provenance` sub-dict so surrogate functions can pass it
    forward into their `raw` field.

    IMPORTANT: We use explicit None checks instead of `or default` because
    the resolver legitimately returns 0 for HBD/HBA/aromatic_rings/etc. for
    molecules that genuinely have zero of that feature. Using `or` would
    overwrite valid zeros with the default — a silent bug.
    """
    def _bv(cat: str, default):
        v = b_value(drug_bundle, cat, None)
        return default if v is None else v

    micro = drug_bundle.get("drug_microspecies", {}).get("value") or {}
    if not isinstance(micro, dict): micro = {}
    pka_dom_v = b_value(drug_bundle, "drug_pka_dominant")
    pka_acid_v = b_value(drug_bundle, "drug_pka_acidic")
    pka_base_v = b_value(drug_bundle, "drug_pka_basic")

    # Microspecies: explicit None check on each fraction
    def _mf(key: str, default: float) -> float:
        v = micro.get(key)
        return default if v is None else float(v)

    return {
        "mw":           _bv("drug_mw", 350),
        "logp":         _bv("drug_logp", 2.5),
        "tpsa":         _bv("drug_tpsa", 60),
        "hbd":          _bv("drug_hbd", 2),
        "hba":          _bv("drug_hba", 5),
        "rotbonds":     _bv("drug_rotbonds", 5),
        "arom_rings":   _bv("drug_aromatic_rings", 1),
        "formal_q":     _bv("drug_formal_charge", 0),
        "n_stereo":     _bv("drug_stereocenters", 0),
        "pka_dom":      pka_dom_v,
        "pka_acid":     pka_acid_v,
        "pka_base":     pka_base_v,
        "net_q_pH74":   _mf("net_charge", 0.0),
        "f_cat":        _mf("f_cationic", 0.0),
        "f_ani":        _mf("f_anionic", 0.0),
        "f_zwit":       _mf("f_zwitterion", 0.0),
        "f_neutral":    _mf("f_neutral", 1.0),
        "thalf":        _bv("pk_halflife", 0.5),
        "bbb":          _bv("bbb_permeability", 5),
        # Identifiers + metadata
        "smiles":       drug_bundle.get("_meta",{}).get("identifiers",{}).get("smiles") or
                          b_value(drug_bundle, "drug_smiles", "") or "",
        "fasta":        drug_bundle.get("_meta",{}).get("identifiers",{}).get("fasta") or
                          b_value(drug_bundle, "drug_fasta", "") or "",
        "mclass":       drug_bundle.get("_meta",{}).get("drug_type") or "small_molecule",
        "name":         drug_bundle.get("_meta",{}).get("name") or "",
        # Provenance bundle for downstream reporting
        "_provenance":  _collect_drug_provenance(drug_bundle),
    }


def _dds_specs_from_bundle(dds_bundle: dict, dds_row: dict | None = None) -> dict:
    """Extract DDS specs from a bundle, optionally merging Excel-row data.

    The bundle holds RESOLVED material properties (Tg, Tm, hydrolysis Ea,
    zeta_intrinsic, etc.). The Excel row holds USER-PROVIDED formulation
    properties (Size_nm, Zeta_Potential_mV, PDI, etc.) which are the actual
    measurements of THIS specific formulation. Both are merged into the
    standard dds spec dict.
    """
    dds_row = dds_row or {}
    carrier = (dds_bundle.get("_meta",{}).get("carrier_type") or
                 _str(dds_row, "Carrier_Type", "liposome"))
    return {
        # Formulation-specific from Excel row (researcher measurements)
        "size":     _safe(dds_row, "Size_nm",  _safe(dds_row, "size_nm", 100)),
        "zeta":     _safe(dds_row, "Zeta_Potential_mV",
                            _safe(dds_row, "zeta_potential_mv",
                                    b_value(dds_bundle, "material_zeta_intrinsic", -10) or -10)),
        "pdi":      _safe(dds_row, "PDI",
                            _safe(dds_row, "pdi",
                                    b_value(dds_bundle, "material_pdi", 0.2) or 0.2)),
        "ee":       _safe(dds_row, "Encapsulation_Efficiency_pct", 75),
        "peg":      _safe(dds_row, "PEGylation_Degree_mol_pct",
                            _safe(dds_row, "PEG_Density_mol_pct", 5)),
        "ligand":   _str(dds_row, "Surface_Ligand"),
        "carrier":  carrier,
        "rel_kin":  _str(dds_row, "Release_Kinetics", "sustained"),
        "ph_trig":  _safe(dds_row, "pH_Trigger", 6.5),
        # P06 (endosomal escape scoring, below) reads this. "Endosomal_Escape_Eff"
        # is never a real column in dds_row (df_dds's actual per-formulation
        # column is "PgP_Escape_Coeff", computed in pipeline_runner.py) -- the
        # old key name meant escape=0.5 for every formulation, every time,
        # silently erasing the one term meant to differentiate carriers by
        # their actual escape efficiency in the P06 ranking score.
        "endo_esc": _safe(dds_row, "PgP_Escape_Coeff",
                            _safe(dds_row, "Endosomal_Escape_Eff", 0.5)),
        "phase_T":  _safe(dds_row, "Phase_Transition_Temp_C",
                            b_value(dds_bundle, "material_lipid_tm", 42) or 42),
        "elast":    _safe(dds_row, "Elasticity_kPa", 0.5),
        # Unused by any P-function today (dead value) but corrected for the
        # same reason: "CNS_Bioavailability_Pct" is never a real dds_row
        # column either -- see _dds_metrics.backfill_legacy_aliases.
        "cns_bio":  _safe(dds_row, "BBB_Engineering_Score", 10),
        "scale":    _str(dds_row, "Scale_Up_Readiness", "lab"),
        "drug_load":_safe(dds_row, "Drug_Loading_Pct", 10),
        # Bundle-resolved material properties (Tier 3-7 with provenance)
        "polymer_Tg":  b_value(dds_bundle, "material_polymer_tg"),
        "polymer_Tm":  b_value(dds_bundle, "material_polymer_tm"),
        "hydrolysis_Ea": b_value(dds_bundle, "material_polymer_hydrolysis_ea"),
        "lipid_Tm":    b_value(dds_bundle, "material_lipid_tm"),
        "hamaker":     b_value(dds_bundle, "material_hamaker_constant"),
        "porosity":    b_value(dds_bundle, "material_porosity"),
        "dds_type":    dds_bundle.get("_meta",{}).get("dds_type"),
        # Provenance bundle
        "_provenance": _collect_dds_provenance(dds_bundle),
    }


def _collect_drug_provenance(drug_bundle: dict) -> dict[str, dict]:
    """Pull (tier, source, computational_method) for each resolved category.
    Used by surrogate functions to populate the `raw._provenance` field
    so reports can show 'this score used MW=379.5 (Tier 3, RDKit)'.
    """
    keys_of_interest = ["drug_logp","drug_mw","drug_tpsa","drug_hbd",
                          "drug_hba","drug_pka_acidic","drug_pka_basic",
                          "drug_microspecies","pk_halflife","bbb_cns_mpo",
                          "bbb_logBB","drug_solubility_logS","drug_caco2_papp",
                          "drug_pgp_efflux_ratio","drug_aromatic_rings"]
    prov = {}
    for k in keys_of_interest:
        rec = drug_bundle.get(k, {})
        if not rec: continue
        prov[k] = {
            "value": rec.get("value"),
            "tier":  rec.get("tier"),
            "source": rec.get("source"),
            "_computational_method": rec.get("_computational_method"),
        }
    return prov


def _collect_dds_provenance(dds_bundle: dict) -> dict[str, dict]:
    keys_of_interest = ["dds_type","material_polymer_tg","material_polymer_tm",
                          "material_polymer_hydrolysis_ea",
                          "material_lipid_tm","material_zeta_intrinsic",
                          "material_pdi","material_porosity",
                          "material_hamaker_constant"]
    prov = {}
    for k in keys_of_interest:
        rec = dds_bundle.get(k, {})
        if not rec: continue
        prov[k] = {
            "value": rec.get("value"),
            "tier":  rec.get("tier"),
            "source": rec.get("source"),
            "_computational_method": rec.get("_computational_method"),
        }
    return prov


def _resolve_inputs(drug_bundle: dict, dds_bundle: dict,
                       combo_bundle: dict | None = None
                       ) -> tuple[dict, dict, dict | None]:
    """Bundle-only dispatcher (Phase 5, 2026-04-30).

    Surrogate function contract: every P-function receives
        (drug_bundle, dds_bundle, combo_bundle)
    where:
      drug_bundle:  output of cerebro_resolved_bundles.resolve_drug_bundle()
      dds_bundle:   output of cerebro_resolved_bundles.resolve_dds_bundle()
      combo_bundle: output of cerebro_resolved_bundles.resolve_combo_bundle()
                      with _meta.dds_row carrying the Excel formulation row

    The legacy `(dds_dict, mol_profile_dict)` signature has been removed.
    Callers that previously passed raw dicts must first build bundles via
    resolve_drug_bundle / resolve_dds_bundle.

    Returns:
        (d, s, combo) — d/s are flat spec dicts in the shape surrogate
        bodies expect; combo is the original combo_bundle (or None) for
        any function that needs interaction-property access.
    """
    # Strict validation — fail fast on signature violations rather than
    # silently producing nonsense.
    if not (isinstance(drug_bundle, dict)
              and isinstance(drug_bundle.get("_meta"), dict)
              and "drug_type" in drug_bundle.get("_meta", {})):
        raise TypeError(
            "_resolve_inputs: arg1 is not a drug bundle. Surrogate functions "
            "are bundle-only as of Phase 5. Use cerebro_resolved_bundles."
            "resolve_drug_bundle() to produce one.")
    if not (isinstance(dds_bundle, dict)
              and isinstance(dds_bundle.get("_meta"), dict)
              and "dds_type" in dds_bundle.get("_meta", {})):
        raise TypeError(
            "_resolve_inputs: arg2 is not a DDS bundle. Use "
            "cerebro_resolved_bundles.resolve_dds_bundle() to produce one.")

    d = _drug_specs_from_bundle(drug_bundle)
    dds_row: dict = {}
    if isinstance(combo_bundle, dict):
        dds_row = combo_bundle.get("_meta", {}).get("dds_row", {}) or {}
    s = _dds_specs_from_bundle(dds_bundle, dds_row=dds_row)
    return d, s, combo_bundle


# ──────────────────────────────────────────────────────────────────────────
# Molecule-aware physics helpers (used across many surrogate functions)
# ──────────────────────────────────────────────────────────────────────────
def _bbb_propensity(d: dict) -> float:
    """Wager TT (2010) ACS Chem Neurosci 1:420 — CNS MPO surrogate.

    Returns 0..6 score; ≥4 is good CNS-permeability propensity.
    Combines: LogP (optimal 1-3), MW (≤500), HBD (≤1), TPSA (≤90),
    pKa_basic (≤8), aromatic rings (≤3).
    """
    logp = d["logp"]; mw = d["mw"]; hbd = d["hbd"]; tpsa = d["tpsa"]
    pkab = d["pka_base"] if d["pka_base"] is not None else 7.0
    arom = d["arom_rings"]
    s = 0.0
    if 1 <= logp <= 3:   s += 1.0
    elif 0 <= logp <= 4: s += 0.5
    if mw <= 360:        s += 1.0
    elif mw <= 500:      s += 0.5
    if hbd <= 0:         s += 1.0
    elif hbd <= 1:       s += 0.5
    if tpsa <= 60:       s += 1.0
    elif tpsa <= 90:     s += 0.5
    if pkab <= 8:        s += 1.0
    elif pkab <= 10:     s += 0.5
    if arom <= 2:        s += 1.0
    elif arom <= 3:      s += 0.5
    return s


def _membrane_partition_logK(d: dict) -> float:
    """Lipid-water partition coefficient at pH 7.4 (logK_mem).

    Avdeef A (2012) Absorption and Drug Development, 2nd ed:
        logK_mem = LogP − 0.4 × ionization_penalty
    where ionization_penalty = log(1 + f_ionized × 10^pKa_diff)
    For our purposes: penalty ≈ 1 per unit |net_charge| at pH 7.4.
    """
    return d["logp"] - 0.8 * abs(d["net_q_pH74"])


def _hill(value: float, k50: float, n: float = 2.0,
            invert: bool = False) -> float:
    """Hill-equation activation curve, returns 0..100.

    Used to convert continuous values into smooth scores with a tunable
    half-max point and slope. invert=True for "lower is better" metrics.
    """
    if value <= 0: return 0.0 if not invert else 100.0
    h = 100.0 * (value ** n) / (value ** n + k50 ** n)
    return 100.0 - h if invert else h


# ──────────────────────────────────────────────────────────────────────────
# Surrogate functions (P01..P62 except P21, P32, P45, P47, P55, P56)
# ──────────────────────────────────────────────────────────────────────────

def P01(drug_bundle, dds_bundle, combo_bundle=None):
    """Adversarial Stress-Testing — 6 worst-case scenarios.

    Molecule-aware refactor: each scenario's score now depends on the
    drug's chemistry as well as DDS properties.
      • pH/acid/base stress → drug pKa, microspecies fractions, ester groups
      • Heat → drug melting proxy from MW + aromatic rings (Joback group)
      • Antibody/complement → drug formal charge + biologics flag
      • Oxidative → SMILES-detected oxidation-prone moieties
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    smi = d["smiles"]
    scenarios = []

    # ─── Scenario 1: pH 4.5 (early endosome) ────────────────────────
    # Drug stable if non-acid-sensitive AND pH-trigger matches
    drug_acid_sens = (("C(=O)O" in smi and "OC(=O)" in smi) or  # esters
                       (d["pka_acid"] is not None and d["pka_acid"] < 5))
    pH45_score = 80 if 5 <= s["ph_trig"] <= 7.4 else 50
    if drug_acid_sens: pH45_score *= 0.7
    scenarios.append(pH45_score)

    # ─── Scenario 2: pH 2 (gastric) ─────────────────────────────────
    # Drugs that are highly cationic at pH 7.4 stay protonated at pH 2 → may
    # destabilize lipid carriers. Anionic drugs become neutral, may release.
    pH2_score = 60 if s["carrier"] in ("plga","polymer","solid_lipid") else 30
    pH2_score *= (1 - 0.3 * d["f_cat"])     # cation-rich drugs penalty
    scenarios.append(max(20, pH2_score))

    # ─── Scenario 3: pH 8.5 (intestinal) ────────────────────────────
    pH85_score = 70 if s["carrier"] in ("liposome","plga") else 50
    pH85_score *= (1 - 0.3 * d["f_ani"])     # anionic drugs penalty at high pH
    scenarios.append(max(20, pH85_score))

    # ─── Scenario 4: 42°C heat stress ───────────────────────────────
    # Carrier phase-transition margin AND drug thermal-stability proxy.
    # Joback (1987): T_b ≈ 198 + 5·(MW/100) + 12·aromatic_rings (very rough)
    drug_Tb_proxy = 198 + 5 * (d["mw"]/100) + 12 * d["arom_rings"]
    drug_thermal_margin = (drug_Tb_proxy - 315) / 100  # 42°C = 315 K
    carrier_margin = abs(42 - s["phase_T"])
    # Continuous (sigmoid-like): 0.3 at margin=-1, 1.0 at margin=+1
    drug_thermal_factor = 0.5 + 0.5 / (1 + math.exp(-2 * drug_thermal_margin))
    heat_score = min(100, carrier_margin * 15) * drug_thermal_factor + 5 * drug_thermal_factor
    scenarios.append(heat_score)

    # ─── Scenario 5: Antibody/complement ────────────────────────────
    # Strongly cationic drugs (f_cat>0.5) attract C3-corona → faster clearance
    comp_score = 80 if s["peg"] >= 5 else 40
    if d["f_cat"] > 0.5:   comp_score *= 0.8
    if abs(d["formal_q"]) >= 1: comp_score *= 0.85
    scenarios.append(comp_score)

    # ─── Scenario 6: Oxidative stress ───────────────────────────────
    # Drugs with phenols (-OH on aromatic), thioethers (-S-), or aldehyde
    # are oxidation-prone.
    # NOTE: these SMILES substring checks are intentionally case-SENSITIVE —
    # lowercase letters denote aromatic ring atoms, uppercase denotes the
    # substituent (e.g. phenol's aromatic ring is "c1ccccc1", its -OH
    # substituent is "O"). Calling .lower() on the whole string here used
    # to erase that distinction and make the phenol pattern permanently
    # unmatchable for any input. Also broadened to the same three phenol
    # orderings P08 already checks — RDKit's own canonical phenol SMILES
    # is "Oc1ccccc1" (O first), which the original single "c1ccccc1O"
    # (O last) pattern never matched either.
    phenol_present = ("c1ccccc1O" in smi or "Oc1cc" in smi or "Oc1ccc" in smi)
    ox_prone = (phenol_present or "S" in smi or "C=O" in smi)
    ox_score = 75 if s["carrier"] in ("plga","polymer","metallic") else 45
    if ox_prone: ox_score *= 0.75
    scenarios.append(ox_score)

    score = sum(scenarios) / len(scenarios)
    return _hb(score, "",
                "Mean of 6 stress scenarios (pH4.5, pH2, pH8.5, 42°C, "
                "complement, oxidation); each scenario penalized by drug-"
                "specific sensitivities derived from SMILES + microspeciation",
                {"scenarios": [round(x,1) for x in scenarios],
                  "drug_LogP": d["logp"], "drug_f_cat_pH7.4": d["f_cat"],
                  "drug_f_ani_pH7.4": d["f_ani"],
                  "drug_acid_sensitive": drug_acid_sens,
                  "drug_thermal_margin": round(drug_thermal_margin, 2),
                  "drug_oxidation_prone": ox_prone,
                  "carrier": s["carrier"], "PEG_pct": s["peg"]})


def P02(drug_bundle, dds_bundle, combo_bundle=None):
    """Cross-Species PK Scaling (Allometric) — drug-only, BBB-aware."""
    d = _drug_specs_from_bundle(drug_bundle)
    # Body-weight^0.75 scaling success indicator
    # Score reflects how predictable scaling will be
    if d["mclass"] == "small_molecule":
        scale_score = 90 if d["mw"] < 500 else 70
    elif d["mclass"] in ("biologic","monoclonal_antibody","antibody","mab"):
        scale_score = 60   # biologics scale poorly
    else:
        scale_score = 75
    # BBB-related boost if drug already known to cross
    if d["bbb"] > 5: scale_score = min(100, scale_score + 10)
    return _hb(scale_score, "",
                "BW^0.75 scaling + class-specific adjustment",
                {"mw": d["mw"], "mclass": d["mclass"], "bbb_pct": d["bbb"]})


def P03(drug_bundle, dds_bundle, combo_bundle=None):
    """Competitive DDS Landscape — novelty score.

    Molecule-aware refactor: "novel" combos depend on whether the
    drug-class × carrier combination is well-trodden in CNS literature.
    A LogP=4.5 base in a transferrin-PLGA = highly trodden (Donepezil-like).
    A LogP=0.05 zwitterion in the same carrier = very rare.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    # Common ligand-carrier combos in CNS literature → less novel
    NOVELTY_PENALTY = {
        ("transferrin","liposome"): 30, ("rvg29","plga"): 25,
        ("apoe","liposome"): 30,        ("transferrin","plga"): 25,
        ("","polymer"): 50,             ("","liposome"): 50,
    }
    key = (s["ligand"], s["carrier"])
    base_penalty = NOVELTY_PENALTY.get(key, 10)

    # Drug-class novelty: most CNS DDS literature targets lipophilic basic
    # amines (LogP 2-5, basic pKa). Continuous distance from "trodden zone".
    # Trodden center: LogP=3.5, pKa_b=9.5, MW=350.
    logp_dist = abs(d["logp"] - 3.5) / 2.0      # 0 = perfectly trodden
    pka_dist = abs((d["pka_base"] or 9.5) - 9.5) / 2.5
    mw_dist = abs(d["mw"] - 350) / 200
    novelty_distance = (logp_dist + pka_dist + mw_dist) / 3.0   # 0..~3
    novelty_bonus = min(30, novelty_distance * 12)    # max +30 for very atypical
    base_penalty -= novelty_bonus
    if d["f_zwit"] > 0.5:     # zwitterion in nano-DDS literature is rare
        base_penalty -= 10
    if d["mclass"] in ("biologic","antibody","monoclonal_antibody","mab"):
        base_penalty -= 5     # CNS biologic delivery still less explored

    novelty = max(20, min(100, 100 - base_penalty))
    return _hb(novelty, "",
                "Novelty = 100 - frequency_of_combo_in_CNS_trials, "
                "modified by whether the drug's LogP/pKa/MW profile is in "
                "the typical CNS-DDS-literature zone (basic amines, LogP 2-5)",
                {"carrier": s["carrier"], "ligand": s["ligand"] or "(none)",
                  "drug_LogP": d["logp"], "drug_pKa_base": d["pka_base"],
                  "drug_MW": d["mw"], "novelty_distance": round(novelty_distance,2),
                  "drug_f_zwit": d["f_zwit"], "drug_class": d["mclass"]},
                conf="LOW")


def P04(drug_bundle, dds_bundle, combo_bundle=None):
    """Quantum Coherence Transport — only meaningful for small drugs."""
    d = _drug_specs_from_bundle(drug_bundle)
    if d["mw"] >= 500:
        return _hb(50, "",
                    "MW ≥ 500 Da → tunneling negligible",
                    {"mw": d["mw"]}, conf="LOW",
                    warnings=["Quantum tunneling only meaningful for MW<500 Da"])
    # WKB-style: smaller barrier (lower LogP variance) = higher tunneling
    barrier = abs(d["logp"] - 2.5) + 1.0   # eV-equivalent surrogate
    p_tunnel = math.exp(-2 * barrier)
    score = min(100, p_tunnel * 200)
    return _hb(score, "",
                "WKB tunneling: P ∝ exp(-2·barrier)",
                {"mw": d["mw"], "barrier_eV_proxy": round(barrier, 2)},
                value=round(p_tunnel, 4))


def P05(drug_bundle, dds_bundle, combo_bundle=None):
    """Patient Subgroup Stratifier — drug-only."""
    d = _drug_specs_from_bundle(drug_bundle)
    # CYP-substrate risk → narrower applicability
    cyp_risk = 0
    smi = d["smiles"]
    # Heuristic: tertiary amines + aromatic → CYP2D6/3A4 substrate
    if smi.count("N") >= 1 and "c1cc" in smi.lower(): cyp_risk += 30
    if d["logp"] > 4: cyp_risk += 20  # high LogP = often CYP substrate
    score = max(40, 100 - cyp_risk)
    return _hb(score, "",
                "% subgroups responding (lower CYP risk = more universal)",
                {"cyp_risk_pct": cyp_risk})


def P06(drug_bundle, dds_bundle, combo_bundle=None):
    """Lysosomal Trafficking — endosomal escape efficiency.

    Molecule-aware: drugs that are LIPOPHILIC (logK_mem high) and small
    (MW<500) escape passively through the lipid bilayer once the endosome
    acidifies. Drugs that are HIGHLY CHARGED at endosomal pH (5.0-5.5)
    are membrane-impermeant and depend entirely on carrier escape.

    References:
      - Smith SA et al (2019) Trends Biotechnol 37:1077
      - Stewart MP et al (2018) Chem Rev 118:7409
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    escape = s["endo_esc"]
    if escape > 1: escape /= 100   # normalize if given as %
    ph_boost = 1.2 if s["ph_trig"] <= 6.0 else 1.0

    # ── Drug-side passive permeability at endosomal pH 5.5 ──
    # Henderson-Hasselbalch fraction-cationic at pH 5.5 (basic drugs):
    if d["pka_base"] is not None:
        f_cat_endosome = 1.0 / (1.0 + 10**(5.5 - d["pka_base"]))
    else:
        f_cat_endosome = 0.0
    # Higher LogP and lower endosomal charge → drug can permeate alone.
    drug_passive = max(0.0, min(1.0,
                       0.6 * (d["logp"] / 5.0) +
                       0.4 * (1.0 - f_cat_endosome) -
                       0.3 * (d["mw"] / 800)))

    # Total escape: combine carrier-mediated + drug-passive
    total_escape = escape + drug_passive * (1 - escape)   # complementary
    score = min(100, total_escape * 100 * ph_boost)
    return _hb(score, "",
                "Carrier endosomal_escape ⊕ drug-passive permeation at pH 5.5; "
                "drug-passive = LogP-driven for neutral drugs, "
                "blocked for endosomally-cationic drugs",
                {"carrier_escape_eff": round(escape, 3),
                  "ph_trigger": s["ph_trig"], "drug_LogP": d["logp"],
                  "drug_MW": d["mw"], "drug_pKa_base": d["pka_base"],
                  "drug_f_cat_at_pH5.5": round(f_cat_endosome, 3),
                  "drug_passive_permeation": round(drug_passive, 3),
                  "total_escape": round(total_escape, 3)})


def P07(drug_bundle, dds_bundle, combo_bundle=None):
    """Real-Time Literature Mining — count-based heuristic (no live API)."""
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    # Common combos have more literature → bonus
    base = 40
    if s["ligand"] in ("transferrin","apoe","rvg29"): base += 30
    if s["carrier"] in ("liposome","plga"): base += 20
    if d["bbb"] > 0: base += 10
    score = min(100, base)
    return _hb(score, "",
                "log-count proxy of literature support",
                {"carrier": s["carrier"], "ligand": s["ligand"] or "(none)"},
                conf="LOW",
                warnings=["Surrogate uses heuristic; live PubMed fetch in deep mode"])


def P08(drug_bundle, dds_bundle, combo_bundle=None):
    """Degradation under oxidative stress — Arrhenius + drug oxidation-prone moieties.

    Molecule-aware: the drug itself can be oxidatively-degraded if it
    contains phenols, thioethers, aldehydes, or polyene chains. We
    multiplicatively combine carrier Ea with drug oxidation susceptibility.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    smi = d["smiles"]
    Ea_TABLE = {"liposome":80, "plga":110, "polymer":105, "micelle":75,
                  "dendrimer":90, "nanogel":85, "solid_lipid":95, "metallic":150}
    Ea = Ea_TABLE.get(s["carrier"], 90)
    R, T = 8.314e-3, 310
    k_ox_carrier = math.exp(-Ea / (R * T))

    # ── Drug oxidation-prone moieties (SMARTS surrogate via SMILES strings) ──
    drug_ox_penalty = 0
    ox_groups = []
    # Case-sensitive by necessity — see the note in P01 above.
    if "c1ccccc1O" in smi or "Oc1cc" in smi or "Oc1ccc" in smi:
        drug_ox_penalty += 15; ox_groups.append("phenol")
    if "S" in smi and "S(=O)" not in smi:    # thioether (not sulfoxide/sulfone)
        drug_ox_penalty += 10; ox_groups.append("thioether")
    if "C=O" in smi and "OC=O" not in smi:   # aldehyde-like
        drug_ox_penalty += 10; ox_groups.append("aldehyde-like")
    if "C=CC=C" in smi:                       # polyene
        drug_ox_penalty += 8;  ox_groups.append("polyene")
    # Continuous aromatic penalty (1 per ring, capped at 8)
    arom_penalty = min(8, 2.5 * d["arom_rings"])
    drug_ox_penalty += arom_penalty
    # Lipophilicity boost: very lipophilic drugs sink into lipid bilayer
    # interior, sheltered from radicals → small bonus
    lipophilic_bonus = max(0, min(5, d["logp"] - 2))
    drug_ox_penalty -= lipophilic_bonus

    score = min(100, max(0, (Ea - 60) * 1.5 - drug_ox_penalty))
    return _hb(score, "",
                "Arrhenius k=A·exp(-Ea/RT) for carrier; minus penalties for "
                "drug-side oxidation-prone moieties detected in SMILES "
                "(phenols, thioethers, aldehydes, polyenes, polycyclic aromatics)",
                {"carrier": s["carrier"], "Ea_kJ_mol": Ea,
                  "k_ox_proxy": round(k_ox_carrier, 6),
                  "drug_oxidation_groups_detected": ox_groups,
                  "drug_ox_penalty": drug_ox_penalty,
                  "drug_aromatic_rings": d["arom_rings"]})


def P09(drug_bundle, dds_bundle, combo_bundle=None):
    """Digital Pharmacovigilance — metabolite organ accumulation."""
    d = _drug_specs_from_bundle(drug_bundle)
    # Penalty if drug has reactive groups likely to bioaccumulate
    smi = d["smiles"]
    risk = 0
    if "F" in smi: risk += 10   # halogens → kidney accumulation
    if "Cl" in smi: risk += 15
    if d["logp"] > 5: risk += 30   # very lipophilic → fat accumulation
    if d["mw"] > 800: risk += 15   # large MW → biliary excretion only
    score = max(30, 100 - risk)
    return _hb(score, "",
                "100 - sum(metabolite organ accumulation risks)",
                {"smiles_features": {"halogens": "F" in smi or "Cl" in smi,
                                       "high_logp": d["logp"]>5,
                                       "high_mw": d["mw"]>800}})


def P10(drug_bundle, dds_bundle, combo_bundle=None):
    """LNP Ionization — drug-and-carrier joint ionization at endosomal pH.

    Molecule-aware: classical LNP design optimizes the IONIZABLE LIPID's
    pKa to ~6.4 so it protonates upon endosomal acidification, disrupting
    the membrane. But the DRUG must also stay encapsulated at pH 7.4 and
    preferably ionize at endosome to amplify osmotic disruption.

    Score = score_lipid_pKa × score_drug_pH-coupling
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    if s["carrier"] not in ("liposome","solid_lipid","lipid"):
        # For non-LNP carriers, P10 still scores drug ionization stability
        # at storage pH 7.4. Highly cationic (or anionic) drugs need electrolyte
        # balance to remain stable in suspension; net-neutral or zwitterions
        # tolerate broader pH ranges.
        ion_stability = 100 * (1 - 0.4 * abs(d["net_q_pH74"]))
        if d["f_zwit"] > 0.3:    ion_stability += 5    # zwitterion buffer
        return _hb(min(100, ion_stability),
                    "",
                    "Non-LNP carrier — falls back to drug-side ionization "
                    "stability at storage pH 7.4 (lower |net_charge| = better)",
                    {"carrier": s["carrier"],
                      "drug_net_charge_pH7.4": d["net_q_pH74"],
                      "drug_f_zwitterion": d["f_zwit"]}, conf="LOW")

    # ── Lipid side: estimate effective pKa from zeta + pH-trigger ──
    pKa_lipid = 6.0 + (s["zeta"] / -50) * 0.5
    charge_lipid_endosome = 1 / (1 + 10**(5.5 - pKa_lipid))

    # ── Drug side: charge change between pH 7.4 (storage) and pH 5.5 (escape) ──
    # Ideal drug: NEUTRAL at pH 7.4, CATIONIC at pH 5.5 (synergy with lipid).
    if d["pka_base"] is not None:
        f_cat_drug_74  = d["f_cat"]   # already at pH 7.4 from microspeciation
        f_cat_drug_55  = 1.0 / (1.0 + 10**(5.5 - d["pka_base"]))
    else:
        f_cat_drug_74 = f_cat_drug_55 = 0.0
    charge_swing = f_cat_drug_55 - f_cat_drug_74    # ideal: +0.5 to +1.0
    drug_synergy = max(0.0, min(1.0, charge_swing + 0.5))

    score = min(100, charge_lipid_endosome * 100 * (0.5 + 0.5 * drug_synergy))
    return _hb(score, "",
                "Lipid Henderson-Hasselbalch ionization at endosomal pH 5.5, "
                "modulated by drug charge-swing (pH7.4→pH5.5) — ideal drug "
                "co-ionizes with lipid for amplified osmotic disruption",
                {"carrier": s["carrier"], "lipid_pKa_estimate": round(pKa_lipid, 2),
                  "lipid_charge_at_pH5.5": round(charge_lipid_endosome, 3),
                  "drug_pKa_base": d["pka_base"],
                  "drug_f_cat_at_pH7.4": round(f_cat_drug_74, 3),
                  "drug_f_cat_at_pH5.5": round(f_cat_drug_55, 3),
                  "drug_charge_swing": round(charge_swing, 3)})


def P11(drug_bundle, dds_bundle, combo_bundle=None):
    """Formulation Instability Fingerprint — weakest bond Ea."""
    d = _drug_specs_from_bundle(drug_bundle); s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Use SMILES bond patterns as proxy
    smi = d["smiles"]
    # Score = higher = more stable
    weak_score = 100
    # Ester bonds (COO) — easily hydrolyzed
    if "C(=O)O" in smi: weak_score -= 25
    # Hydrazone (NN) — pH-sensitive
    if "N=N" in smi or "/N=N/" in smi: weak_score -= 30
    # Disulfide (SS) — reducible
    if "SS" in smi: weak_score -= 20
    # Carrier-related: PLGA has labile esters → reflect
    if s["carrier"] == "plga": weak_score -= 10
    return _hb(max(20, weak_score), "",
                "100 - sum(weak-bond penalties from SMILES)",
                {"weakest_bonds_present": [
                    "ester" if "C(=O)O" in smi else None,
                    "hydrazone" if "N=N" in smi else None,
                    "disulfide" if "SS" in smi else None,
                ]})


def P12(drug_bundle, dds_bundle, combo_bundle=None):
    """CNS Disease-Stage-Aware Dosing — BBB integrity × drug-intrinsic permeability.

    Molecule-aware: at advanced disease stages BBB is leaky, but a drug
    that is INHERENTLY permeable (high CNS-MPO score) needs less DDS-help.
    A drug that is impermeable (zwitterion, large MW, polar) needs strong
    targeting + intact BBB to compensate.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    stage = (combo_bundle or {}).get("disease_stage", 2)
    BBB_PCT = {1: 1.0, 2: 0.85, 3: 0.60, 4: 0.40}
    bbb_factor = BBB_PCT.get(stage, 0.85)

    # Drug-intrinsic CNS permeability (Wager CNS-MPO 0..6)
    cns_mpo = _bbb_propensity(d)
    drug_perm_factor = cns_mpo / 6.0

    # Active targeting compensates for low drug permeability AND/OR low BBB
    has_active_target = bool(s["ligand"] and s["ligand"] not in ("none","-",""))
    target_boost = 15 if has_active_target else 0
    # Larger boost if drug needs help (low MPO + advanced stage)
    if has_active_target and (drug_perm_factor < 0.5 or bbb_factor < 0.7):
        target_boost = 25

    base = 100 * bbb_factor * (0.4 + 0.6 * drug_perm_factor)
    score = min(100, base + target_boost)
    return _hb(score, "",
                "Score = 100·BBB_integrity_factor × (0.4 + 0.6·CNS-MPO/6) "
                "+ targeting_boost (larger boost for hard-to-deliver drugs)",
                {"disease_stage": stage, "bbb_factor": bbb_factor,
                  "drug_CNS_MPO_score": round(cns_mpo, 2),
                  "drug_perm_factor": round(drug_perm_factor, 3),
                  "drug_LogP": d["logp"], "drug_MW": d["mw"],
                  "drug_TPSA": d["tpsa"], "drug_HBD": d["hbd"],
                  "drug_pKa_base": d["pka_base"],
                  "active_targeting": has_active_target,
                  "targeting_boost": target_boost})


def P13(drug_bundle, dds_bundle, combo_bundle=None):
    """PBPK Digital Twin — 3-compartment surrogate."""
    d = _drug_specs_from_bundle(drug_bundle); s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # AUC_brain / AUC_plasma proxy
    bbb_perm = d["bbb"] / 100 if d["bbb"] > 0 else 0.05
    # DDS boost: ligand + good size
    dds_boost = 1.0
    if s["ligand"] and s["ligand"] not in ("none","-",""): dds_boost *= 2.5
    if 50 <= s["size"] <= 150: dds_boost *= 1.5
    if s["peg"] >= 3: dds_boost *= 1.2   # stealth
    auc_ratio = bbb_perm * dds_boost
    score = min(100, auc_ratio * 1500)   # 0.05 ratio → 75 score
    return _hb(score, "",
                "AUC_brain/AUC_plasma proxy; 3-compartment surrogate",
                {"bbb_perm": bbb_perm, "dds_boost": round(dds_boost, 2),
                  "auc_ratio_estimate": round(auc_ratio, 3)})


def P14(drug_bundle, dds_bundle, combo_bundle=None):
    """Release Profile — t50 sustained-window match, drug-LogP modulated.

    Molecule-aware: a drug that is highly lipophilic (LogP>4) and embedded
    in a lipid carrier RESISTS release → t50 elongates. A hydrophilic drug
    (LogP<1) burst-releases regardless of intended kinetics.
    Higuchi (1961) describes this as drug-matrix partition behavior.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    K_T50 = {"sustained":36, "zero-order":48, "first-order":18,
              "burst":4, "ph-responsive":24, "thermo":30}
    t50_h = K_T50.get(s["rel_kin"], 24)

    # Drug-LogP modulation: K_partition = 10^logP_membrane
    logK_mem = _membrane_partition_logK(d)
    # Continuous LogK-driven retention factor: 1.0 at logK=2, exp-grows above
    if s["carrier"] in ("liposome","solid_lipid","lipid","plga"):
        # f = 0.5 at logK=0, 1.0 at logK=2, 1.5 at logK=4, 2.0 at logK=6
        logK_factor = 0.5 + 0.25 * logK_mem
        logK_factor = max(0.4, min(2.5, logK_factor))
        t50_h *= logK_factor
    # Hydrogen-bond donors slow release from polymer carriers (extra anchoring)
    if s["carrier"] in ("plga","polymer"):
        t50_h *= (1 + 0.05 * d["hbd"])
    # MW-driven diffusion: D ∝ 1/MW^(1/3); larger drug = slower release
    t50_h *= (d["mw"] / 350) ** 0.33

    # Continuous scoring instead of triangular plateau:
    # ideal t50 = 36h; gaussian-like decay from there
    target = 36.0
    score = 100 * math.exp(-((t50_h - target) ** 2) / (2 * 24 ** 2))
    return _hb(score, "",
                "t50 from carrier kinetics × drug-membrane partition factor "
                "(10^logK_mem); HBD-anchoring boost in polymer carriers",
                {"release_kinetics": s["rel_kin"], "carrier": s["carrier"],
                  "drug_LogP": d["logp"],
                  "drug_logK_membrane": round(logK_mem, 2),
                  "drug_HBD": d["hbd"],
                  "t50_h_modulated": round(t50_h, 1)})


def P15(drug_bundle, dds_bundle, combo_bundle=None):
    """Shelf-life — Arrhenius extrapolation modulated by drug hydrolysis risk.

    Molecule-aware: drugs with hydrolyzable bonds (esters, amides, lactones,
    carbamates) shorten formulation shelf-life regardless of carrier.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    BASELINE = {"liposome":18, "plga":36, "polymer":36, "micelle":24,
                  "dendrimer":24, "nanogel":18, "solid_lipid":30, "metallic":48}
    sl25 = BASELINE.get(s["carrier"], 18) * (0.7 + 0.3 * (s["ee"]/100))

    # Drug hydrolysis-risk groups (SMARTS via SMILES substrings)
    smi = d["smiles"]
    hydrolyzable = []
    if "C(=O)O" in smi:           hydrolyzable.append("ester")
    if "C(=O)N" in smi:           hydrolyzable.append("amide")
    if "OC(=O)O" in smi:          hydrolyzable.append("carbonate")
    if "NC(=O)O" in smi:          hydrolyzable.append("carbamate")
    drug_stab_factor = 1.0 - 0.08 * len(hydrolyzable)
    drug_stab_factor = max(0.5, drug_stab_factor)
    sl25_drug = sl25 * drug_stab_factor

    score = min(100, sl25_drug / 0.36)
    return _hb(score, "",
                "Arrhenius baseline × (0.7 + 0.3·EE) × drug_hydrolysis_factor "
                "(0.08 penalty per hydrolyzable bond detected in SMILES)",
                {"carrier": s["carrier"], "ee_pct": s["ee"],
                  "drug_hydrolyzable_groups": hydrolyzable,
                  "drug_stab_factor": round(drug_stab_factor, 3),
                  "shelf_life_months_25C": round(sl25_drug, 1)},
                value=round(sl25_drug, 1))


def P16(drug_bundle, dds_bundle, combo_bundle=None):
    """Scale-up & Manufacturability — drug-crystallinity-aware.

    Molecule-aware: drugs with HIGH MW + many rotatable bonds + many H-bond
    donors tend to be crystalline polymorphs that are HARDER to encapsulate
    consistently at scale. Highly lipophilic drugs aggregate during
    nanoprecipitation, lowering yield.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    SCALE_SCORE = {"lab":40, "pilot":70, "clinical":90, "commercial":100}
    base = SCALE_SCORE.get(s["scale"], 50)
    elast_bonus = min(20, s["elast"] * 20)

    # Drug processability penalty (CONTINUOUS, all drugs differ)
    proc_penalty = 0
    proc_flags = []
    proc_penalty += max(0, (d["mw"] - 350) / 50) * 1.5         # ~+1.5/50Da
    if d["mw"] > 500: proc_flags.append("high_MW")
    proc_penalty += max(0, d["hbd"] - 1) * 2.0                  # +2 per extra HBD
    if d["hbd"] > 3: proc_flags.append("multi_HBD_crystal")
    proc_penalty += max(0, d["logp"] - 3) * 2.0                  # aggregation risk
    if d["logp"] > 5: proc_flags.append("very_lipophilic")
    proc_penalty += max(0, d["rotbonds"] - 5) * 0.8              # flexibility
    if d["rotbonds"] > 10: proc_flags.append("highly_flexible")

    score = max(20, min(100, base + elast_bonus - proc_penalty))
    return _hb(score, "",
                "Scale-readiness × shear-robustness, minus drug-processability "
                "penalties (MW, HBD-crystallinity, LogP-aggregation, flexibility)",
                {"scale_up_readiness": s["scale"],
                  "elasticity_kPa": s["elast"],
                  "drug_MW": d["mw"], "drug_LogP": d["logp"],
                  "drug_HBD": d["hbd"], "drug_RotBonds": d["rotbonds"],
                  "drug_processability_penalty": proc_penalty,
                  "drug_processability_flags": proc_flags})


def P17(drug_bundle, dds_bundle, combo_bundle=None):
    """Nanotoxicity & Immunogenicity — composite, drug-tox-aware.

    Molecule-aware: drugs with reactive moieties (Michael acceptors,
    epoxides, alkylators) add intrinsic toxicity. Strongly cationic drugs
    (large positive net charge at pH 7.4) cause hemolysis directly.
    Biologic drugs add immunogenicity risk.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    smi = d["smiles"]

    # ── Hemolysis: carrier zeta + drug positive net charge ──
    drug_cat_excess = max(0.0, d["net_q_pH74"])
    hemo = max(0, 100 - max(0, s["zeta"]) * 5 - drug_cat_excess * 30)
    # Continuous LogP contribution: very lipophilic drugs (LogP>5) add
    # membrane-disrupting risk regardless of charge
    hemo -= max(0, (d["logp"] - 4.5)) * 4

    # ── Complement activation: PEG step + drug-side immunogenicity ──
    comp = 90 if s["peg"] >= 5 else 70 if s["peg"] >= 3 else 50 if s["peg"] >= 1 else 25
    if d["mclass"] in ("biologic","antibody","monoclonal_antibody","mab"):
        comp -= 15    # biologics inherently more immunogenic
    # MW boost: very large drugs trigger more recognition
    comp -= max(0, (d["mw"] - 500) / 100) * 2

    # ── RES uptake (size optimum 50-200) — unchanged from DDS side ──
    res = _triangular(s["size"], 50, 200, 1.5, 0.4)

    # ── Oxidative ── carrier-class + drug reactive groups
    OX = {"liposome":80, "plga":85, "polymer":85, "micelle":70,
           "dendrimer":75, "metallic":55}
    oxi = OX.get(s["carrier"], 75)
    reactive_groups = []
    if "C=CC(=O)" in smi:    reactive_groups.append("Michael_acceptor"); oxi -= 15
    if "C1OC1" in smi:        reactive_groups.append("epoxide"); oxi -= 20
    if "CC(Cl)" in smi or "CN(Cl)" in smi:
        reactive_groups.append("alkyl_halide"); oxi -= 15
    # Continuous TPSA contribution: high TPSA = more polar surface, less ROS prone
    oxi += max(0, min(8, (d["tpsa"] - 60) * 0.1))
    oxi = max(20, min(100, oxi))

    composite = (hemo + comp + res + oxi) / 4
    return _hb(composite, "",
                "Mean of (hemolysis penalized by drug net+ charge, "
                "complement penalized for biologics, RES size-window, "
                "oxidative penalized for reactive drug moieties)",
                {"hemolysis": round(hemo,1), "complement": comp,
                  "res_uptake": round(res,1), "oxidative": oxi,
                  "drug_net_charge_pH7.4": d["net_q_pH74"],
                  "drug_class": d["mclass"],
                  "drug_reactive_groups": reactive_groups})


def P18(drug_bundle, dds_bundle, combo_bundle=None):
    """Active Targeting — receptor-binding score, drug-compatibility-aware.

    Molecule-aware: a transferrin-targeted carrier delivers all drugs equally
    well in terms of vesicle uptake, but the DRUG must SURVIVE the slow
    transferrin-receptor recycling endosome (acidic) and EXIT into cytoplasm.
    Drugs that protonate/precipitate in acidic endosome (high pKa_base, low
    LogP at low pH) lose more dose per uptake event.
    """
    dds = (combo_bundle or {}).get('_meta',{}).get('dds_row',{}) or {}
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    LIG_AFF = {"transferrin":95, "tf":95, "rvg29":90, "rvg-29":90,
                "apoe":85, "ldl":80, "ldlr":80, "insulin":75,
                "leptin":70, "tat":60, "lactoferrin":80, "lf":80,
                "":20, "none":20, "-":20}
    aff = LIG_AFF.get(s["ligand"], 50)
    density = _safe(dds, "Surface_Ligand_Density_per_nm2", 0.5)
    if density > 1.5: aff = min(100, aff * 1.1)
    elif density < 0.3: aff = max(20, aff * 0.85)

    # Drug-compatibility factor: fraction of dose surviving + escaping
    # endosome to cytoplasm (transferrin path is most acidic).
    # Continuous modulation regardless of ligand identity:
    if s["ligand"] in ("transferrin","tf"):
        # logK_mem at endosomal pH — drug must remain partition-active
        if d["pka_base"] is not None:
            f_cat_55 = 1 / (1 + 10**(5.5 - d["pka_base"]))
        else:
            f_cat_55 = 0
        endo_compat = 1.0 - 0.3 * abs(f_cat_55 - 0.6)
        aff *= max(0.7, endo_compat)
    elif s["ligand"] in ("rvg29","rvg-29"):
        # RVG29 → nicotinic-AChR → continuous MW penalty
        aff *= max(0.7, 1.0 - 0.0003 * max(0, d["mw"] - 300))
    elif s["ligand"] in ("apoe","ldl","ldlr"):
        # ApoE → LRP1 → caveolar transcytosis (less degradative)
        # Continuous LogP boost
        aff = min(100, aff * (1 + 0.02 * max(0, d["logp"] - 1)))
    # Universal LogP modulation: any active-targeting carrier benefits
    # if the drug can subsequently cross brain parenchyma membranes
    # (post-receptor crossing). Continuous, small contribution.
    aff *= (0.95 + 0.01 * max(0, min(5, d["logp"])))

    return _hb(aff, "",
                "Ligand-affinity table × density × drug-compatibility "
                "(receptor-pathway-specific drug requirements: transferrin "
                "needs partial endosomal protonation; RVG29 prefers small MW; "
                "ApoE/LRP1 prefers LogP>1 for post-fusion escape)",
                {"ligand": s["ligand"] or "(none)",
                  "density_per_nm2": density,
                  "drug_LogP": d["logp"], "drug_MW": d["mw"],
                  "drug_pKa_base": d["pka_base"],
                  "final_affinity_score": round(aff, 2)},
                conf="HIGH" if aff >= 70 else "MODERATE")


def P19(drug_bundle, dds_bundle, combo_bundle=None):
    """QbD - Quality by Design — drug-physicochemistry-extended CQAs.

    Molecule-aware: classical CQAs are physical (size, zeta, PDI, EE), but
    a 5th drug-specific CQA captures whether the actual loaded drug-mass
    matches the theoretical maximum for that drug's MW + LogP profile.

    Lipinski Ro5 + drug-loading achievability (Bunjes 2010, Cur Op Coll
    Interface Sci 15:80): typical max drug load for solid lipid =
    LogP × 2 (%w/w) for lipophilic drugs.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    in_spec = 0
    if 50 <= s["size"] <= 200: in_spec += 1
    if -25 <= s["zeta"] <= 25: in_spec += 1
    if s["ee"] >= 70: in_spec += 1
    if s["pdi"] < 0.3: in_spec += 1

    # 5th CQA: drug-loading achievability for THIS drug given its LogP
    drug_load_actual = s["drug_load"]
    drug_load_theoretical = max(2.0, d["logp"] * 2.0)   # Bunjes rule of thumb
    load_ratio = drug_load_actual / drug_load_theoretical
    # Continuous from 0.0 to 1.0 (saturating at ratio≥1)
    load_cqa_score = min(1.0, load_ratio)
    in_spec_continuous = in_spec + load_cqa_score   # continuous 5th CQA

    score = (in_spec_continuous / 5) * 100
    return _hb(score, "",
                "Fraction of CQAs (size, zeta, EE, PDI, drug-loading) "
                "within ICH spec — 5th CQA depends on whether claimed "
                "drug load is feasible given drug LogP",
                {"in_spec": f"{in_spec}/5",
                  "drug_LogP": d["logp"],
                  "drug_load_actual_pct": drug_load_actual,
                  "drug_load_theoretical_max_pct": round(drug_load_theoretical, 1)})


def P20(drug_bundle, dds_bundle, combo_bundle=None):
    """Cost-Efficiency — drug synthesis complexity adds API cost.

    Molecule-aware: stereocenters multiply synthesis cost (chiral synthesis
    or chiral resolution); high MW + many heteroatoms = more synthesis steps.
    Biologics carry orders-of-magnitude higher API cost.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    BASE = {"liposome":3, "plga":5, "polymer":4, "micelle":2,
              "dendrimer":15, "metallic":10, "solid_lipid":4}
    cost = BASE.get(s["carrier"], 5)
    LIG = {"transferrin":3, "rvg29":5, "apoe":4, "lactoferrin":3,
            "":0, "none":0}
    cost += LIG.get(s["ligand"], 1)

    # Drug API cost contribution (CONTINUOUS, all drugs differ)
    drug_cost = 1.0   # baseline $/mg for simple small mol
    drug_cost += 0.5 * d["n_stereo"]      # +50¢ per stereocenter
    # Continuous MW contribution: ~$1 per 100 Da above 200
    drug_cost += max(0, (d["mw"] - 200) / 100) * 1.0
    drug_cost += 0.4 * d["arom_rings"]
    drug_cost += 0.1 * d["rotbonds"]
    if d["mclass"] in ("biologic","antibody","monoclonal_antibody","mab"):
        drug_cost += 50    # biologics: $50/mg API
    elif d["mclass"] == "peptide":
        drug_cost += 10
    cost += drug_cost

    score = max(0, 100 - cost * 3)
    return _hb(score, "",
                "Score = 100 - 3·($/mg estimate, drug+carrier+ligand+API). "
                "Drug API cost from stereocenters, MW, aromatic complexity, class",
                {"carrier_cost": BASE.get(s["carrier"], 5),
                  "ligand_cost": LIG.get(s["ligand"], 1),
                  "drug_API_cost": round(drug_cost, 2),
                  "drug_class": d["mclass"], "drug_stereocenters": d["n_stereo"],
                  "drug_MW": d["mw"], "drug_aromatic_rings": d["arom_rings"],
                  "estimated_total_cost_usd_per_mg": round(cost, 2)},
                conf="LOW")


# P21 is C_translational — handled by translational engine

def P22(drug_bundle, dds_bundle, combo_bundle=None):
    """Protein Corona Predictor — Vroman effect + drug-modulated affinity.

    Molecule-aware: corona thickness depends on (a) carrier hydrophobic patch
    area (driven by zeta + size) AND (b) drug-modulated surface chemistry —
    if the drug is exposed at the carrier interface (typical for high-LogP
    drugs in lipid carriers), it changes the surface protein-binding profile.

    References:
      - Tenzer S et al (2013) Nat Nanotechnol 8:772 (corona discovery)
      - Schöttler S et al (2016) Nat Nanotechnol 11:372 (dysopsonin role)
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)

    # Carrier-side base thickness
    thickness = abs(s["zeta"])/3 + max(0, (s["size"] - 100)/30)

    # Drug-side contribution: drug surface exposure shapes opsonin profile.
    # For ALL carrier types, more lipophilic drugs migrate to corona-water
    # interface. Continuous contribution.
    interface_thickness = 0.15 * max(0, d["logp"] - 1) * (s["drug_load"] / 10)
    thickness += interface_thickness
    # Strongly cationic drugs at the surface attract complement C3
    if d["f_cat"] > 0.6 and abs(s["zeta"]) < 20:
        thickness += 1.0   # net cationic surface boosts C3 corona
    # MW contribution: larger drug perturbs surface more
    thickness += 0.005 * max(0, d["mw"] - 200)

    # PEG protective effect
    if s["peg"] >= 5: thickness *= 0.5
    elif s["peg"] >= 3: thickness *= 0.7

    score = min(100, max(0, 100 * math.exp(-thickness/10)))
    return _hb(score, "",
                "100 × exp(-corona_thickness/10); thickness from carrier "
                "(|zeta|, size) + drug-side (LogP × loading for lipid "
                "carriers; cationic drug penalty for non-PEGylated)",
                {"carrier_thickness_proxy": round(abs(s["zeta"])/3 + max(0,(s["size"]-100)/30),2),
                  "drug_LogP": d["logp"], "drug_load_pct": s["drug_load"],
                  "drug_f_cat_pH7.4": d["f_cat"],
                  "PEG_pct": s["peg"], "carrier": s["carrier"],
                  "final_corona_thickness_proxy": round(thickness, 2)})


def P23(drug_bundle, dds_bundle, combo_bundle=None):
    """Crystal Polymorphism — risk from drug structure."""
    d = _drug_specs_from_bundle(drug_bundle)
    # Polymorph risk: rotatable bonds + H-bond pattern
    # Use simple SMILES heuristic
    smi = d["smiles"]
    # Count single bonds in chain (proxy for rotatable)
    rot_proxy = smi.count("CC") + smi.count("CO") + smi.count("CN")
    risk = min(70, rot_proxy * 3 + d["hbd"] * 5 + d["hba"] * 2)
    score = max(20, 100 - risk)
    return _hb(score, "",
                "100 - polymorph risk (rot_bonds + H-bond pattern)",
                {"rotatable_proxy": rot_proxy, "hbd": d["hbd"], "hba": d["hba"]})


def P24(drug_bundle, dds_bundle, combo_bundle=None):
    """Shear Stress & Scale-Up Collapse — drug-load-modulated.

    Molecule-aware: high drug loading raises internal viscosity for lipid
    carriers (Bunjes 2010), reducing the critical shear they tolerate
    before vesicle/particle rupture during scale-up tangential flow.
    Highly lipophilic drugs particularly soften vesicles.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    CRIT_SHEAR = {"liposome":1e4, "plga":1e6, "polymer":1e5,
                   "micelle":5e3, "dendrimer":1e7, "metallic":1e8,
                   "solid_lipid":5e4, "nanogel":3e4}
    crit = CRIT_SHEAR.get(s["carrier"], 1e5)

    # Drug-load softening for lipid carriers (CONTINUOUS)
    if s["carrier"] in ("liposome","solid_lipid","lipid","micelle"):
        load_softening = 1.0 - 0.04 * max(0, s["drug_load"] - 5)
        load_softening *= (1 - 0.02 * max(0, d["logp"] - 4))
        load_softening *= (1 - 0.001 * max(0, d["mw"] - 300))
        crit *= max(0.3, load_softening)
    else:
        # Even non-lipid carriers see continuous drug effect on shear tolerance
        # (drug clusters strain the matrix)
        crit *= (1 - 0.005 * max(0, d["logp"] - 2)
                  - 0.0005 * max(0, d["mw"] - 300))

    op = 1e4
    # Guard log10 input — for very-high-MW biologics (Lecanemab) or
    # high-LogP drugs with high loading, the modifications can push crit
    # toward zero or negative. Floor at op/1000 to keep margin physical.
    crit = max(crit, op / 1000.0)
    margin = math.log10(crit / op)
    score = min(100, max(0, margin * 30 + 30))
    return _hb(score, "",
                "log10(crit_shear/operating_shear) × 30; crit_shear softened "
                "by drug-load for lipid carriers (-4% per %loading >5%) "
                "and by drug LogP (-2% per LogP unit >4)",
                {"carrier": s["carrier"],
                  "crit_shear_modified": f"{crit:.1e}",
                  "drug_load_pct": s["drug_load"], "drug_LogP": d["logp"],
                  "margin_decades": round(margin,2)})


def P25(drug_bundle, dds_bundle, combo_bundle=None):
    """Extractables & Leachables — packaging compatibility."""
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    # Lipophilic drugs in PVC = bad. Carrier-LogP modifier.
    risk = 0
    if d["logp"] > 4 and s["carrier"] in ("liposome","solid_lipid"):
        risk = 40   # likely PVC incompatible
    elif d["logp"] > 3:
        risk = 20
    score = max(30, 100 - risk)
    return _hb(score, "",
                "100 - leachables risk by drug LogP × carrier",
                {"drug_logp": d["logp"], "carrier": s["carrier"]})


def P26(drug_bundle, dds_bundle, combo_bundle=None):
    """Microbiome-Excipient Interactions.

    Molecule-aware: gut microbiota metabolize drugs differently based on
    physicochemistry. Highly polar/anionic drugs are substrates for bacterial
    β-glucuronidases and azoreductases (Zimmermann 2019). Lipophilic drugs
    partition into bacterial membranes more readily.
    """
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    SUSCEPT = {"liposome":15, "plga":10, "polymer":15, "micelle":30,
                "dendrimer":35, "nanogel":50, "solid_lipid":15,
                "metallic":5, "exosome":40}
    susc = SUSCEPT.get(s["carrier"], 20)

    # Drug-side microbial-metabolism risk (continuous):
    # - Anionic drugs (carboxylates) = β-glucuronidase substrates
    # - Phenolic OH = sulfatase + reductase substrates
    # - Azo (N=N) = azoreductase substrate
    # - Very lipophilic = partitions into bacterial membrane
    drug_risk = 0.0
    drug_risk += 8 * d["f_ani"]                       # anionic fraction
    drug_risk += 5 * (d["hbd"] / 5)                   # H-bond donors (proxy for polar)
    drug_risk += max(0, (d["logp"] - 4)) * 3          # very lipophilic
    if "N=N" in d["smiles"]:    drug_risk += 12
    if "Oc1cc" in d["smiles"]:  drug_risk += 8         # phenol

    score = max(20, 100 - susc - drug_risk)
    return _hb(score, "",
                "100 - mean_microbiome_degradability(carrier) - "
                "drug-side risk (anionic-fraction, polar surface, lipophilicity, "
                "azo/phenol moieties)",
                {"carrier": s["carrier"], "carrier_susceptibility_pct": susc,
                  "drug_f_anionic": d["f_ani"], "drug_LogP": d["logp"],
                  "drug_HBD": d["hbd"], "drug_microbiome_risk": round(drug_risk,1)})


def P27(drug_bundle, dds_bundle, combo_bundle=None):
    """Lyophilization Cycle Optimizer."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Carrier Tg' lookup (lower = harder to lyophilize)
    TG_PRIME = {"liposome":-35, "plga":-20, "polymer":-25, "micelle":-30,
                  "dendrimer":-15, "metallic":-5, "solid_lipid":-25}
    tg = TG_PRIME.get(s["carrier"], -30)
    # Lower Tg' (more negative) → higher cake collapse risk
    risk = max(0, abs(tg) - 5) * 1.5
    score = max(20, 100 - risk)
    return _hb(score, "",
                "100 - (|Tg'| - 5) × 1.5",
                {"carrier": s["carrier"], "tg_prime_C": tg})


def P28(drug_bundle, dds_bundle, combo_bundle=None):
    """3D Printing Rheology."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    PRINT = {"polymer":85, "plga":80, "dendrimer":50, "liposome":40,
              "micelle":45, "nanogel":75, "solid_lipid":60, "metallic":30}
    score = PRINT.get(s["carrier"], 50)
    return _hb(score, "",
                "Carrier-specific printability index",
                {"carrier": s["carrier"]})


def P29(drug_bundle, dds_bundle, combo_bundle=None):
    """Biomimetic & Exosome Engineering — stealth from macrophages."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    BIO = {"exosome":85, "rbc-coated":80, "tumor-coated":75,
            "liposome":50, "plga":40, "polymer":45,
            "micelle":40, "dendrimer":35, "metallic":20, "solid_lipid":50}
    base = BIO.get(s["carrier"], 50)
    if s["peg"] >= 5: base = min(100, base + 15)
    return _hb(base, "",
                "Stealth-from-macrophage score; PEG ≥5% boost",
                {"carrier": s["carrier"], "peg_pct": s["peg"]})


def P30(drug_bundle, dds_bundle, combo_bundle=None):
    """QM/MM Stimuli-Responsive Cleavage."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # pH-trigger selectivity: bigger gap from blood pH (7.4) = better
    selectivity = abs(7.4 - s["ph_trig"])
    score = min(100, selectivity * 50)
    return _hb(score, "",
                "Score = 50 × |7.4 - pH_trigger|",
                {"ph_trigger": s["ph_trig"], "ph_selectivity": round(selectivity,1)})


def P31(drug_bundle, dds_bundle, combo_bundle=None):
    """Biodistribution — brain fraction estimate."""
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    # Brain fraction proxy: BBB perm × DDS-targeting × size suitability
    bbb = d["bbb"] / 100 if d["bbb"] > 0 else 0.05
    target = 2.0 if (s["ligand"] and s["ligand"] not in ("none","-","")) else 1.0
    size_match = _triangular(s["size"], 50, 150, 2, 0.5) / 100
    brain_pct = bbb * target * size_match * 100
    # Score: target ≥ 5% brain fraction → 100
    score = min(100, brain_pct / 0.05)
    return _hb(score, "",
                "brain% = BBB · ligand · size_match · 100; 100 if ≥5%",
                {"bbb_perm": bbb, "ligand_target_x": target,
                  "size_match": round(size_match, 2),
                  "brain_pct_estimate": round(brain_pct, 2)})


# P32 is C_translational — handled by translational engine

def P33(drug_bundle, dds_bundle, combo_bundle=None):
    """BBB Quantum Breaker — Trojan-Horse design."""
    dds = (combo_bundle or {}).get('_meta',{}).get('dds_row',{}) or {}
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    LIG = {"transferrin":95, "tf":95, "rvg29":90, "apoe":85,
            "lrp1":85, "ldlr":80, "insulin":75, "leptin":70,
            "lactoferrin":80, "":15, "none":15}
    lig_score = LIG.get(s["ligand"], 40)
    # Size compatibility (50-150 nm window)
    size_score = _triangular(s["size"], 50, 150, 2, 0.5)
    # Density modifier
    density = _safe(dds, "Surface_Ligand_Density_per_nm2", 0.5)
    density_factor = min(1.2, max(0.6, density))
    score = (0.6 * lig_score + 0.4 * size_score) * density_factor
    score = min(100, score)
    return _hb(score, "",
                "(0.6·ligand + 0.4·size) × density_factor",
                {"ligand": s["ligand"] or "(none)", "size_nm": s["size"],
                  "density": density},
                conf="HIGH" if score >= 70 else "MODERATE")


def P34(drug_bundle, dds_bundle, combo_bundle=None):
    """DNA Logic Gates."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    GATE = {"dna":95, "polymer":40, "liposome":15, "plga":20,
             "dendrimer":50, "exosome":25}
    return _hb(GATE.get(s["carrier"], 25),
                "",
                "DNA-based carriers score high",
                {"carrier": s["carrier"]})


def P35(drug_bundle, dds_bundle, combo_bundle=None):
    """Microgravity Formulation."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Smaller particles = lower Péclet = gravity-independent
    # Size 50-200 nm = gravity-irrelevant for most carriers
    score = 100 if s["size"] < 200 else max(50, 100 - (s["size"] - 200) * 0.3)
    return _hb(score, "",
                "Sedimentation-Péclet proxy; smaller = better",
                {"size_nm": s["size"]}, conf="LOW")


def P36(drug_bundle, dds_bundle, combo_bundle=None):
    """Geopolitical Supply-Chain Resilience."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Common materials = many suppliers = high score
    DIVERSITY = {"liposome":85, "plga":80, "polymer":75, "micelle":80,
                  "solid_lipid":75, "dendrimer":40, "metallic":50, "exosome":30}
    score = DIVERSITY.get(s["carrier"], 60)
    if s["ligand"] in ("rvg29","lactoferrin"): score -= 20   # specialty
    return _hb(max(20, score), "",
                "Supplier-diversity index by carrier + ligand",
                {"carrier": s["carrier"], "ligand": s["ligand"] or "(none)"})


def P37(drug_bundle, dds_bundle, combo_bundle=None):
    """Eco-Destructible Pharma."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    BIODEG = {"plga":95, "polymer":75, "liposome":90, "micelle":70,
                "solid_lipid":90, "metallic":5, "dendrimer":50, "nanogel":60}
    return _hb(BIODEG.get(s["carrier"], 60),
                "",
                "Biodegradability index by carrier class",
                {"carrier": s["carrier"]})


def P38(drug_bundle, dds_bundle, combo_bundle=None):
    """Glymphatic Clearance Trap."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Optimum 80-150 nm: too small = washed out, too big = stuck
    score = _triangular(s["size"], 80, 150, 1.2, 0.4)
    # Charge neutrality boost
    if abs(s["zeta"]) < 15: score = min(100, score * 1.1)
    return _hb(score, "",
                "Stokes-Einstein: optimum 80-150 nm",
                {"size_nm": s["size"], "abs_zeta": abs(s["zeta"])})


def P39(drug_bundle, dds_bundle, combo_bundle=None):
    """Microglial Activation & Neuroinflammation."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    risk = 0
    # Cationic = TLR4 trigger
    if s["zeta"] > 5: risk += 40
    elif s["zeta"] > 0: risk += 20
    # PEG protective
    if s["peg"] >= 5: risk -= 20
    # Carrier-class
    if s["carrier"] in ("metallic", "dendrimer"): risk += 15
    return _hb(max(20, 100 - risk),
                "",
                "100 - (cationic_charge + carrier_risk - PEG_protection)",
                {"zeta_mV": s["zeta"], "peg_pct": s["peg"], "carrier": s["carrier"]})


def P40(drug_bundle, dds_bundle, combo_bundle=None):
    """Intranasal-to-Brain Delivery."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Mucoadhesion ↔ carrier type
    MUCO = {"chitosan":95, "polymer":75, "nanogel":85,
             "liposome":40, "plga":50, "micelle":35,
             "solid_lipid":45, "dendrimer":40, "metallic":15}
    # Look at carrier and special ingredients
    score = MUCO.get(s["carrier"], 40)
    # Thermo-responsive boost
    if 32 <= s["phase_T"] <= 36: score = min(100, score + 15)
    return _hb(score, "",
                "Mucoadhesion + thermo-responsive boost",
                {"carrier": s["carrier"], "phase_T_C": s["phase_T"]})


def P41(drug_bundle, dds_bundle, combo_bundle=None):
    """Exosome Cargo Loading."""
    d, s, _ctx = _resolve_inputs(drug_bundle, dds_bundle, combo_bundle)
    if s["carrier"] != "exosome":
        return _hb(40, "",
                    "Not an exosome carrier — N/A",
                    {"carrier": s["carrier"]}, conf="LOW")
    # Sonication efficiency for given drug MW
    eff = max(30, 100 - abs(d["mw"] - 400) / 10)
    return _hb(eff, "",
                "Exosome-loading efficiency for drug MW",
                {"mw_da": d["mw"], "carrier": s["carrier"]})


def P42(drug_bundle, dds_bundle, combo_bundle=None):
    """Region-Specific Spatiotemporal Navigation."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Region-specific receptors
    SPATIAL = {"transferrin":70, "rvg29":85, "apoe":75,
                "lactoferrin":75, "insulin":80, "":25,"none":25}
    return _hb(SPATIAL.get(s["ligand"], 40),
                "",
                "Ligand-region specificity table",
                {"ligand": s["ligand"] or "(none)"})


def P43(drug_bundle, dds_bundle, combo_bundle=None):
    """FUS-Responsive Nanocarriers."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    FUS = {"microbubble":95, "gas-liposome":85, "liposome":40,
            "polymer":15, "plga":20, "micelle":15}
    return _hb(FUS.get(s["carrier"], 25),
                "",
                "FUS-response by carrier acoustic properties",
                {"carrier": s["carrier"]})


def P44(drug_bundle, dds_bundle, combo_bundle=None):
    """CNS-Specific PBPK Time-Machine."""
    d = _drug_specs_from_bundle(drug_bundle); s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Time-course: t10 (10% to brain) inversely proportional to perm
    bbb_perm = d["bbb"] / 100 if d["bbb"] > 0 else 0.02
    target_factor = 2.0 if (s["ligand"] and s["ligand"] not in ("none","-","")) else 1.0
    auc_brain = bbb_perm * target_factor * 24    # 24h window
    # Score for therapeutic AUC
    score = min(100, auc_brain * 200)
    return _hb(score, "",
                "AUC over 24h therapeutic window proxy",
                {"bbb_perm": bbb_perm, "target_factor": target_factor,
                  "auc_24h_proxy": round(auc_brain, 3)})


# P45 is C_translational

def P46(drug_bundle, dds_bundle, combo_bundle=None):
    """Polypharmacy & DDI Simulator — drug-only."""
    d = _drug_specs_from_bundle(drug_bundle)
    smi = d["smiles"]
    # Heuristic CYP-inhibition risk
    risk = 0
    # Imidazole / triazole groups → CYP3A4 inhibition
    if "n1cnc" in smi.lower(): risk += 35
    # Tertiary amine + lipophilic
    if d["logp"] > 4 and "N(C)C" in smi: risk += 25
    return _hb(max(40, 100 - risk),
                "",
                "CYP-inhibition heuristic from SMILES",
                {"cyp_inhibition_risk": risk})


# P47 is the ONLY Class B principle in the catalog. It's also runnable
# as a surrogate at the docking level — provide a fast surrogate here.
def P47(drug_bundle, dds_bundle, combo_bundle=None):
    """FEP+ surrogate: AutoDock Vina-like docking score proxy."""
    d = _drug_specs_from_bundle(drug_bundle); s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Surrogate ΔG estimate (kcal/mol) — Lipinski-ish
    if d["mw"] < 200: dg = -4.0
    elif d["mw"] < 500: dg = -7.5
    elif d["mw"] < 800: dg = -8.5
    else: dg = -6.0
    # LogP penalty if too lipophilic
    if d["logp"] > 5: dg += 1.5
    if d["logp"] < 0: dg += 1.0
    # Score: more negative ΔG = better binding
    score = min(100, abs(dg) * 12)
    return _hb(score, "",
                "Vina-like ΔG proxy from MW + LogP (deep mode runs full FEP+)",
                {"dg_proxy_kcal_mol": round(dg, 2)},
                conf="LOW",
                warnings=["Deep mode runs full FEP+ for Top-1"])


def P48(drug_bundle, dds_bundle, combo_bundle=None):
    """Off-Target Toxicity — 50-receptor panel surrogate."""
    d = _drug_specs_from_bundle(drug_bundle)
    smi = d["smiles"]
    risk = 0
    # hERG risk: basic amine + lipophilic
    if d["logp"] > 4 and ("N(" in smi or "[NH]" in smi): risk += 30
    # 5HT2B: indole + amine
    if "c1cc2c" in smi.lower() and "N" in smi: risk += 15
    # AhR: planar aromatic
    if smi.count("c") > 8 and d["logp"] > 5: risk += 20
    return _hb(max(30, 100 - risk),
                "",
                "50-receptor QSAR surrogate (hERG, 5HT2B, AhR risks)",
                {"off_target_risk": risk})


def P49(drug_bundle, dds_bundle, combo_bundle=None):
    """Organ-on-Chip Compatibility."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Stable, well-sized carriers do well in microfluidics
    score = 80 if 50 <= s["size"] <= 200 else 50
    if s["pdi"] > 0.4: score -= 20
    return _hb(max(30, score),
                "",
                "Microfluidic compatibility (size + PDI)",
                {"size_nm": s["size"], "pdi": s["pdi"]})


def P50(drug_bundle, dds_bundle, combo_bundle=None):
    """Cryo-Chain Thermal Excursion."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Phase-transition margin from -20C target
    margin = abs(-20 - s["phase_T"])
    score = min(100, margin * 1.3)
    return _hb(score, "",
                "Distance from -20°C phase transition × 1.3",
                {"phase_T_C": s["phase_T"], "margin_C": margin})


def P51(drug_bundle, dds_bundle, combo_bundle=None):
    """Terminal Sterilization Survivability."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    GAMMA = {"liposome":50, "plga":85, "polymer":80, "solid_lipid":75,
              "dendrimer":70, "metallic":95, "micelle":40, "nanogel":50}
    return _hb(GAMMA.get(s["carrier"], 60),
                "",
                "Carrier gamma-radiation survival (25 kGy)",
                {"carrier": s["carrier"]})


def P52(drug_bundle, dds_bundle, combo_bundle=None):
    """Continuous Manufacturing Digital Twin."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    CM = {"liposome":85, "plga":80, "polymer":75, "micelle":85,
            "solid_lipid":70, "exosome":35, "dendrimer":50, "metallic":75}
    return _hb(CM.get(s["carrier"], 60),
                "",
                "Continuous-process readiness by carrier",
                {"carrier": s["carrier"]})


def P53(drug_bundle, dds_bundle, combo_bundle=None):
    """Dark Data & Negative Results — failure-pattern matching."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Known-failure combos in CNS literature
    risk = 0
    if s["carrier"] == "metallic" and s["zeta"] > 0:
        risk = 50   # documented neurotoxicity
    elif s["size"] > 300:
        risk = 40   # documented poor brain delivery
    elif abs(s["zeta"]) > 35:
        risk = 30
    return _hb(max(30, 100 - risk),
                "",
                "Similarity-to-documented-failure",
                {"detected_risks": ["cationic_metallic" if s["carrier"]=="metallic" and s["zeta"]>0 else None,
                                     "oversize" if s["size"]>300 else None,
                                     "extreme_charge" if abs(s["zeta"])>35 else None]})


def P54(drug_bundle, dds_bundle, combo_bundle=None):
    """Pharmacogenomic-Guided Targeting."""
    d = _drug_specs_from_bundle(drug_bundle)
    # Heuristic from molecule class
    if d["mclass"] == "small_molecule": score = 70   # CYP variants matter
    elif d["mclass"] in ("biologic","monoclonal_antibody","mab"): score = 90   # less CYP
    else: score = 75
    return _hb(score, "",
                "Class-based pharmacogenomic applicability",
                {"molecule_class": d["mclass"]})


# P55, P56 are C_translational

def P57(drug_bundle, dds_bundle, combo_bundle=None):
    """Microfluidics & LNP Synthesis."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    if s["carrier"] in ("liposome","solid_lipid","micelle","plga"):
        score = 90 if 50 <= s["size"] <= 150 else 70
    else: score = 50
    return _hb(score, "",
                "Microfluidic readiness for size 50-150 nm",
                {"carrier": s["carrier"], "size_nm": s["size"]})


def P58(drug_bundle, dds_bundle, combo_bundle=None):
    """Impurity Cascade Predictor."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Higher metal-residue carriers → worse score
    METAL_RISK = {"metallic":60, "plga":15, "polymer":20, "liposome":10,
                    "dendrimer":25, "micelle":15, "solid_lipid":10}
    risk = METAL_RISK.get(s["carrier"], 20)
    return _hb(max(30, 100 - risk),
                "",
                "Carrier residual-metals impurity profile",
                {"carrier": s["carrier"], "metal_risk": risk})


def P59(drug_bundle, dds_bundle, combo_bundle=None):
    """4D Shape-Shifting Carriers."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    score = 30   # baseline
    if s["rel_kin"] in ("ph-responsive","thermo"): score += 50
    if s["carrier"] == "polymer" and s["rel_kin"] == "ph-responsive": score += 20
    return _hb(min(100, score),
                "",
                "Stimuli-responsive bonus by release kinetics",
                {"release_kinetics": s["rel_kin"]})


def P60(drug_bundle, dds_bundle, combo_bundle=None):
    """Swarm Nanorobotics Intelligence."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Most current DDS = no swarm = baseline
    return _hb(15 if s["carrier"] != "swarm" else 80,
                "",
                "Swarm capability (most carriers: no)",
                {"carrier": s["carrier"]}, conf="LOW")


def P61(drug_bundle, dds_bundle, combo_bundle=None):
    """Synthetic Clinical Trials & Virtual Humans."""
    d = _drug_specs_from_bundle(drug_bundle); s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # % responders proxy = BBB-adjusted potency × DDS targeting
    bbb = d["bbb"] / 100 if d["bbb"] > 0 else 0.05
    target = 1.5 if (s["ligand"] and s["ligand"] not in ("none","-","")) else 1.0
    responders = min(95, 30 + bbb * 800 * target)
    return _hb(responders, "",
                "Virtual-cohort responder fraction",
                {"bbb_perm": bbb, "ligand_target_x": target},
                value=round(responders, 0))


def P62(drug_bundle, dds_bundle, combo_bundle=None):
    """Biobetter / Supergeneric — novelty distance."""
    s = _dds_specs_from_bundle(dds_bundle, dds_row=(combo_bundle or {}).get("_meta",{}).get("dds_row",{}))
    # Combos not in standard CNS literature get higher score
    NOVELTY = {("transferrin","liposome"):40, ("rvg29","plga"):50,
                 ("apoe","liposome"):40, ("","liposome"):20,
                 ("","plga"):25, ("lactoferrin","solid_lipid"):75,
                 ("rvg29","liposome"):60}
    score = NOVELTY.get((s["ligand"], s["carrier"]), 65)
    return _hb(score, "",
                "Novelty distance from on-market CNS DDS",
                {"carrier": s["carrier"], "ligand": s["ligand"] or "(none)"},
                conf="LOW")


# ──────────────────────────────────────────────────────────────────────────
# Master dispatcher
# ──────────────────────────────────────────────────────────────────────────
SURROGATE_FUNCTIONS = {
    "P01":P01, "P02":P02, "P03":P03, "P04":P04, "P05":P05,
    "P06":P06, "P07":P07, "P08":P08, "P09":P09, "P10":P10,
    "P11":P11, "P12":P12, "P13":P13, "P14":P14, "P15":P15,
    "P16":P16, "P17":P17, "P18":P18, "P19":P19, "P20":P20,
    "P22":P22, "P23":P23, "P24":P24, "P25":P25, "P26":P26,
    "P27":P27, "P28":P28, "P29":P29, "P30":P30, "P31":P31,
    "P33":P33, "P34":P34, "P35":P35, "P36":P36, "P37":P37,
    "P38":P38, "P39":P39, "P40":P40, "P41":P41, "P42":P42,
    "P43":P43, "P44":P44, "P46":P46, "P47":P47, "P48":P48,
    "P49":P49, "P50":P50, "P51":P51, "P52":P52, "P53":P53,
    "P54":P54, "P57":P57, "P58":P58, "P59":P59, "P60":P60,
    "P61":P61, "P62":P62,
}
# ↑ 57 functions. P21, P32, P45, P55, P56 are translational (5).
# P47 has both surrogate (here) and deep version (deep_engine).
assert len(SURROGATE_FUNCTIONS) == 57, \
    f"Expected 57 surrogate functions, got {len(SURROGATE_FUNCTIONS)}"


def evaluate_all_principles_for_dds(drug_bundle: dict, dds_bundle: dict,
                                       combo_bundle: dict) -> dict[str, dict]:
    """Run ALL Class A surrogate functions for a single DDS.

    BUNDLE-ONLY signature (Phase 5, 2026-04-30): no mol_profile dict, no
    raw dds_dict. Surrogate functions receive `(drug_bundle, dds_bundle,
    combo_bundle)` and use _resolve_inputs() to extract values with full
    provenance.

    Args:
        drug_bundle:  output of cerebro_resolved_bundles.resolve_drug_bundle()
        dds_bundle:   output of cerebro_resolved_bundles.resolve_dds_bundle()
        combo_bundle: output of cerebro_resolved_bundles.resolve_combo_bundle()
                        — must carry _meta.dds_row with the Excel formulation row

    Returns:
        dict mapping principle_id → {value, score, method, ref, conf, raw, warnings}
    """
    out: dict[str, dict] = {}
    for pid, fn in SURROGATE_FUNCTIONS.items():
        try:
            # Surrogate functions accept (arg1, arg2, arg3) via _resolve_inputs
            # which detects bundles vs legacy dicts. With bundles, _resolve_inputs
            # extracts the standard d/s spec dicts including _provenance.
            out[pid] = fn(drug_bundle, dds_bundle, combo_bundle)
        except Exception as e:
            log.warning(f"[SURROGATE] {pid} failed: {e}")
            out[pid] = {"value": 0, "score": 0,
                         "method": "failed", "reference": "—",
                         "confidence": "FAILED",
                         "raw": {"error": str(e)},
                         "warnings": [f"Function failed: {e}"]}
    return out
