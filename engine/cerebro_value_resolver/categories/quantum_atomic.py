"""
================================================================================
CEREBRO-X | categories/quantum_atomic.py
================================================================================
Atomic & quantum properties — mendeleev + computed.

Categories:
    quantum_polarizability       — molecular polarizability (Å³)
    quantum_dipole_moment        — molecular dipole (Debye)
    quantum_homo_lumo_gap        — HOMO-LUMO gap (eV)
    quantum_atomic_charges_sum   — sum of partial atomic charges (Gasteiger)
    quantum_ionization_energy    — first ionization energy (eV)

Tier cascade:
    1. PubChem electronic properties (rare)
    3. RDKit Gasteiger (live computation)
    5. mendeleev atomic-additive (Tier-5 first-principles library)
    7. Pure-math empirical (electronegativity sums)
================================================================================
"""
from __future__ import annotations

import logging

from .._core import _HAS_MENDELEEV, _HAS_RDKIT, _resolved, register

log = logging.getLogger("CEREBRO-RESOLVER.quantum")


_BOHR3_TO_ANGSTROM3 = 0.529177210903 ** 3   # CODATA 2018 Bohr radius, cubed


def _atomic_polarizability(symbol: str) -> float | None:
    """Atomic polarizability (Å³) via mendeleev or hardcoded short table."""
    if _HAS_MENDELEEV:
        try:
            import mendeleev
            el = mendeleev.element(symbol)
            # mendeleev.dipole_polarizability is in Bohr³ (atomic units), not
            # Å³ — confirmed against its own H/C values (4.507/11.3 Bohr³),
            # which only match the well-known experimental 0.667/1.76 Å³
            # after this conversion. Using it unconverted overstated every
            # atomic polarizability by ~6.75x (1/0.1482).
            v = getattr(el, "dipole_polarizability", None)
            if v is not None: return float(v) * _BOHR3_TO_ANGSTROM3
        except Exception: pass
    # Short fallback table (Schwerdtfeger 2019 atomic polarizabilities, Å³)
    POL = {"H":0.667,"C":1.76,"N":1.10,"O":0.802,"S":2.90,
           "F":0.557,"Cl":2.18,"Br":3.05,"I":4.69,"P":3.63}
    return POL.get(symbol)


@register("quantum_polarizability")
def resolve_quantum_polarizability(name: str = "", smiles: str = "",
                                       researcher_override: float | None = None) -> dict:
    """Molecular polarizability α (Å³) via atomic additivity."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided α",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["PubChem (no α endpoint)"]

    if not smiles:
        return _resolved(value=15.0, tier=7,
                          source="cerebro_value_resolver:typical_drug",
                          method="Median α for drug-sized molecules",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"confidence":"LOW", "unit": "Å³"})

    # Tier 5: mendeleev atomic additivity
    from ..computations.group_contribution import _tokenize_smiles_to_atoms
    atoms = _tokenize_smiles_to_atoms(smiles)
    total_alpha = 0.0
    n_atoms = 0
    for a in atoms:
        sym = a if a in ("Cl","Br","Si","Se","I","F","P","S") else a.upper()
        v = _atomic_polarizability(sym)
        if v is not None:
            total_alpha += v
            n_atoms += 1
    if n_atoms > 0:
        # Add ~1 H per heavy atom contribution
        n_heavy = sum(1 for a in atoms if a.upper() != "H")
        total_alpha += n_heavy * 0.667    # H polarizability
        return _resolved(value=round(total_alpha, 3), tier=5,
                          source="mendeleev (atomic additivity)" if _HAS_MENDELEEV
                                  else "cerebro_value_resolver:atomic_additivity",
                          method="Σ α_i (atomic dipole polarizabilities, "
                                  "Schwerdtfeger 2019)",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "Å³", "n_atoms_summed": n_atoms})
    return _resolved(value=15.0, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Median drug polarizability",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "Å³"})


@register("quantum_dipole_moment")
def resolve_quantum_dipole_moment(name: str = "", smiles: str = "",
                                      researcher_override: float | None = None) -> dict:
    """Molecular dipole moment μ (Debye)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided μ",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["NIST WebBook (sparse)",
                              "PubChem (no μ endpoint)"]

    # Tier 3: RDKit Gasteiger charges + geometry-based moment
    if smiles and _HAS_RDKIT:
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            mol = Chem.MolFromSmiles(smiles)
            if mol is not None:
                mol = Chem.AddHs(mol)
                if AllChem.EmbedMolecule(mol, randomSeed=42) == 0:
                    AllChem.MMFFOptimizeMolecule(mol)
                    AllChem.ComputeGasteigerCharges(mol)
                    conf = mol.GetConformer()
                    dx = dy = dz = 0.0
                    for atom in mol.GetAtoms():
                        try:
                            q = float(atom.GetProp('_GasteigerCharge'))
                        except: q = 0.0
                        if q != q:    # NaN
                            continue
                        p = conf.GetAtomPosition(atom.GetIdx())
                        dx += q * p.x; dy += q * p.y; dz += q * p.z
                    mu = (dx*dx + dy*dy + dz*dz) ** 0.5 * 4.802    # eÅ → Debye
                    return _resolved(value=round(mu, 3), tier=3,
                                      source="rdkit.Gasteiger+MMFF94",
                                      method="MMFF94-optimized geometry × Gasteiger charges",
                                      reference="",
                                      live_db_misses=db_misses,
                                      extra={"unit": "Debye"})
        except Exception as e:
            log.debug(f"[μ-RDKit] {e}")
    db_misses.append("RDKit Gasteiger")

    return _resolved(value=2.5, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Median drug dipole moment",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "Debye"})


@register("quantum_homo_lumo_gap")
def resolve_quantum_homo_lumo_gap(name: str = "", smiles: str = "",
                                      aromatic_rings: float | None = None,
                                      researcher_override: float | None = None) -> dict:
    """HOMO-LUMO gap (eV) — empirical from aromatic ring count."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided HOMO-LUMO gap",
                          reference="Researcher input", live_db_misses=[])
    db_misses: list[str] = ["PubChem (no DFT endpoint)",
                              "MaterialsProject (limited)"]

    # Tier 6: empirical gap shrinks with extended π-conjugation
    if aromatic_rings is not None:
        gap = max(2.5, 5.5 - 0.4 * aromatic_rings)
        return _resolved(value=gap, tier=6,
                          source="cerebro_value_resolver:empirical_pi_conj",
                          method="HOMO-LUMO ≈ 5.5 - 0.4·N_aromatic_rings",
                          reference="",
                          live_db_misses=db_misses,
                          extra={"unit": "eV"})
    return _resolved(value=4.5, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Typical drug HOMO-LUMO gap",
                      reference="",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW", "unit": "eV"})


@register("quantum_atomic_charges_sum")
def resolve_quantum_atomic_charges_sum(name: str = "", smiles: str = "",
                                          researcher_override: float | None = None) -> dict:
    """Sum of |Gasteiger partial charges| — proxy for total ionic character."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided Σ|q|",
                          reference="Researcher input", live_db_misses=[])
    if smiles and _HAS_RDKIT:
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            mol = Chem.MolFromSmiles(smiles)
            if mol is not None:
                AllChem.ComputeGasteigerCharges(mol)
                total = 0.0
                for atom in mol.GetAtoms():
                    try:
                        q = float(atom.GetProp('_GasteigerCharge'))
                        if q == q:    # not NaN
                            total += abs(q)
                    except: continue
                return _resolved(value=round(total, 4), tier=3,
                                  source="rdkit.Gasteiger",
                                  method="Σ|q_i| over Gasteiger atomic charges",
                                  reference="",
                                  live_db_misses=[],
                                  extra={"unit": "e"})
        except Exception: pass
    return _resolved(value=2.5, tier=7,
                      source="cerebro_value_resolver:typical_drug",
                      method="Typical Σ|q| for drug-sized molecules",
                      reference="—",
                      live_db_misses=["RDKit unavailable"],
                      extra={"confidence":"LOW", "unit": "e"})


@register("quantum_ionization_energy")
def resolve_quantum_ionization_energy(symbol: str = "C",
                                          researcher_override: float | None = None) -> dict:
    """First ionization energy of an element (eV)."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided IE",
                          reference="Researcher input", live_db_misses=[])

    # Tier 5: mendeleev / periodictable
    if _HAS_MENDELEEV:
        try:
            import mendeleev
            el = mendeleev.element(symbol)
            ie = el.ionenergies.get(1) if hasattr(el, "ionenergies") else None
            if ie is not None:
                return _resolved(value=float(ie), tier=5,
                                  source="mendeleev",
                                  method="mendeleev.element.ionenergies[1]",
                                  reference="NIST Atomic Spectra Database",
                                  live_db_misses=[],
                                  extra={"unit": "eV"})
        except Exception: pass

    # Tier 7: short table fallback (eV, NIST)
    IE = {"H":13.598,"C":11.260,"N":14.534,"O":13.618,"S":10.360,
          "F":17.422,"Cl":12.968,"Br":11.814,"I":10.451,"P":10.487}
    v = IE.get(symbol)
    if v is not None:
        return _resolved(value=v, tier=7,
                          source="cerebro_value_resolver:nist_short_table",
                          method="NIST atomic IE short table",
                          reference="NIST Atomic Spectra Database "
                                     "https://physics.nist.gov/PhysRefData/ASD",
                          live_db_misses=[],
                          extra={"unit": "eV"})
    # No element symbol provided, not in the NIST short table, and mendeleev
    # couldn't resolve it either (an invalid/unrecognized symbol). The
    # Bohr/Rydberg hydrogen-like IE formula R·(Z_eff/n)²·n² algebraically
    # reduces to R·Z_eff² for ANY value of n — the n's cancel exactly — so
    # this is not actually a per-element Slater's-rules computation; it's
    # the fixed hydrogen ground-state ionization energy used as a generic
    # last-resort baseline, same honest spirit as this file's other
    # "typical_drug"/tier-7 fallbacks.
    Rydberg_eV = 13.605693    # NIST CODATA 2018
    return _resolved(value=round(Rydberg_eV, 3), tier=7,
                      source="cerebro_value_resolver:hydrogen_like_baseline",
                      method="Generic hydrogen-like ionization-energy baseline "
                              "(no data for this element symbol)",
                      reference="",
                      live_db_misses=["mendeleev (no value for this symbol)"],
                      extra={"confidence": "LOW", "unit": "eV"})
