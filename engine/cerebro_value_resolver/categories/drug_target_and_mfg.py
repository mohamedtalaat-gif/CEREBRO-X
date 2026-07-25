"""
================================================================================
CEREBRO-X | categories/drug_target_and_mfg.py
================================================================================
Drug-target binding parameters + carrier manufacturing parameters.

Categories:
    drug_target_kd               — dissociation constant Kd (nM)
    drug_target_ic50             — half-maximal inhibitory IC50 (nM)
    drug_target_ki               — inhibition constant Ki (nM)
    drug_loading_capacity_pct    — theoretical maximum drug load
    material_pdi                 — polydispersity index (default for carrier)
    material_porosity            — typical porosity for carrier type
================================================================================
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from .._core import _HAS_REQUESTS, _resolved, cached_safe_get, register

log = logging.getLogger("CEREBRO-RESOLVER.target_mfg")


def _chembl_target_activity(name: str, target_uniprot: str | None,
                                std_type: str = "IC50") -> float | None:
    """ChEMBL bioactivity query against a specific UniProt target."""
    if not (name and _HAS_REQUESTS): return None
    try:
        enc = urllib.parse.quote(name)
        # First find the molecule
        txt = cached_safe_get(
            f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
            f"pref_name__iexact={enc}&limit=1")
        if not txt: return None
        d = json.loads(txt)
        mols = d.get("molecules", [])
        if not mols: return None
        cid = mols[0].get("molecule_chembl_id")
        if not cid: return None
        target_q = f"&target_chembl_id={target_uniprot}" if target_uniprot else ""
        txt2 = cached_safe_get(
            f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
            f"molecule_chembl_id={cid}&standard_type={std_type}"
            f"{target_q}&limit=20")
        if not txt2: return None
        d2 = json.loads(txt2)
        vals = []
        for act in d2.get("activities", []):
            v = act.get("standard_value")
            u = act.get("standard_units")
            if v is not None and u in ("nM", "uM"):
                try:
                    val = float(v)
                    if u == "uM": val *= 1000     # μM → nM
                    vals.append(val)
                except: continue
        if vals:
            vals.sort()
            return vals[len(vals)//2]   # median in nM
    except Exception as e:
        log.debug(f"[ChEMBL-target:{std_type}] {name!r}: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────
# drug_target_kd / drug_target_ic50 / drug_target_ki
# ──────────────────────────────────────────────────────────────────────────
def _build_target_resolver(category: str, std_type: str, default_nM: float):
    @register(category)
    def resolver(name: str = "", smiles: str = "",
                  target_chembl: str | None = None,
                  researcher_override: float | None = None) -> dict:
        if researcher_override is not None:
            return _resolved(value=float(researcher_override), tier=0,
                              source="researcher_override",
                              method=f"User-provided {std_type}",
                              reference="Researcher input", live_db_misses=[])
        db_misses: list[str] = []
        try:
            v = _chembl_target_activity(name, target_chembl, std_type)
            if v is not None:
                return _resolved(value=v, tier=1,
                                  source=f"ChEMBL {std_type}",
                                  method=f"Median ChEMBL {std_type} against "
                                          f"{target_chembl or 'any target'}",
                                  reference="Mendez D et al (2019) NAR 47:D930",
                                  live_db_misses=db_misses,
                                  extra={"unit": "nM"})
        except Exception: pass
        db_misses.append(f"ChEMBL {std_type}")
        db_misses.append("BindingDB (no public REST)")
        return _resolved(value=default_nM, tier=7,
                          source="cerebro_value_resolver:typical_drug",
                          method=f"Typical drug {std_type} median",
                          reference="ChEMBL statistical summary",
                          live_db_misses=db_misses,
                          extra={"confidence":"LOW", "unit": "nM"})
    resolver.__name__ = f"resolve_{category}"
    return resolver


_build_target_resolver("drug_target_kd",   "Kd",    100.0)
_build_target_resolver("drug_target_ic50", "IC50",   50.0)
_build_target_resolver("drug_target_ki",   "Ki",     50.0)


# ──────────────────────────────────────────────────────────────────────────
# drug_loading_capacity_pct — Bunjes (2010) rule of thumb
# ──────────────────────────────────────────────────────────────────────────
@register("drug_loading_capacity_pct")
def resolve_drug_loading_capacity_pct(carrier: str = "",
                                          logp: float | None = None,
                                          mw_Da: float | None = None,
                                          researcher_override: float | None = None) -> dict:
    """Theoretical max drug loading (% w/w) for a carrier-drug combination."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided drug loading",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []

    carrier_low = (carrier or "").lower()

    # Tier 6: Bunjes (2010) — for lipid carriers, max load ≈ LogP × 2 (% w/w)
    if logp is not None and carrier_low in ("liposome","solid_lipid","lipid","micelle"):
        max_load = max(2.0, min(40.0, logp * 2.0))
        return _resolved(value=round(max_load, 1), tier=6,
                          source="cerebro_value_resolver:bunjes_lipid_load",
                          method="Bunjes rule: max_load(%) ≈ LogP × 2 for lipid carriers",
                          reference="Bunjes H (2010) Curr Opin Colloid Interface Sci 15:80",
                          live_db_misses=db_misses,
                          extra={"unit": "% w/w"})

    # Polymer carriers: typical 5-20%, modulated by LogP and MW
    if carrier_low in ("plga","polymer","pcl","pla","chitosan","alginate"):
        load = 10.0
        if logp is not None: load += min(8, logp * 1.5)
        if mw_Da is not None and mw_Da < 400: load += 3
        return _resolved(value=round(min(35, load), 1), tier=6,
                          source="cerebro_value_resolver:polymer_load_heuristic",
                          method="Polymer carrier loading heuristic from LogP + MW",
                          reference="Soppimath KS et al (2001) J Control Release 70:1",
                          live_db_misses=db_misses,
                          extra={"unit": "% w/w"})

    # Default: 8% (median across carriers)
    return _resolved(value=8.0, tier=7,
                      source="cerebro_value_resolver:carrier_class_median",
                      method="Median drug loading across carrier classes",
                      reference="Allen TM & Cullis PR (2013) Adv Drug Deliv Rev 65:36",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "% w/w"})


# ──────────────────────────────────────────────────────────────────────────
# material_pdi — polydispersity index defaults
# ──────────────────────────────────────────────────────────────────────────
PDI_DEFAULTS = {
    "liposome":   0.10,
    "plga":       0.20,
    "polymer":    0.20,
    "micelle":    0.15,
    "dendrimer":  0.05,    # monodisperse
    "metallic":   0.12,
    "solid_lipid":0.25,
    "exosome":    0.30,    # naturally heterogeneous
    "nanogel":    0.18,
}


@register("material_pdi")
def resolve_material_pdi(carrier: str = "",
                            researcher_override: float | None = None) -> dict:
    """Default polydispersity index for a carrier class."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided PDI",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["No live DB for theoretical PDI"]
    key = (carrier or "").lower()
    pdi = PDI_DEFAULTS.get(key, 0.20)
    return _resolved(value=pdi, tier=7,
                      source="cerebro_value_resolver:carrier_class_PDI",
                      method=f"Carrier-class typical PDI for {key}",
                      reference="Allen TM & Cullis PR (2013) Adv Drug Deliv Rev 65:36",
                      live_db_misses=db_misses,
                      extra={"unit": "dimensionless"})


# ──────────────────────────────────────────────────────────────────────────
# material_porosity — typical for carrier
# ──────────────────────────────────────────────────────────────────────────
POROSITY_DEFAULTS = {
    "liposome":   0.0,     # closed bilayer
    "plga":       0.30,    # nanoporous from solvent evap
    "polymer":    0.25,
    "micelle":    0.0,
    "dendrimer":  0.10,
    "metallic":   0.0,
    "solid_lipid":0.05,
    "nanogel":    0.85,    # highly porous
    "mof":        0.70,
    "silica":     0.50,
}


@register("material_porosity")
def resolve_material_porosity(carrier: str = "",
                                 researcher_override: float | None = None) -> dict:
    """Carrier porosity (volume fraction)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided porosity",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    key = (carrier or "").lower()
    p = POROSITY_DEFAULTS.get(key, 0.10)
    return _resolved(value=p, tier=7,
                      source="cerebro_value_resolver:carrier_class_porosity",
                      method=f"Carrier-class typical porosity for {key}",
                      reference="Brunauer S, Emmett PH, Teller E (1938) J Am Chem Soc 60:309",
                      live_db_misses=db_misses,
                      extra={"unit": "volume fraction"})
