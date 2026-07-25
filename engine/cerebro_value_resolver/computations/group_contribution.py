"""
================================================================================
CEREBRO-X | computations/group_contribution.py
================================================================================
Pure-math first-principles physical-chemistry computations.

ALL functions here are LIBRARY-FREE except for `math` and `re`. They are
the absolute last-resort tier (Tier 7) used by the resolver when every
live database AND every external library has failed.

References for each method are inline. Most are textbook/journal correlations
that any pharmaceutical chemist can verify by hand from a SMILES.

Implementations:
  - joback_estimate            — Joback group contribution for Tb, Tm, Tc,
                                  Pc, Vc, ΔHvap, ΔHform, Cp, etc.
  - ghose_crippen_logp_atomic  — atom-based LogP without RDKit
  - hh_microspeciation         — Bjerrum 4-microspecies + HH monoprotic
  - wilke_chang_diff           — Wilke-Chang infinite-dilution diffusivity
  - hayduk_laudie_diff         — Hayduk-Laudie aqueous diffusivity
  - stokes_einstein_diff       — Stokes-Einstein for spherical solute
  - lennard_jones_combine      — LB combining rules for ε/σ
  - lj_to_hamaker              — Hamaker constant from LJ params
  - bornsolvation_energy       — Born-Onsager solvation free energy
  - antoine_vapor_pressure     — Antoine equation for P_sat(T)
  - clausius_clapeyron         — phase boundary slope dP/dT
================================================================================
"""
from __future__ import annotations

import math

# ──────────────────────────────────────────────────────────────────────────
# Joback (1987) group contribution — atom & functional-group counts
# Reference: Joback KG, Reid RC (1987) Chem Eng Commun 57:233
#
# We use a SMARTS-free SMILES tokenizer to count groups. Estimates Tb, Tm,
# Tc (critical temperature), Vc (critical volume), Pc (critical pressure),
# ΔHvap, ΔHform, ΔGform, Cp(298 K).
# ──────────────────────────────────────────────────────────────────────────

# Joback group contributions — partial table with the most common groups
# encountered in pharmaceutically-relevant molecules.
#
# Format: group_label → (Tb_K, Tm_K, Tc_K, Pc_bar, Vc_cm3_mol, dHvap_kJ_mol,
#                         dHform_kJ_mol, dGform_kJ_mol, Cp_a, Cp_b, Cp_c, Cp_d)
JOBACK_GROUPS: dict[str, tuple] = {
    # alkyl
    "-CH3":      (23.58, -5.10, 0.0141, -0.0012,  65, 2.373, -76.45, -43.96,
                   1.95E1, -8.08E-3, 1.53E-4, -9.67E-8),
    "-CH2-":     (22.88, 11.27, 0.0189,  0.0000,  56, 2.226, -20.64,  8.42,
                  -9.09E-1, 9.50E-2, -5.44E-5, 1.19E-8),
    "-CH<":      (21.74, 12.64, 0.0164,  0.0020,  41, 1.691,  29.89, 58.36,
                  -2.30E1, 2.04E-1, -2.65E-4, 1.20E-7),
    ">C<":       (18.25, 46.43, 0.0067,  0.0043,  27, 0.636,  82.23, 116.02,
                  -6.62E1, 4.27E-1, -6.41E-4, 3.01E-7),
    # aromatic (ring atoms)
    "=CH-(ar)":   (26.73, 8.13,  0.0082, 0.0011,  41, 2.544,   2.09, 11.30,
                  -8.00E0, 1.05E-1, -9.63E-5, 3.56E-8),
    "=C<(ar)":    (31.01, 37.02, 0.0143, 0.0008,  32, 3.059,  46.43, 54.05,
                  -2.81E1, 2.08E-1, -3.06E-4, 1.46E-7),
    # functional groups
    "-OH(alc)":   (92.88, 44.45, 0.0741, 0.0112,  28,18.279,-208.04,-189.20,
                   2.57E1, -6.91E-2, 1.77E-4, -9.88E-8),
    "-OH(phen)":  (76.34, 82.83, 0.0240, 0.0184,  -25,40.713,-221.65,-197.37,
                   -2.81E0, 1.11E-1, -1.16E-4, 4.94E-8),
    "-O-(alkoxy)":(22.42, 22.23, 0.0168, 0.0015,  18, 2.406,-132.22,-105.00,
                   2.55E1, -6.32E-2, 1.11E-4, -5.48E-8),
    ">C=O":       (94.97, 72.24, 0.0380, 0.0031,  73,17.029,-133.22,-120.50,
                   6.45E0, 6.70E-2, -3.57E-5, 2.86E-9),
    "-COOH":     (169.09, 155.5, 0.0791, 0.0077,  89,27.030,-426.72,-387.87,
                   2.41E1, 4.27E-2, 8.04E-5, -6.87E-8),
    "-COOR":     (81.10, 53.60, 0.0481, 0.0005,  82,12.624,-337.92,-301.95,
                   2.45E1, 4.02E-2, 4.02E-5, -4.52E-8),
    "-NH2":      (73.23, 66.89, 0.0243, 0.0109,  38,14.296,  -22.02,  14.07,
                   2.69E1, -4.12E-2, 1.64E-4, -9.76E-8),
    "-NH-":      (50.17, 52.66, 0.0295, 0.0077,  35, 8.071,   53.47,  89.39,
                  -1.21E1, 7.62E-2, -4.86E-5, 1.05E-8),
    ">N-":       (52.82, 101.51,0.0130, 0.0114,  17, 4.097,  123.34, 163.16,
                  -3.11E1, 2.27E-1, -3.20E-4, 1.46E-7),
    "-CN":       (125.66,52.80, 0.0496, 0.0101,  91,25.859,   88.43, 121.91,
                   3.65E1, -7.33E-2, 1.84E-4, -1.03E-7),
    "-NO2":      (152.54,127.24,0.0437, 0.0064,  91,15.792, -66.57, -16.83,
                   2.56E1, -1.32E-2, 1.59E-4, -9.45E-8),
    "-F":         (-0.03, -15.78,0.0111,-0.0057, 27,-0.670,-251.92,-247.19,
                   2.65E1, -9.13E-2, 1.91E-4, -1.03E-7),
    "-Cl":       (38.13,  13.55,0.0105,-0.0049,  58, 6.582, -71.55, -64.31,
                   3.33E1, -9.63E-2, 1.87E-4, -9.96E-8),
    "-Br":       (66.86,  43.43,0.0133, 0.0057,  71, 9.520, -29.48, -38.06,
                   2.86E1, -6.49E-2, 1.36E-4, -7.45E-8),
    "-I":         (93.84, 41.69,0.0068, -0.0034, 97,11.606,  21.06,   5.74,
                   3.21E1, -6.41E-2, 1.26E-4, -6.87E-8),
    "-S-":        (52.10, 31.22,0.0119, 0.0049,  54, 6.884, 41.87,  33.12,
                   1.61E1, 8.10E-3, 4.91E-5, -3.56E-8),
}


def _tokenize_smiles_to_atoms(smiles: str) -> list[str]:
    """Very simple SMILES atom tokenizer. Handles two-letter elements and
    aromatic-vs-aliphatic distinction (lowercase = aromatic).
    Skips bond chars, parens, ring-closure digits.
    """
    atoms: list[str] = []
    i = 0
    skip = set("()=#-+./\\@123456789%0[]") 
    while i < len(smiles):
        c = smiles[i]
        if c in skip: i += 1; continue
        # Two-letter element (Cl, Br, Si, etc.)
        if i + 1 < len(smiles):
            two = smiles[i:i+2]
            if two in ("Cl", "Br", "Si", "Se", "As", "Te"):
                atoms.append(two); i += 2; continue
        atoms.append(c); i += 1
    return atoms


def _approximate_joback_groups(smiles: str) -> dict[str, int]:
    """Rough Joback group counting from SMILES tokens (no SMARTS).

    Counts (-CH3, -CH2-, -CH<, =CH-(ar), =C<(ar), -OH(alc), -OH(phen),
    -COOH, -COOR, -NH2, -NH-, >N-, -CN, -NO2, -F, -Cl, -Br, -I, -S-).
    Approximations are deliberate — Tier 7 is fallback only.
    """
    atoms = _tokenize_smiles_to_atoms(smiles)
    counts: dict[str, int] = {k: 0 for k in JOBACK_GROUPS}

    n_C  = sum(1 for a in atoms if a == "C")
    n_c  = sum(1 for a in atoms if a == "c")     # aromatic
    n_O  = sum(1 for a in atoms if a == "O")
    n_o  = sum(1 for a in atoms if a == "o")
    n_N  = sum(1 for a in atoms if a == "N")
    n_n  = sum(1 for a in atoms if a == "n")
    n_S  = sum(1 for a in atoms if a in ("S","s"))
    n_F  = sum(1 for a in atoms if a == "F")
    n_Cl = sum(1 for a in atoms if a == "Cl")
    n_Br = sum(1 for a in atoms if a == "Br")
    n_I  = sum(1 for a in atoms if a == "I")

    # Aliphatic carbons distributed roughly: -CH3 (terminal) ~30%, -CH2- ~50%,
    # -CH< ~15%, >C< ~5%
    counts["-CH3"]   = max(1, int(n_C * 0.30))
    counts["-CH2-"]  = max(0, int(n_C * 0.50))
    counts["-CH<"]    = max(0, int(n_C * 0.15))
    counts[">C<"]    = max(0, n_C - counts["-CH3"] - counts["-CH2-"] - counts["-CH<"])

    # Aromatic carbons: ~85% =CH-, 15% =C<
    counts["=CH-(ar)"]  = max(0, int(n_c * 0.85))
    counts["=C<(ar)"]   = max(0, n_c - counts["=CH-(ar)"])

    # Oxygen heuristic from substring: COOH > COOR > C=O > -O- > -OH
    counts["-COOH"]   = smiles.count("C(=O)O") + smiles.count("OC(=O)")
    counts["-COOR"]   = smiles.count("C(=O)OC") - counts["-COOH"]
    counts["-COOR"]   = max(0, counts["-COOR"])
    counts[">C=O"]    = max(0, smiles.count("C(=O)") - counts["-COOH"] - counts["-COOR"])
    if "Oc" in smiles or "cO" in smiles or "c1ccc(O" in smiles:
        counts["-OH(phen)"] = smiles.count("Oc") + smiles.count("cO")
    counts["-OH(alc)"] = max(0, n_O - counts["-COOH"]*2 - counts["-COOR"]*2
                                - counts[">C=O"] - counts["-OH(phen)"])
    counts["-O-(alkoxy)"] = max(0, n_o + n_O - sum([counts["-COOH"]*2,
                                  counts["-COOR"]*2, counts[">C=O"],
                                  counts["-OH(alc)"], counts["-OH(phen)"]]))

    # Nitrogen heuristic
    counts["-NH2"] = smiles.count("N") - max(0, n_N - 1)
    counts["-NH-"] = max(0, smiles.count("N") - counts["-NH2"] - 1)
    counts[">N-"]  = max(0, n_N - counts["-NH2"] - counts["-NH-"])
    counts["-CN"]  = smiles.count("C#N")
    counts["-NO2"] = smiles.count("N(=O)=O") + smiles.count("[N+](=O)[O-]")

    counts["-F"]  = n_F;  counts["-Cl"] = n_Cl
    counts["-Br"] = n_Br; counts["-I"]  = n_I
    counts["-S-"] = n_S

    return {k: v for k, v in counts.items() if v > 0}


def joback_estimate(smiles: str) -> dict[str, float]:
    """Estimate Tb (K), Tm (K), Tc (K), Pc (bar), Vc (cm³/mol), ΔHvap, etc.

    Joback equations:
      Tb = 198 + Σ(ΔTb_i)
      Tm =  122 + Σ(ΔTm_i)
      Tc = Tb / [0.584 + 0.965·ΣΔ - (ΣΔ)²]   where Δ are critical-T contribs
      Pc = 1 / [0.113 + 0.0032·N_atoms - ΣΔ_Pc]²
      Vc =  17.5 + ΣΔ_Vc
      ΔHvap (kJ/mol) =  15.30 + ΣΔ_Hv     (at boiling)
      ΔHform (kJ/mol)= -68.29 + ΣΔ_Hf
      Cp(T) = ΣΔ_Cp_a - 37.93 + (ΣΔ_Cp_b + 0.210)·T
              + (ΣΔ_Cp_c - 3.91e-4)·T²
              + (ΣΔ_Cp_d + 2.06e-7)·T³  J/mol/K
    """
    if not smiles or not isinstance(smiles, str):
        return {}
    groups = _approximate_joback_groups(smiles)
    if not groups:
        return {}
    Tb_sum = Tm_sum = 0.0
    Tc_sum = Pc_sum = Vc_sum = 0.0
    Hv_sum = Hf_sum = Gf_sum = 0.0
    Cp_a = Cp_b = Cp_c = Cp_d = 0.0
    for g, n in groups.items():
        if g not in JOBACK_GROUPS: continue
        c = JOBACK_GROUPS[g]
        Tb_sum += n * c[0];   Tm_sum += n * c[1]
        Tc_sum += n * c[2];   Pc_sum += n * c[3]
        Vc_sum += n * c[4];   Hv_sum += n * c[5]
        Hf_sum += n * c[6];   Gf_sum += n * c[7]
        Cp_a += n * c[8]; Cp_b += n * c[9]
        Cp_c += n * c[10]; Cp_d += n * c[11]
    Tb = 198 + Tb_sum
    Tm = 122 + Tm_sum
    Tc = Tb / max(1e-6, (0.584 + 0.965 * Tc_sum - Tc_sum * Tc_sum))
    n_atoms = sum(groups.values())
    Pc = 1.0 / max(1e-3, (0.113 + 0.0032 * n_atoms - Pc_sum)) ** 2
    Vc = 17.5 + Vc_sum
    Hvap = 15.30 + Hv_sum     # at boiling
    Hf   = -68.29 + Hf_sum
    Gf   = -53.88 + Gf_sum
    return {
        "Tb_K": round(Tb, 2),
        "Tm_K": round(Tm, 2),
        "Tc_K": round(Tc, 2),
        "Pc_bar": round(Pc, 2),
        "Vc_cm3_mol": round(Vc, 2),
        "Hvap_kJ_mol": round(Hvap, 2),
        "Hform_kJ_mol": round(Hf, 2),
        "Gform_kJ_mol": round(Gf, 2),
        "Cp_coeffs_298": (round(Cp_a, 3), round(Cp_b, 3),
                            round(Cp_c, 6), round(Cp_d, 9)),
    }


# ──────────────────────────────────────────────────────────────────────────
# Atom-additive LogP (Ghose-Crippen 1986, simplified)
# Used when neither RDKit nor live DBs return a value.
# ──────────────────────────────────────────────────────────────────────────
ATOM_LOGP_GHOSE_CRIPPEN = {
    # Approximate single-atom hydrophobicity contributions, in log-octanol.
    # Reference: Ghose AK & Crippen GM (1986) J Comput Chem 7:565
    "C":  0.20, "c":  0.30,    # aliphatic / aromatic
    "N": -0.40, "n": -0.10,
    "O": -0.50, "o": -0.20,
    "S":  0.30, "s":  0.30,
    "F":  0.40, "Cl": 0.80, "Br": 1.00, "I": 1.20,
    "P":  0.10, "H":  0.20,
    "Si": 0.50, "Se": 0.30,
}


def ghose_crippen_logp_atomic(smiles: str) -> float | None:
    """Atom-additive LogP (no RDKit). Returns rounded LogP or None."""
    if not smiles: return None
    atoms = _tokenize_smiles_to_atoms(smiles)
    if not atoms: return None
    total = sum(ATOM_LOGP_GHOSE_CRIPPEN.get(a, 0.0) for a in atoms)
    return round(total, 2)


# ──────────────────────────────────────────────────────────────────────────
# Bjerrum 4-microspecies / Henderson-Hasselbalch
# ──────────────────────────────────────────────────────────────────────────
def hh_microspeciation(pka_acid: float | None,
                         pka_base: float | None,
                         pH: float = 7.4) -> dict[str, float]:
    """Bjerrum 4-microspecies (acid+base) or HH (single-site). Returns
    fractions f_cationic, f_anionic, f_zwitterion, f_neutral and net charge.

    Reference: Bjerrum N (1923) Z Physik Chem 106:219; Pagliara A et al
    (1997) J Med Chem 40:1972.
    """
    if pka_acid is not None and pka_base is not None:
        R_a = 10 ** (pH - pka_acid)
        R_b = 10 ** (pka_base - pH)
        num_HA_HB  = R_b
        num_A_HB   = R_a * R_b
        num_HA_B   = 1.0
        num_A_B    = R_a
        Z = num_HA_HB + num_A_HB + num_HA_B + num_A_B
        f_cat = num_HA_HB / Z
        f_zw  = num_A_HB / Z
        f_neu = num_HA_B / Z
        f_ani = num_A_B / Z
        method = "Bjerrum 4-microspecies"
    elif pka_base is not None:
        f_cat = 1.0 / (1.0 + 10 ** (pH - pka_base))
        f_ani = 0.0; f_zw = 0.0; f_neu = 1.0 - f_cat
        method = "Henderson-Hasselbalch (monoprotic base)"
    elif pka_acid is not None:
        f_ani = 1.0 / (1.0 + 10 ** (pka_acid - pH))
        f_cat = 0.0; f_zw = 0.0; f_neu = 1.0 - f_ani
        method = "Henderson-Hasselbalch (monoprotic acid)"
    else:
        f_cat = f_ani = f_zw = 0.0; f_neu = 1.0
        method = "no ionizable groups (assumed neutral)"
    return {
        "f_cationic":   round(f_cat, 4),
        "f_anionic":    round(f_ani, 4),
        "f_zwitterion": round(f_zw, 4),
        "f_neutral":    round(f_neu, 4),
        "net_charge":   round(f_cat - f_ani, 4),
        "method":       method,
    }


# ──────────────────────────────────────────────────────────────────────────
# Diffusivity correlations
# ──────────────────────────────────────────────────────────────────────────
def stokes_einstein_diff(mw_Da: float, T_K: float = 310.15,
                            visc_Pa_s: float = 6.91e-4) -> float:
    """Stokes-Einstein D (m²/s) for spherical solute.

    D = kT / (6πηr); r ≈ 0.066·MW^(1/3) Å (Wilke-Chang correlation).
    Defaults: T=37°C body temp, η=plasma viscosity.
    """
    if mw_Da <= 0: return 0.0
    k_B = 1.380649e-23
    r_m = 6.6e-12 * (mw_Da ** (1/3))
    return (k_B * T_K) / (6 * math.pi * visc_Pa_s * r_m)


def wilke_chang_diff(mw_solute_Da: float, T_K: float = 310.15,
                        visc_solvent_cP: float = 0.69,
                        Vm_solute_cm3_mol: float | None = None,
                        phi_solvent: float = 2.6) -> float:
    """Wilke-Chang (1955) AIChE J 1:264 — D₁₂ (cm²/s).

    D = 7.4e-8 · (φ·M_solvent)^0.5 · T / (η · Vm^0.6)

    Defaults: water at 37°C (φ=2.6, M=18 g/mol). Vm estimated from MW
    via Schroeder volume increment if not supplied.
    """
    M_solvent = 18.015
    if Vm_solute_cm3_mol is None:
        # Schroeder: ~7 cm³/mol per heavy atom; for general molecules
        # MW/density ≈ MW/1.2 g/cm³ for typical organics
        Vm_solute_cm3_mol = mw_solute_Da / 1.2
    return (7.4e-8 * math.sqrt(phi_solvent * M_solvent) * T_K
             / (visc_solvent_cP * Vm_solute_cm3_mol ** 0.6))


def hayduk_laudie_diff(Vm_solute_cm3_mol: float,
                          T_K: float = 310.15) -> float:
    """Hayduk-Laudie (1974) AIChE J 20:611 — aqueous D for non-electrolytes.

    D₁₂ = 13.26e-5 / (η_water^1.14 · Vm^0.589)   in cm²/s
    """
    visc_water = 0.69    # cP at 37°C
    return 13.26e-5 / (visc_water ** 1.14 * Vm_solute_cm3_mol ** 0.589)


# ──────────────────────────────────────────────────────────────────────────
# Lennard-Jones combining + Hamaker
# ──────────────────────────────────────────────────────────────────────────
def lennard_jones_combine(eps1_K: float, sig1_A: float,
                             eps2_K: float, sig2_A: float
                            ) -> tuple[float, float]:
    """Lorentz-Berthelot combining rules.
    σ_12 = (σ₁ + σ₂)/2;  ε_12 = √(ε₁·ε₂)
    """
    return (math.sqrt(eps1_K * eps2_K), (sig1_A + sig2_A) / 2)


def lj_to_hamaker(eps_K: float, sig_A: float,
                    n_atoms_per_unit_vol: float = 6e28) -> float:
    """Hamaker constant from LJ params (rough).
    A ≈ π² · ε · n²·σ⁶  (in J)
    """
    k_B = 1.380649e-23
    eps_J = eps_K * k_B
    sig_m = sig_A * 1e-10
    return math.pi ** 2 * eps_J * (n_atoms_per_unit_vol ** 2) * sig_m ** 6


# ──────────────────────────────────────────────────────────────────────────
# Born-Onsager solvation free energy
# ──────────────────────────────────────────────────────────────────────────
def born_solvation_energy(charge_e: float, radius_A: float,
                            eps_solvent: float = 78.5) -> float:
    """Born (1920) Z Phys 1:45 — ΔG_solv (kJ/mol) for a charged sphere.

    ΔG = -(Ne²·Z²)/(8πε₀r) · (1 − 1/εr)
    """
    if radius_A <= 0: return 0.0
    Ne   = 6.022e23; e_C = 1.602e-19; eps0 = 8.854e-12
    r_m = radius_A * 1e-10
    return -(Ne * e_C**2 * charge_e**2) / (8 * math.pi * eps0 * r_m) \
            * (1 - 1/eps_solvent) / 1000     # → kJ/mol


# ──────────────────────────────────────────────────────────────────────────
# Antoine / Clausius-Clapeyron
# ──────────────────────────────────────────────────────────────────────────
def antoine_vapor_pressure(T_K: float, A: float, B: float, C: float) -> float:
    """Antoine equation: log10(P_kPa) = A − B/(T_K + C). Returns P in Pa."""
    P_kPa = 10 ** (A - B / (T_K + C))
    return P_kPa * 1000


def clausius_clapeyron(T1_K: float, P1_Pa: float,
                          dHvap_J_mol: float) -> tuple[float, float]:
    """Returns (T2, P2) extrapolation — caller picks T2 → P2 or vice versa.
    Here: returns slope dP/dT and intercept for ln(P) = -ΔHvap/RT + C.
    """
    R = 8.314
    slope_lnP_invT = -dHvap_J_mol / R
    intercept = math.log(P1_Pa) + dHvap_J_mol / (R * T1_K)
    return slope_lnP_invT, intercept
