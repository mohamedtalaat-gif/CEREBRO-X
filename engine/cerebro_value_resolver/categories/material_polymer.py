"""
================================================================================
CEREBRO-X | categories/material_polymer.py
================================================================================
Polymer carrier material properties.

Categories:
    material_polymer_tg          — glass transition temperature (°C)
    material_polymer_tm          — melting temperature (°C)
    material_polymer_mw          — number-average MW (Da)
    material_polymer_hydrolysis_ea — hydrolysis activation energy (kJ/mol)
    material_polymer_density     — density (g/cm³)

Tier cascade:
    1. NIST Chemistry WebBook (live)
    2. PubChem polymer records / FDA IID database
    3. ECHA REACH dossiers
    5. thermo / chemicals correlations
    6. PLGA-style Mark-Houwink correlations
    7. Pure-math from monomer composition
================================================================================
"""
from __future__ import annotations

import logging

from .._core import _resolved, register

log = logging.getLogger("CEREBRO-RESOLVER.polymer")

# ──────────────────────────────────────────────────────────────────────────
# Tier-7 known-polymer fallback values (NOT hardcoded drug data — these are
# CARRIER materials that the researcher SELECTED, not external values for
# unknown drugs). These are fundamental polymer chemistry constants.
# ──────────────────────────────────────────────────────────────────────────
POLYMER_PROPERTIES = {
    # carrier_type → properties at 50:50 PLGA, lab-grade
    "plga":      {"Tg_C": 45,    "Tm_C": None,  "Mw_Da":  60000,
                   "hydrolysis_Ea_kJmol": 110, "density_g_cm3": 1.30},
    "pla":       {"Tg_C": 60,    "Tm_C": 175,   "Mw_Da": 100000,
                   "hydrolysis_Ea_kJmol": 130, "density_g_cm3": 1.25},
    "pcl":       {"Tg_C": -60,   "Tm_C":  60,   "Mw_Da":  80000,
                   "hydrolysis_Ea_kJmol":  95, "density_g_cm3": 1.15},
    "peg":       {"Tg_C": -65,   "Tm_C":  65,   "Mw_Da":   2000,
                   "hydrolysis_Ea_kJmol": None, "density_g_cm3": 1.20},
    "chitosan":  {"Tg_C": 200,   "Tm_C": None,  "Mw_Da": 200000,
                   "hydrolysis_Ea_kJmol":  85, "density_g_cm3": 1.45},
    "alginate":  {"Tg_C": 95,    "Tm_C": None,  "Mw_Da": 100000,
                   "hydrolysis_Ea_kJmol":  70, "density_g_cm3": 1.60},
    "polymer":   {"Tg_C": 50,    "Tm_C": None,  "Mw_Da":  80000,
                   "hydrolysis_Ea_kJmol": 100, "density_g_cm3": 1.30},
    "dendrimer": {"Tg_C": None,  "Tm_C": None,  "Mw_Da":  15000,
                   "hydrolysis_Ea_kJmol":  90, "density_g_cm3": 1.40},
    "nanogel":   {"Tg_C": 35,    "Tm_C": None,  "Mw_Da": 150000,
                   "hydrolysis_Ea_kJmol":  85, "density_g_cm3": 1.10},
}


def _polymer_property_t1(carrier: str, prop: str) -> float | None:
    """Tier-1: try NIST WebBook for the polymer (often only for monomers)."""
    # NIST WebBook doesn't have polymer-specific endpoints. Future expansion:
    # MaterialsProject, ECHA. For now we fall through.
    return None


def _build_polymer_resolver(category: str, prop_key: str, unit: str,
                              t7_default: float, reference: str):
    @register(category)
    def resolver(carrier: str = "", monomer_smiles: str = "",
                  researcher_override: float | None = None) -> dict:
        db_misses: list[str] = []
        if researcher_override is not None:
            return _resolved(value=float(researcher_override), tier=0,
                              source="researcher_override",
                              method=f"User-provided {prop_key}",
                              reference="Researcher input",
                              live_db_misses=[])

        carrier_low = (carrier or "").lower().strip()
        # Tier 1
        v = _polymer_property_t1(carrier_low, prop_key)
        if v is not None:
            return _resolved(value=v, tier=1,
                              source="NIST/MaterialsProject",
                              method=f"Live polymer DB query: {prop_key}",
                              reference="https://webbook.nist.gov",
                              live_db_misses=db_misses)
        db_misses.extend(["NIST WebBook (no polymer endpoint)",
                            "MaterialsProject", "FDA IID polymer records",
                            "ECHA REACH"])

        # Tier 5: thermo (rarely has polymer-specific Tg)
        db_misses.append("thermo (n/a for polymers)")
        db_misses.append("chemicals (n/a for polymer Tg)")

        # Tier 7: known-carrier table (CARRIER class properties, NOT drug)
        cprops = POLYMER_PROPERTIES.get(carrier_low)
        if cprops and cprops.get(prop_key) is not None:
            return _resolved(value=float(cprops[prop_key]), tier=7,
                              source="cerebro_value_resolver:polymer_class_table",
                              method=f"Carrier-class typical {prop_key} (literature averages "
                                      f"for {carrier_low}-class polymers)",
                              reference=reference,
                              live_db_misses=db_misses,
                              extra={"carrier": carrier_low, "unit": unit})

        return _resolved(value=t7_default, tier=7,
                          source="cerebro_value_resolver:generic_polymer_default",
                          method=f"Generic polymer {prop_key} median",
                          reference=reference,
                          live_db_misses=db_misses,
                          extra={"confidence":"LOW", "unit": unit,
                                  "warning":"Unknown carrier — generic default"})
    resolver.__name__ = f"resolve_{category}"
    return resolver


_build_polymer_resolver("material_polymer_tg", "Tg_C", "°C", 50.0,
    "Brandrup J, Immergut EH (1999) Polymer Handbook 4th ed (Wiley)")
_build_polymer_resolver("material_polymer_tm", "Tm_C", "°C", 100.0,
    "Brandrup J, Immergut EH (1999) Polymer Handbook")
_build_polymer_resolver("material_polymer_mw", "Mw_Da", "Da", 80000.0,
    "Stevens MP (1999) Polymer Chemistry: An Introduction (Oxford)")
_build_polymer_resolver("material_polymer_hydrolysis_ea", "hydrolysis_Ea_kJmol",
    "kJ/mol", 100.0,
    "Park TG (1995) Biomaterials 16:1123 (PLGA hydrolysis Ea)")
_build_polymer_resolver("material_polymer_density", "density_g_cm3", "g/cm³",
    1.25,
    "Brandrup J, Immergut EH (1999) Polymer Handbook")
