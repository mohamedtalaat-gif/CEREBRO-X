"""
================================================================================
CEREBRO-X | categories/physics_dlvo.py
================================================================================
DLVO theory resolvers — electrostatic + van der Waals colloidal interactions.

Categories:
    physics_hamaker_combined        — Hamaker constant for particle-particle in medium
    physics_dlvo_potential          — Total V(D) at given separation
    physics_debye_length            — κ⁻¹ in electrolyte solution
    physics_zeta_to_surface_charge  — σ from ζ via Grahame eq

Tier cascade:
    1. NIST/MaterialsProject (live)
    5. chemicals lib correlations
    6. Israelachvili tables
    7. Pure-math: classic DLVO equations
================================================================================
"""
from __future__ import annotations

import logging
import math

from .._core import _resolved, register

log = logging.getLogger("CEREBRO-RESOLVER.dlvo")


@register("physics_hamaker_combined")
def resolve_physics_hamaker_combined(carrier_Hamaker_J: float | None = None,
                                       medium_Hamaker_J: float = 3.7e-20,
                                       researcher_override: float | None = None) -> dict:
    """Combined Hamaker constant A_132 = (√A_11 - √A_33)² for symmetric pairs.

    A_11: particle-particle Hamaker
    A_33: medium (water default = 3.7e-20 J)
    """
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided combined A",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []

    if carrier_Hamaker_J is None:
        carrier_Hamaker_J = 6e-21    # generic organic
        db_misses.append("carrier-specific Hamaker not provided")

    # Israelachvili (2011): A_132 = (√A_11 - √A_33)²
    A_132 = (math.sqrt(carrier_Hamaker_J) - math.sqrt(medium_Hamaker_J)) ** 2
    return _resolved(value=A_132, tier=6,
                      source="cerebro_value_resolver:hamaker_combine",
                      method="A_132 = (√A_11 - √A_33)² combining rule",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"A_particle_J": carrier_Hamaker_J,
                              "A_medium_J": medium_Hamaker_J, "unit": "J"})


@register("physics_debye_length")
def resolve_physics_debye_length(ionic_strength_M: float = 0.15,
                                    epsilon_r: float = 78.5,
                                    T_K: float = 310.15,
                                    researcher_override: float | None = None) -> dict:
    """Debye screening length κ⁻¹ (m).

    κ⁻¹ = √(ε₀·εr·kT / (2·N_A·e²·I·1000))
    Default I=0.15 M (physiological).
    """
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided κ⁻¹",
                          reference="Researcher input", live_db_misses=[])
    eps_0 = 8.854e-12; k_B = 1.380649e-23; N_A = 6.022e23; e = 1.602e-19
    kappa_inv = math.sqrt(eps_0 * epsilon_r * k_B * T_K
                            / (2 * N_A * e**2 * ionic_strength_M * 1000))
    return _resolved(value=kappa_inv, tier=7,
                      source="cerebro_value_resolver:debye_length",
                      method="κ⁻¹ = √(ε₀εrkT/(2N_Ae²I·1000))",
                      reference="",
                      live_db_misses=[],
                      extra={"ionic_strength_M": ionic_strength_M,
                              "unit": "m"})


@register("physics_dlvo_potential")
def resolve_physics_dlvo_potential(particle_radius_nm: float = 100,
                                      separation_nm: float = 5,
                                      zeta_mV: float = -25,
                                      Hamaker_J: float = 4e-21,
                                      ionic_strength_M: float = 0.15,
                                      epsilon_r: float = 78.5,
                                      T_K: float = 310.15,
                                      researcher_override: float | None = None) -> dict:
    """Total DLVO potential V(D) = V_vdW + V_electrostatic in units of kT.

    V_vdW = -A·R / (12·D)   (sphere-sphere, D << R)
    V_el  = 2π·εr·ε₀·R·ψ²·exp(-κD)   (linearized Poisson-Boltzmann)
    """
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided V_DLVO",
                          reference="Researcher input", live_db_misses=[])

    eps_0 = 8.854e-12; k_B = 1.380649e-23; N_A = 6.022e23; e = 1.602e-19
    R = particle_radius_nm * 1e-9
    D = separation_nm * 1e-9
    psi = zeta_mV * 1e-3

    # vdW (J)
    V_vdW = -Hamaker_J * R / (12 * D)

    # Debye length κ⁻¹
    kappa_inv = math.sqrt(eps_0 * epsilon_r * k_B * T_K
                            / (2 * N_A * e**2 * ionic_strength_M * 1000))
    kappa = 1.0 / kappa_inv

    # Electrostatic
    V_el = 2 * math.pi * epsilon_r * eps_0 * R * psi**2 * math.exp(-kappa * D)

    V_total = V_vdW + V_el
    V_kT = V_total / (k_B * T_K)
    return _resolved(value=V_kT, tier=7,
                      source="cerebro_value_resolver:dlvo_full",
                      method="V_total = V_vdW + V_el (Israelachvili 2011 sphere-sphere)",
                      reference="",
                      live_db_misses=[],
                      extra={"V_vdW_kT": V_vdW/(k_B*T_K),
                              "V_el_kT": V_el/(k_B*T_K),
                              "kappa_inv_nm": kappa_inv*1e9,
                              "unit": "kT"})


@register("physics_zeta_to_surface_charge")
def resolve_physics_zeta_to_surface_charge(zeta_mV: float = -25,
                                              ionic_strength_M: float = 0.15,
                                              epsilon_r: float = 78.5,
                                              T_K: float = 310.15,
                                              researcher_override: float | None = None) -> dict:
    """Surface charge density σ (C/m²) from ζ via Grahame equation."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided σ",
                          reference="Researcher input", live_db_misses=[])
    eps_0 = 8.854e-12; k_B = 1.380649e-23; N_A = 6.022e23; e = 1.602e-19
    psi = zeta_mV * 1e-3
    # Grahame: σ = √(8·ε₀·εr·k_B·T·c)·sinh(eψ/(2kT))
    sigma = math.sqrt(8 * eps_0 * epsilon_r * k_B * T_K
                       * ionic_strength_M * 1000 * N_A) \
             * math.sinh(e * psi / (2 * k_B * T_K))
    return _resolved(value=sigma, tier=7,
                      source="cerebro_value_resolver:grahame_eq",
                      method="σ = √(8ε₀εrkTc)·sinh(eψ/(2kT))",
                      reference="",
                      live_db_misses=[],
                      extra={"zeta_mV": zeta_mV,
                              "ionic_strength_M": ionic_strength_M,
                              "unit": "C/m²"})
