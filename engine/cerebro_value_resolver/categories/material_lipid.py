"""
================================================================================
CEREBRO-X | categories/material_lipid.py
================================================================================
Lipid carrier material properties.

Categories:
    material_lipid_tm                    — phase transition Tm (°C)
    material_lipid_packing_parameter     — Israelachvili packing parameter
    material_lipid_area_per_lipid        — APL (Å²)
    material_lipid_bending_modulus       — κ (kT)
================================================================================
"""
from __future__ import annotations

import logging

from .._core import _resolved, register

log = logging.getLogger("CEREBRO-RESOLVER.lipid")

# Israelachvili lipid library (carrier-class FUNDAMENTALS, not drug data).
# Reference: Israelachvili JN (2011) Intermolecular & Surface Forces 3rd ed
LIPID_PROPERTIES = {
    # carrier_subtype → properties
    "dppc":     {"Tm_C": 41,   "P": 0.91, "APL_A2": 63, "kappa_kT": 17},
    "dspc":     {"Tm_C": 55,   "P": 1.00, "APL_A2": 60, "kappa_kT": 22},
    "dopc":     {"Tm_C": -17,  "P": 0.95, "APL_A2": 72, "kappa_kT": 13},
    "popc":     {"Tm_C": -2,   "P": 0.96, "APL_A2": 65, "kappa_kT": 16},
    "dmpc":     {"Tm_C": 24,   "P": 0.85, "APL_A2": 60, "kappa_kT": 18},
    "chol":     {"Tm_C": None, "P": 1.10, "APL_A2": 38, "kappa_kT": 35},
    # generic carrier-level fallback for "liposome" without lipid type
    "liposome": {"Tm_C": 35,   "P": 0.95, "APL_A2": 65, "kappa_kT": 18},
    "solid_lipid":{"Tm_C": 65, "P": 1.00, "APL_A2": 50, "kappa_kT": 30},
    "lipid":    {"Tm_C": 35,   "P": 0.95, "APL_A2": 65, "kappa_kT": 18},
    "micelle":  {"Tm_C": None, "P": 0.5,  "APL_A2": 70, "kappa_kT": 8},
}


def _build_lipid_resolver(category: str, prop_key: str, unit: str,
                            t7_default: float):
    @register(category)
    def resolver(carrier: str = "", lipid_type: str = "",
                  researcher_override: float | None = None) -> dict:
        db_misses: list[str] = []
        if researcher_override is not None:
            return _resolved(value=float(researcher_override), tier=0,
                              source="researcher_override",
                              method=f"User-provided {prop_key}",
                              reference="Researcher input",
                              live_db_misses=[])

        # Tier 1-5 (limited DB coverage for lipid-specific phase data live)
        db_misses.extend(["LIPID MAPS structure DB (rate-limited)",
                            "Avanti Polar Lipids product DB",
                            "thermo (n/a for lipid Tm)",
                            "chemicals (n/a)"])

        key = (lipid_type or carrier or "").lower().strip()
        # Try lipid-type first, then carrier
        for k in (lipid_type.lower(), carrier.lower(), "liposome"):
            if not k: continue
            props = LIPID_PROPERTIES.get(k)
            if props and props.get(prop_key) is not None:
                return _resolved(value=float(props[prop_key]), tier=7,
                                  source="cerebro_value_resolver:lipid_class_table",
                                  method=f"Carrier-class typical {prop_key} for "
                                          f"{k} lipid (Israelachvili tables)",
                                  reference="",
                                  live_db_misses=db_misses,
                                  extra={"carrier": carrier, "lipid_type": k,
                                          "unit": unit})

        return _resolved(value=t7_default, tier=7,
                          source="cerebro_value_resolver:generic_lipid",
                          method=f"Generic lipid {prop_key} median",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"confidence":"LOW", "unit": unit})
    resolver.__name__ = f"resolve_{category}"
    return resolver


_build_lipid_resolver("material_lipid_tm", "Tm_C", "°C", 35.0)
_build_lipid_resolver("material_lipid_packing_parameter", "P", "dimensionless", 0.95)
_build_lipid_resolver("material_lipid_area_per_lipid", "APL_A2", "Å²", 65.0)
_build_lipid_resolver("material_lipid_bending_modulus", "kappa_kT", "kT", 18.0)
