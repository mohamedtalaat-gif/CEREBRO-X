# Computations package — pure-math first-principles helpers.
from .group_contribution import (
    antoine_vapor_pressure,
    born_solvation_energy,
    clausius_clapeyron,
    ghose_crippen_logp_atomic,
    hayduk_laudie_diff,
    hh_microspeciation,
    joback_estimate,
    lennard_jones_combine,
    lj_to_hamaker,
    stokes_einstein_diff,
    wilke_chang_diff,
)
from .pka_first_principles import (
    compute_pka_from_first_principles,
    find_x_h_bonds_in_smiles,
    select_dominant_pka,
)

__all__ = [
    "antoine_vapor_pressure",
    "born_solvation_energy",
    "clausius_clapeyron",
    "compute_pka_from_first_principles",
    "find_x_h_bonds_in_smiles",
    "ghose_crippen_logp_atomic",
    "hayduk_laudie_diff",
    "hh_microspeciation",
    "joback_estimate",
    "lennard_jones_combine",
    "lj_to_hamaker",
    "select_dominant_pka",
    "stokes_einstein_diff",
    "wilke_chang_diff",
]
