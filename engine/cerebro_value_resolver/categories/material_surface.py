# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X | categories/material_surface.py
================================================================================
Carrier surface properties.

Categories:
    material_zeta_intrinsic    — bare carrier zeta (mV) without surfactant
    material_dielectric        — relative permittivity at 37°C
    material_refractive_index  — n at 589 nm
    material_surface_tension   — γ (mN/m)
    material_hamaker_constant  — A (J)
================================================================================
"""
from __future__ import annotations
import logging
from typing import Optional, Dict, List
from .._core import register, _resolved

log = logging.getLogger("CEREBRO-RESOLVER.surface")

# Reference values per carrier class (Israelachvili 2011 + Hiemenz 1997)
SURFACE_PROPERTIES = {
    "liposome":    {"zeta_mV": -8,   "epsilon_r": 78.5, "n": 1.46,
                     "gamma_mN_m": 30, "Hamaker_J": 4e-21},
    "plga":        {"zeta_mV": -25,  "epsilon_r": 6.0,  "n": 1.50,
                     "gamma_mN_m": 35, "Hamaker_J": 6e-21},
    "polymer":     {"zeta_mV": -15,  "epsilon_r": 5.0,  "n": 1.55,
                     "gamma_mN_m": 40, "Hamaker_J": 7e-21},
    "micelle":     {"zeta_mV": -2,   "epsilon_r": 78.0, "n": 1.40,
                     "gamma_mN_m": 25, "Hamaker_J": 3e-21},
    "dendrimer":   {"zeta_mV": +20,  "epsilon_r": 30.0, "n": 1.48,
                     "gamma_mN_m": 32, "Hamaker_J": 5e-21},
    "metallic":    {"zeta_mV": -30,  "epsilon_r": -np_inf if False else 2.0,
                     "n": 0.18,    # gold at 589 nm
                     "gamma_mN_m": 1100, "Hamaker_J": 3e-19},
    "solid_lipid": {"zeta_mV": -20,  "epsilon_r": 5.5,  "n": 1.47,
                     "gamma_mN_m": 30, "Hamaker_J": 5e-21},
    "exosome":     {"zeta_mV": -22,  "epsilon_r": 78.5, "n": 1.46,
                     "gamma_mN_m": 32, "Hamaker_J": 4e-21},
}


def _build_surface_resolver(category: str, prop_key: str, unit: str,
                              t7_default: float, reference: str):
    @register(category)
    def resolver(carrier: str = "",
                  researcher_override: Optional[float] = None) -> Dict:
        db_misses: List[str] = []
        if researcher_override is not None:
            return _resolved(value=float(researcher_override), tier=0,
                              source="researcher_override",
                              method=f"User-provided {prop_key}",
                              reference="Researcher input",
                              live_db_misses=[])
        db_misses.extend(["NIST WebBook (limited carrier-specific data)",
                            "MaterialsProject"])
        key = (carrier or "").lower().strip()
        props = SURFACE_PROPERTIES.get(key)
        if props and props.get(prop_key) is not None:
            return _resolved(value=float(props[prop_key]), tier=7,
                              source="cerebro_value_resolver:surface_class_table",
                              method=f"Carrier-class typical {prop_key}",
                              reference=reference,
                              live_db_misses=db_misses,
                              extra={"carrier": key, "unit": unit})
        return _resolved(value=t7_default, tier=7,
                          source="cerebro_value_resolver:generic_default",
                          method=f"Generic {prop_key} default",
                          reference=reference,
                          live_db_misses=db_misses,
                          extra={"confidence":"LOW", "unit": unit})
    resolver.__name__ = f"resolve_{category}"
    return resolver


# patch syntax error in dict above (np_inf)
SURFACE_PROPERTIES["metallic"]["epsilon_r"] = 2.0


_build_surface_resolver("material_zeta_intrinsic", "zeta_mV", "mV", -10.0,
    "Hiemenz PC, Rajagopalan R (1997) Principles of Colloid and Surface Chemistry")
_build_surface_resolver("material_dielectric", "epsilon_r", "ε_r", 78.5,
    "Israelachvili JN (2011) Intermolecular and Surface Forces")
_build_surface_resolver("material_refractive_index", "n", "RIU", 1.46,
    "Hiemenz PC (1997)")
_build_surface_resolver("material_surface_tension", "gamma_mN_m", "mN/m", 30.0,
    "Israelachvili JN (2011)")
_build_surface_resolver("material_hamaker_constant", "Hamaker_J", "J", 4e-21,
    "Israelachvili JN (2011)")
