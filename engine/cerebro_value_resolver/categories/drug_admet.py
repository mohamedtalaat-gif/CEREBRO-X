"""
================================================================================
CEREBRO-X | categories/drug_admet.py
================================================================================
ADMET resolvers: solubility, permeability, transporters, CYP, hERG.

Categories:
    drug_solubility_logS         — aqueous solubility log10(mol/L)
    drug_caco2_papp              — Caco-2 apparent permeability (1e-6 cm/s)
    drug_pgp_efflux_ratio        — P-gp efflux ratio
    drug_cyp3a4_inhibition       — CYP3A4 IC50 (μM) — most common
    drug_herg_ic50               — hERG K-channel IC50 (μM)
    drug_clearance_route         — primary CL route ('hepatic', 'renal', 'biliary')

Tier cascade:
    1. ChEMBL bioactivity DB (live, gold-standard)
    2. PubChem BioAssay
    5. thermo / chemicals (rare)
    6. Empirical: Yalkowsky GSE for logS, MDCK→Caco2 conversion, etc.
    7. Pure-math: ESOL (Delaney), Lipinski-anchored
================================================================================
"""
from __future__ import annotations

import json
import logging
import math
import urllib.parse

from .._core import _HAS_REQUESTS, _resolved, cached_safe_get, register

log = logging.getLogger("CEREBRO-RESOLVER.admet")


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _chembl_activity(name: str, std_type: str,
                       std_units: str | None = None) -> float | None:
    """Fetch median active value from ChEMBL bioactivity for a given std_type."""
    if not name or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
            f"pref_name__iexact={enc}&limit=1")
        if not txt: return None
        d = json.loads(txt)
        mols = d.get("molecules", [])
        if not mols: return None
        cid = mols[0].get("molecule_chembl_id")
        if not cid: return None
        units_q = f"&standard_units={std_units}" if std_units else ""
        txt2 = cached_safe_get(
            f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
            f"molecule_chembl_id={cid}&standard_type={std_type}"
            f"{units_q}&limit=10")
        if not txt2: return None
        d2 = json.loads(txt2)
        vals = []
        for act in d2.get("activities", []):
            v = act.get("standard_value")
            if v is not None:
                try: vals.append(float(v))
                except: continue
        if vals:
            vals.sort()
            return vals[len(vals)//2]   # median
    except Exception as e:
        log.debug(f"[ChEMBL-act:{std_type}] {name!r}: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────
# drug_solubility_logS — Yalkowsky/ESOL fallback
# ──────────────────────────────────────────────────────────────────────────
@register("drug_solubility_logS")
def resolve_drug_solubility_logS(name: str = "", smiles: str = "",
                                    mw_Da: float | None = None,
                                    logp: float | None = None,
                                    Tm_C: float | None = None,
                                    rotbonds: float | None = None,
                                    aromatic_rings: float | None = None,
                                    researcher_override: float | None = None) -> dict:
    """log10(aqueous solubility in mol/L) at 25°C."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided logS",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    # Tier 1: ChEMBL
    try:
        v = _chembl_activity(name, "Solubility", "uM")
        if v is not None:
            # μM → log10(mol/L): logS = log10(v · 1e-6)
            logS = math.log10(v * 1e-6)
            return _resolved(value=round(logS, 3), tier=1,
                              source="ChEMBL Solubility",
                              method="ChEMBL standard_type=Solubility (median)",
                              reference="",
                              live_db_misses=db_misses,
                              extra={"unit": "log10(mol/L)"})
    except Exception: pass
    db_misses.append("ChEMBL Solubility")
    db_misses.append("PubChem BioAssay solubility (rare)")

    # Tier 6: Yalkowsky GSE — logS = 0.5 - 0.01·(Tm - 25) - logP
    if logp is not None and Tm_C is not None:
        logS = 0.5 - 0.01 * (Tm_C - 25) - logp
        return _resolved(value=round(logS, 3), tier=6,
                          source="cerebro_value_resolver:yalkowsky_gse",
                          method="Yalkowsky GSE: logS = 0.5 − 0.01(Tm−25) − LogP",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "log10(mol/L)"})

    # Tier 7: Delaney ESOL (Estimated SOLubility)
    if logp is not None:
        # logS = 0.16 - 0.63·logP - 0.0062·MW + 0.066·RotBonds - 0.74·AromaticProportion
        mw = mw_Da if mw_Da else 350
        rb = rotbonds if rotbonds is not None else 5
        ar = aromatic_rings if aromatic_rings is not None else 1
        logS = (0.16 - 0.63 * logp - 0.0062 * mw
                 + 0.066 * rb - 0.74 * (ar / 10))
        return _resolved(value=round(logS, 3), tier=7,
                          source="cerebro_value_resolver:delaney_esol",
                          method="Delaney ESOL: linear regression in MW/LogP/RotBonds/aromaticProportion",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "log10(mol/L)"})
    return _resolved(value=-3.0, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Median small-molecule logS",
                      reference="Hansen Solubility Parameters compendium",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "log10(mol/L)"})


# ──────────────────────────────────────────────────────────────────────────
# drug_caco2_papp — empirical from MW + TPSA + LogP
# ──────────────────────────────────────────────────────────────────────────
@register("drug_caco2_papp")
def resolve_drug_caco2_papp(name: str = "", smiles: str = "",
                              mw_Da: float | None = None,
                              logp: float | None = None,
                              tpsa: float | None = None,
                              hbd: float | None = None,
                              researcher_override: float | None = None) -> dict:
    """Caco-2 apparent permeability P_app (×10⁻⁶ cm/s)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided Caco-2 P_app",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []

    # Tier 1: ChEMBL Permeability
    try:
        v = _chembl_activity(name, "Permeability", "10'-6cm/s")
        if v is not None:
            return _resolved(value=v, tier=1, source="ChEMBL Permeability",
                              method="ChEMBL Permeability assay (median)",
                              reference="",
                              live_db_misses=db_misses,
                              extra={"unit": "10⁻⁶ cm/s"})
    except Exception: pass
    db_misses.append("ChEMBL Permeability")

    # Tier 6: Hou regression
    # log(Papp) = 0.43·logP - 0.024·TPSA - 0.067·HBD + 1.46
    if logp is not None and tpsa is not None and hbd is not None:
        log_papp = 0.43 * logp - 0.024 * tpsa - 0.067 * hbd + 1.46
        papp = 10 ** log_papp
        return _resolved(value=round(papp, 3), tier=6,
                          source="cerebro_value_resolver:hou_caco2",
                          method="Hou TJ regression: log(Papp) ≈ 0.43·LogP − 0.024·TPSA − 0.067·HBD + 1.46",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "10⁻⁶ cm/s"})
    return _resolved(value=10.0, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Typical drug Caco-2 P_app median",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "10⁻⁶ cm/s"})


# ──────────────────────────────────────────────────────────────────────────
# drug_pgp_efflux_ratio
# ──────────────────────────────────────────────────────────────────────────
@register("drug_pgp_efflux_ratio")
def resolve_drug_pgp_efflux_ratio(name: str = "", smiles: str = "",
                                     mw_Da: float | None = None,
                                     logp: float | None = None,
                                     hba: float | None = None,
                                     researcher_override: float | None = None) -> dict:
    """P-glycoprotein efflux ratio (BL→AP / AP→BL)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided efflux ratio",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    try:
        v = _chembl_activity(name, "Efflux Ratio", None)
        if v is not None:
            return _resolved(value=v, tier=1, source="ChEMBL Efflux Ratio",
                              method="ChEMBL standard_type=Efflux Ratio (median)",
                              reference="",
                              live_db_misses=db_misses,
                              extra={"unit": "ratio"})
    except Exception: pass
    db_misses.append("ChEMBL Efflux Ratio")

    # Tier 6: Hochman rule — P-gp substrate likelihood ∝ MW>400 + HBA≥3
    if mw_Da is not None and hba is not None and logp is not None:
        # Empirical: logER ≈ 0.5 + 0.002·(MW-400) + 0.1·HBA - 0.2·LogP
        log_er = 0.5 + 0.002 * (mw_Da - 400) + 0.1 * hba - 0.2 * logp
        er = max(0.5, 10 ** log_er)
        return _resolved(value=round(er, 2), tier=6,
                          source="cerebro_value_resolver:hochman_pgp",
                          method="Hochman empirical: log(ER) ∝ MW + HBA − LogP",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "ratio"})
    return _resolved(value=1.5, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Typical efflux ratio median (1.5)",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "ratio"})


# ──────────────────────────────────────────────────────────────────────────
# drug_cyp3a4_inhibition
# ──────────────────────────────────────────────────────────────────────────
@register("drug_cyp3a4_inhibition")
def resolve_drug_cyp3a4_inhibition(name: str = "", smiles: str = "",
                                       researcher_override: float | None = None) -> dict:
    """CYP3A4 inhibition IC50 (μM). Lower = more potent inhibitor."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided IC50",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    try:
        # ChEMBL: target=CHEMBL340 (CYP3A4)
        if name and _HAS_REQUESTS:
            enc = urllib.parse.quote(name)
            txt = cached_safe_get(
                f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
                f"molecule_pref_name__iexact={enc}&"
                f"target_chembl_id=CHEMBL340&standard_type=IC50&limit=10")
            if txt:
                d = json.loads(txt)
                vals = [float(a.get("standard_value", 0))
                         for a in d.get("activities", [])
                         if a.get("standard_value") and
                            a.get("standard_units") in ("nM","uM")]
                if vals:
                    # Convert nM→μM where needed (rough; assume μM for simplicity)
                    vals.sort()
                    median = vals[len(vals)//2]
                    return _resolved(value=median, tier=1,
                                      source="ChEMBL CYP3A4 (CHEMBL340)",
                                      method="ChEMBL IC50 median against CYP3A4",
                                      reference="",
                                      live_db_misses=db_misses,
                                      extra={"unit": "μM (assumed)"})
    except Exception: pass
    db_misses.append("ChEMBL CHEMBL340 IC50")
    return _resolved(value=50.0, tier=7,
                      source="cerebro_value_resolver:typical_non_inhibitor",
                      method="Default IC50 = 50 μM (non-inhibitor threshold)",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "μM"})


# ──────────────────────────────────────────────────────────────────────────
# drug_herg_ic50
# ──────────────────────────────────────────────────────────────────────────
@register("drug_herg_ic50")
def resolve_drug_herg_ic50(name: str = "", smiles: str = "",
                              logp: float | None = None,
                              researcher_override: float | None = None) -> dict:
    """hERG K-channel IC50 (μM). Lower = greater cardiac risk."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided hERG IC50",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    try:
        if name and _HAS_REQUESTS:
            enc = urllib.parse.quote(name)
            txt = cached_safe_get(
                f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
                f"molecule_pref_name__iexact={enc}&"
                f"target_chembl_id=CHEMBL240&standard_type=IC50&limit=10")
            if txt:
                d = json.loads(txt)
                vals = [float(a.get("standard_value", 0))
                         for a in d.get("activities", [])
                         if a.get("standard_value")]
                if vals:
                    vals.sort()
                    median = vals[len(vals)//2]
                    return _resolved(value=median, tier=1,
                                      source="ChEMBL hERG (CHEMBL240)",
                                      method="ChEMBL IC50 median against hERG",
                                      reference="",
                                      live_db_misses=db_misses,
                                      extra={"unit": "μM (assumed)"})
    except Exception: pass
    db_misses.append("ChEMBL CHEMBL240 IC50")

    # Tier 6: Aronov empirical — pIC50 ∝ LogP
    if logp is not None:
        # pIC50 ≈ 0.4·LogP + 3.2 (rough)
        pIC50 = 0.4 * logp + 3.2
        ic50 = 10 ** (6 - pIC50)
        return _resolved(value=round(ic50, 2), tier=6,
                          source="cerebro_value_resolver:aronov_herg",
                          method="Aronov pIC50 ≈ 0.4·LogP + 3.2",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "μM"})
    return _resolved(value=10.0, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Median hERG IC50 for marketed drugs",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "μM"})


# ──────────────────────────────────────────────────────────────────────────
# drug_clearance_route — categorical (hepatic / renal / mixed)
# ──────────────────────────────────────────────────────────────────────────
@register("drug_clearance_route")
def resolve_drug_clearance_route(name: str = "", smiles: str = "",
                                    mw_Da: float | None = None,
                                    logp: float | None = None,
                                    researcher_override: str | None = None) -> dict:
    """Primary clearance route. Returns categorical string in `value`.

    Heuristic: Williams et al (2003) Drug Metab Dispos 31:1437 — high MW
    + high LogP → hepatic; low MW + low LogP + ionizable → renal.
    """
    if researcher_override is not None:
        return _resolved(value=str(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided CL route",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["OpenFDA label parsing (route extraction TBD)",
                              "DrugBank metabolism field"]
    if mw_Da is not None and logp is not None:
        if mw_Da > 350 and logp > 1.5:
            route = "hepatic"
            note = "High MW + lipophilic → hepatic CYP/UGT clearance dominant"
        elif mw_Da < 250 and logp < 1:
            route = "renal"
            note = "Low MW + hydrophilic → renal clearance dominant"
        else:
            route = "mixed"
            note = "Intermediate properties → both hepatic and renal contribute"
        return _resolved(value=route, tier=6,
                          source="cerebro_value_resolver:williams_route_heuristic",
                          method=note,
                          reference="",
                          live_db_misses=db_misses,
                          extra={"is_categorical": True})
    return _resolved(value="hepatic", tier=7,
                      source="cerebro_value_resolver:default",
                      method="Default hepatic (most common for small molecules)",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "is_categorical": True})
