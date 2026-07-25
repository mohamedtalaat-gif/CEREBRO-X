# Computations package — pure-math first-principles helpers.
from .group_contribution import (
    joback_estimate,
    ghose_crippen_logp_atomic,
    hh_microspeciation,
    stokes_einstein_diff,
    wilke_chang_diff,
    hayduk_laudie_diff,
    lennard_jones_combine,
    lj_to_hamaker,
    born_solvation_energy,
    antoine_vapor_pressure,
    clausius_clapeyron,
)
from .pka_first_principles import (
    compute_pka_from_first_principles,
    find_x_h_bonds_in_smiles,
    select_dominant_pka,
)

__all__ = [
    "joback_estimate",
    "ghose_crippen_logp_atomic",
    "hh_microspeciation",
    "stokes_einstein_diff",
    "wilke_chang_diff",
    "hayduk_laudie_diff",
    "lennard_jones_combine",
    "lj_to_hamaker",
    "born_solvation_energy",
    "antoine_vapor_pressure",
    "clausius_clapeyron",
    "compute_pka_from_first_principles",
    "find_x_h_bonds_in_smiles",
    "select_dominant_pka",
]
