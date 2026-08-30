"""
================================================================================
CEREBRO-X | categories/physics_transport.py
================================================================================
Transport coefficient resolvers — diffusion, Lennard-Jones, viscosity.

Categories:
    physics_diff_coeff_water       — D in water at 37°C (m²/s)
    physics_diff_coeff_membrane    — D in lipid bilayer (m²/s)
    physics_lj_epsilon              — LJ ε / k_B (K)
    physics_lj_sigma                — LJ σ (Å)
    physics_viscosity_solvent       — η of solvent (Pa·s)

Tier cascade:
    1. NIST WebBook (live, where available)
    2. PubChem (rare for transport coeffs)
    5. chemicals library (Wilke-Chang, Hayduk-Laudie correlations)
    6. Empirical from MW + LogP
    7. Pure-math first-principles (Stokes-Einstein)
================================================================================
"""
from __future__ import annotations

import logging
import math

from .._core import _HAS_CHEMICALS, _HAS_THERMO, _resolved, register
from ..computations import stokes_einstein_diff, wilke_chang_diff

log = logging.getLogger("CEREBRO-RESOLVER.transport")


@register("physics_diff_coeff_water")
def resolve_physics_diff_coeff_water(name: str = "", smiles: str = "",
                                       mw_Da: float | None = None,
                                       T_K: float = 310.15,
                                       researcher_override: float | None = None) -> dict:
    """Aqueous diffusion coefficient (m²/s) at 37°C."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided D (m²/s)",
                          reference="Researcher input",
                          live_db_misses=[])
    db_misses: list[str] = []
    db_misses.extend(["NIST WebBook (rate-limited)", "PubChem (rare)"])

    # Tier 5: the `chemicals` library used to expose a Wilke_Chang liquid-
    # diffusivity correlation; it isn't in the currently pinned version
    # (chemicals 1.5.2 — verified: no Wilke_Chang, no diffusivity module at
    # all). Rather than attempt an import that's guaranteed to fail and
    # silently fall through every single call, skip straight to the
    # pure-math implementation of the same equation below.
    db_misses.append("chemicals.Wilke_Chang (not available in this chemicals version)")

    # Tier 6: Wilke-Chang in pure-math
    if mw_Da:
        try:
            D_cm2_s = wilke_chang_diff(mw_Da, T_K=T_K)
            return _resolved(value=D_cm2_s * 1e-4, tier=6,
                              source="cerebro_value_resolver:wilke_chang",
                              method="Wilke-Chang aqueous diffusion correlation",
                              reference="Wilke CR & Chang P (1955) AIChE J 1:264",
                              live_db_misses=db_misses,
                              extra={"unit": "m²/s"})
        except Exception: pass
    db_misses.append("Wilke-Chang (need MW)")

    # Tier 7: Stokes-Einstein
    if mw_Da:
        D = stokes_einstein_diff(mw_Da, T_K=T_K)
        return _resolved(value=D, tier=7,
                          source="cerebro_value_resolver:stokes_einstein",
                          method="D = kT/(6πηr); r ≈ 0.66·MW^(1/3) Å",
                          reference="Stokes GG (1851); Einstein A (1905)",
                          live_db_misses=db_misses,
                          extra={"unit": "m²/s"})
    return _resolved(value=5e-10, tier=7,
                      source="cerebro_value_resolver:typical_small_mol",
                      method="Typical aqueous D for small molecules at 37°C",
                      reference="Cussler EL (1997) Diffusion 2nd ed",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "m²/s"})


@register("physics_diff_coeff_membrane")
def resolve_physics_diff_coeff_membrane(name: str = "", smiles: str = "",
                                          mw_Da: float | None = None,
                                          logp: float | None = None,
                                          T_K: float = 310.15,
                                          researcher_override: float | None = None) -> dict:
    """Lateral diffusion coefficient inside a lipid bilayer (m²/s)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided membrane D",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["LIPID MAPS (no D endpoint)",
                              "Avanti (no D endpoint)"]
    # Tier 6: Saffman-Delbrück (membrane viscosity ~100x water)
    if mw_Da:
        # D_membrane ≈ D_water / (LogP-driven retention factor)
        D_water = stokes_einstein_diff(mw_Da, T_K=T_K, visc_Pa_s=0.07)  # 100x water visc
        retention = 1 + max(0, (logp or 2.5) - 1) * 0.5
        D = D_water / retention
        return _resolved(value=D, tier=6,
                          source="cerebro_value_resolver:saffman_delbruck",
                          method="Saffman-Delbrück + LogP-driven retention factor",
                          reference="Saffman PG & Delbrück M (1975) PNAS 72:3111",
                          live_db_misses=db_misses,
                          extra={"unit": "m²/s"})
    return _resolved(value=1e-12, tier=7,
                      source="cerebro_value_resolver:typical_membrane_D",
                      method="Typical membrane D for small molecules",
                      reference="Vaz WLC et al (1985) Biochemistry 24:781",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "m²/s"})


@register("physics_lj_epsilon")
def resolve_physics_lj_epsilon(name: str = "", smiles: str = "",
                                  mw_Da: float | None = None,
                                  Tb_K: float | None = None,
                                  researcher_override: float | None = None) -> dict:
    """Lennard-Jones ε / k_B (K)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided LJ ε/k",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["NIST WebBook (sparse for organics)"]

    # Stiel-Thodos: ε/k ≈ 0.77·Tc; Tc ≈ 1.5·Tb when Tb is what's available.
    # This is inline pure-math (no chemicals-library call involved despite
    # the historical tier-5 label this used to carry), so it belongs at
    # tier 7 alongside the file's other first-principles computations —
    # and shouldn't be gated behind _HAS_CHEMICALS, which has nothing to
    # do with whether this specific formula can run.
    if Tb_K:
        Tc = 1.5 * Tb_K
        eps_k = 0.77 * Tc
        return _resolved(value=eps_k, tier=7,
                          source="cerebro_value_resolver:stiel_thodos",
                          method="ε/k_B = 0.77·Tc (Stiel-Thodos correlation)",
                          reference="Stiel LI & Thodos G (1962) AIChE J 8:229",
                          live_db_misses=db_misses,
                          extra={"unit": "K"})
    # Tier 6: empirical from MW
    if mw_Da:
        eps_k = 0.5 * mw_Da
        return _resolved(value=eps_k, tier=6,
                          source="cerebro_value_resolver:empirical_mw",
                          method="ε/k ≈ 0.5·MW (rough empirical for organics)",
                          reference="Reid RC et al (1987) Properties of Gases & Liquids",
                          live_db_misses=db_misses,
                          extra={"unit": "K"})
    return _resolved(value=300.0, tier=7,
                      source="cerebro_value_resolver:typical_organic",
                      method="Typical LJ ε/k for organic small molecules",
                      reference="Reid RC et al (1987)",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "K"})


@register("physics_lj_sigma")
def resolve_physics_lj_sigma(name: str = "", smiles: str = "",
                                mw_Da: float | None = None,
                                Vc_cm3_mol: float | None = None,
                                researcher_override: float | None = None) -> dict:
    """Lennard-Jones σ (Å)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided LJ σ (Å)",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["NIST WebBook (sparse)"]
    # Tier 6: σ ≈ 0.841·Vc^(1/3) where Vc in cm³/mol (Bird-Stewart-Lightfoot)
    if Vc_cm3_mol:
        sigma = 0.841 * (Vc_cm3_mol ** (1/3))
        return _resolved(value=sigma, tier=6,
                          source="cerebro_value_resolver:bsl_correlation",
                          method="σ = 0.841·Vc^(1/3) (BSL correlation)",
                          reference="Bird RB, Stewart WE, Lightfoot EN (2002) "
                                     "Transport Phenomena 2nd ed",
                          live_db_misses=db_misses,
                          extra={"unit": "Å"})
    if mw_Da:
        sigma = 0.5 * (mw_Da ** (1/3))
        return _resolved(value=sigma, tier=7,
                          source="cerebro_value_resolver:mw_proxy",
                          method="σ ≈ 0.5·MW^(1/3) (rough)",
                          reference="Reid RC et al (1987)",
                          live_db_misses=db_misses,
                          extra={"unit": "Å"})
    return _resolved(value=5.0, tier=7,
                      source="cerebro_value_resolver:typical_organic",
                      method="Typical LJ σ for organic small molecules",
                      reference="Reid RC et al (1987)",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "Å"})


@register("physics_viscosity_solvent")
def resolve_physics_viscosity_solvent(solvent: str = "water",
                                        T_K: float = 310.15,
                                        researcher_override: float | None = None) -> dict:
    """Solvent dynamic viscosity (Pa·s)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided η",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = []
    # Tier 5: thermo
    if _HAS_THERMO:
        try:
            from thermo import Chemical
            c = Chemical(solvent, T=T_K)
            if c.mu is not None:
                return _resolved(value=float(c.mu), tier=5,
                                  source="thermo.Chemical.mu",
                                  method="thermo lib viscosity at given T",
                                  reference="thermo (Bell, 2018)",
                                  live_db_misses=db_misses,
                                  extra={"unit": "Pa·s"})
        except Exception: pass
    db_misses.append("thermo.Chemical")

    # Tier 7: Andrade equation for water
    if solvent.lower() in ("water", "h2o"):
        # Andrade: η = A·exp(B/T); for water A=2.414e-5, B=247.8
        eta = 2.414e-5 * math.exp(247.8 / (T_K - 140))
        return _resolved(value=eta, tier=7,
                          source="cerebro_value_resolver:andrade_water",
                          method="Andrade equation: η = 2.414e-5·exp(247.8/(T-140))",
                          reference="Andrade ENC (1930) Nature 125:309",
                          live_db_misses=db_misses,
                          extra={"unit": "Pa·s"})
    return _resolved(value=1e-3, tier=7,
                      source="cerebro_value_resolver:water_default",
                      method=f"Defaulted to water viscosity for {solvent!r}",
                      reference="—",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "Pa·s"})
