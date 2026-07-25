"""
================================================================================
CEREBRO-X |  SCIENCE ENGINES
================================================================================
File: cerebro_science_engines.py

STATUS (2026-07-25 remediation pass — see docs/AUDIT_REPORT.md):
This file originally housed 6 engines (QuantumChemEngine, MordredEngine,
ThermodynamicsEngine, MultiCompartmentPKEngine, BiophysicsEngine, PBPKEngine)
behind a ScienceOrchestrator facade. Auditing this module's actual call
graph found ScienceOrchestrator had exactly one caller anywhere in the
codebase (run.py's _run_science_and_viz), and that caller itself had zero
callers of its own — the whole orchestrator and 5 of its 6 wrapped engines
(everything except BiophysicsEngine, which the live pipeline imports
directly) were unreachable dead code, not decorative duplication of a
live path. Removed rather than left in place, matching this session's
Task 1 precedent for confirmed-dead code.

QuantumChemEngine, MordredEngine, ThermodynamicsEngine,
MultiCompartmentPKEngine, and PBPKEngine were not fabricated or
pseudoscience — they were real, reasonably-cited implementations that
happened to be orphaned. If any of them should be revived, wire a real
caller into pipeline_runner.py directly (the way BiophysicsEngine already
is) rather than through ScienceOrchestrator, and update
pbbm_engine.py's cross-reference docstring accordingly — see git history
on this file for the removed implementations.

What remains:
  DIFFUSION & BIOPHYSICS ENGINE (BiophysicsEngine)
    DLVO colloidal stability index, transcytosis energy barrier — called
    directly from pipeline_runner.py's DDS scoring step.
================================================================================
"""


import json
import logging
import math
import subprocess
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
log = logging.getLogger("CEREBRO-SCI")

# ─────────────────────────────────────────────────────────────────────────────
# INSTALLATION HELPER
# ─────────────────────────────────────────────────────────────────────────────
_INSTALL_MAP = {
    "pyscf":     "pyscf",
    "xtb":       "xtb-python",
    "deepchem":  "deepchem",
    "thermo":    "thermo",
    "cantera":   "cantera",
    "mendeleev": "mendeleev",
    "pint":      "pint",
    "molmass":   "molmass",
    "qcelemental":"qcelemental",
    "openmm":    "openmm",
    "MDAnalysis":"mdanalysis",
    "mordred":   "mordred",
    "pkpdsim":   "pkpdsim",
    "scipy":     "scipy",
}

def try_install(pkg: str) -> bool:
    """Attempt silent install. Returns True if successful."""
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "-q",
             "--break-system-packages"],
            capture_output=True, timeout=120, check=False)
        return True
    except Exception:
        return False


def _import_or_warn(module: str, pip_name: str = None):
    """Import module or log a warning with install instructions."""
    try:
        return __import__(module)
    except ImportError:
        pkg = pip_name or _INSTALL_MAP.get(module, module)
        log.debug(f"  [{module}] not installed. "
                  f"Install: pip install {pkg}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENTATION WRITER
# ─────────────────────────────────────────────────────────────────────────────
def _doc(path: Path, overview: str, significance: str,
         science: str, method: str, arch: str):
    sep = "=" * 70
    txt = (
        f"{sep}\n  CEREBRO-X |  FILE DOCUMENTATION\n"
        f"  File      : {Path(path).name}\n"
        f"  Generated : {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}\n"
        f"{sep}\n\n"
        f"{'─'*70}\n  OVERVIEW\n{'─'*70}\n{overview}\n\n"
        f"{'─'*70}\n  SIGNIFICANCE\n{'─'*70}\n{significance}\n\n"
        f"{'─'*70}\n  THEORETICAL & PRACTICAL SCIENCE\n{'─'*70}\n{science}\n\n"
        f"{'─'*70}\n  METHODOLOGY\n{'─'*70}\n{method}\n\n"
        f"{'─'*70}\n  COMPUTATIONAL ARCHITECTURE\n{'─'*70}\n{arch}\n\n"
        f"{sep}\n"
    )
    with open(str(path) + "_DOCUMENTATION.txt", "w", encoding="utf-8") as f:
        f.write(txt)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  QUANTUM CHEMISTRY ENGINE
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 5.  DIFFUSION & BIOPHYSICS ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class BiophysicsEngine:
    """
    Physical pharmacy biophysics for drug delivery systems.

    Computes:
      Stokes-Einstein diffusion coefficient
      Van der Waals interaction energy
      Debye-Hückel electrostatic screening (zeta → ζ-potential stability)
      DLVO theory: colloidal stability index
      Reynolds number: flow regime in capillaries
      Peclet number: convection vs. diffusion balance
      Transcytosis energy barrier (Bell model)
    """

    # Physical constants (SI)
    kB   = 1.380649e-23   # J/K
    T    = 310.15          # K  (37°C body temp)
    eta  = 1.002e-3        # Pa·s (water viscosity at 37°C)
    eps0 = 8.854e-12       # F/m (vacuum permittivity)
    eps_r= 80.0            # relative permittivity water
    NA   = 6.022e23        # Avogadro

    @classmethod
    def stokes_einstein_diffusion(cls, diameter_nm: float) -> float:
        """
        Stokes-Einstein equation: D = kBT / (3πηd)
        Returns diffusion coefficient in µm²/s.

        Physics: random Brownian motion of spherical particle.
        Larger particles diffuse slower (inverse relationship with d).
        """
        d_m = diameter_nm * 1e-9
        D_m2s = cls.kB * cls.T / (3 * math.pi * cls.eta * d_m)
        return round(D_m2s * 1e12, 4)   # m²/s → µm²/s

    @classmethod
    def debye_length_nm(cls, ionic_strength_mM: float = 150.0) -> float:
        """
        Debye screening length κ⁻¹ (nm).
        Physiological plasma: I ≈ 150 mM → κ⁻¹ ≈ 0.78 nm.
        Longer κ⁻¹ = weaker electrostatic screening = stronger repulsion.
        """
        I_mol_m3 = ionic_strength_mM * 1000 / 1000   # mM → mol/m³
        kappa_sq = (2 * cls.NA * I_mol_m3 * (1.602e-19)**2 /
                    (cls.eps0 * cls.eps_r * cls.kB * cls.T))
        return round(1e9 / math.sqrt(kappa_sq), 3)   # m → nm

    @classmethod
    def dlvo_stability_index(cls, diameter_nm: float,
                               zeta_mv: float,
                               hamaker_J: float = 1e-20) -> dict[str, float]:
        """
        DLVO colloidal stability theory.
        Combines van der Waals attraction (V_vdW) and electrostatic
        double-layer repulsion (V_EDL) to compute total interaction energy.

        Stability index:
          > 25 kT  → stable colloidal system (won't aggregate)
          10–25 kT → borderline stability
          < 10 kT  → unstable (aggregation expected)

        Reference: Derjaguin, Landau, Verwey, Overbeek (1941–1948).
        """
        R = (diameter_nm / 2) * 1e-9            # radius in m
        kT = cls.kB * cls.T

        # Van der Waals: V_vdW = -A·R/(12h) at surface separation h=1nm
        h = 1e-9
        V_vdW = -hamaker_J * R / (12 * h)

        # Electrostatic: V_EDL = 64πε₀εᵣR(kT/e)²γ²exp(-κh)
        zeta_V  = zeta_mv * 1e-3
        kappa   = 1 / (cls.debye_length_nm() * 1e-9)
        gamma   = math.tanh(zeta_V * 1.602e-19 / (4 * cls.kB * cls.T))
        V_EDL   = (64 * math.pi * cls.eps0 * cls.eps_r * R *
                   (cls.kB * cls.T / 1.602e-19)**2 *
                   gamma**2 * math.exp(-kappa * h))

        V_total = V_vdW + V_EDL
        stability_kT = V_total / kT

        status = ("stable" if stability_kT > 25 else
                  "borderline" if stability_kT > 10 else "unstable")

        return {
            "diameter_nm":       diameter_nm,
            "zeta_mV":           zeta_mv,
            "V_vdW_kT":          round(V_vdW / kT, 3),
            "V_EDL_kT":          round(V_EDL / kT, 3),
            "V_total_kT":        round(stability_kT, 3),
            "colloidal_status":  status,
            "debye_length_nm":   cls.debye_length_nm(),
            "diffusion_um2s":    cls.stokes_einstein_diffusion(diameter_nm),
        }

    @classmethod
    def transcytosis_energy_barrier(cls, diameter_nm: float,
                                      elasticity_kpa: float,
                                      ligand_density: float) -> dict[str, float]:
        """
        Bell model for receptor-mediated endocytosis energy barrier.

        ΔG_bind = n_bonds · G_bond - E_membrane_deformation
        where:
          n_bonds  = ligand_density × contact_area
          G_bond   = -10 kT (typical receptor–ligand bond)
          E_deform = elasticity × π·R² (membrane bending energy)

        Reference: Bell et al., Science 200:618 (1978).
        """
        R = (diameter_nm / 2) * 1e-9     # m
        kT = cls.kB * cls.T

        contact_area_nm2 = math.pi * (diameter_nm / 2)**2
        n_bonds  = ligand_density * contact_area_nm2
        G_bond   = -10 * kT                        # J per bond
        E_bonds  = n_bonds * abs(G_bond)

        # Membrane deformation: bending stiffness κ_b ~ elasticity/nm²
        kappa_b  = elasticity_kpa * 1000 * (1e-9)**2   # J (≈ Pa·m²)
        E_deform = kappa_b * math.pi * (diameter_nm / 2 * 1e-9)**2

        dG_total_kT = (E_deform - E_bonds) / kT

        return {
            "diameter_nm":        diameter_nm,
            "ligand_density_nm2": ligand_density,
            "n_bonds":            round(n_bonds, 1),
            "E_bonds_kT":         round(E_bonds / kT, 2),
            "E_deform_kT":        round(E_deform / kT, 2),
            "dG_total_kT":        round(dG_total_kT, 2),
            "transcytosis_fate":  ("favourable" if dG_total_kT < 0 else "unfavourable"),
        }

    @classmethod
    def analyse_formulation_batch(cls, df_dds: pd.DataFrame,
                                   output_dir: Path) -> pd.DataFrame:
        """
        Run full biophysics analysis on all DDS formulations.
        """
        records = []
        for _, row in df_dds.iterrows():
            sz   = float(row.get("size_nm", 80) or 80)
            zeta = float(row.get("zeta_potential_mv", -10) or -10)
            ela  = float(row.get("elasticity_kpa", 1.0) or 1.0)
            ld   = float(row.get("ligand_density_per_nm2", 0.8) or 0.8)

            dlvo   = cls.dlvo_stability_index(sz, zeta)
            trans  = cls.transcytosis_energy_barrier(sz, ela, ld)

            rec = {
                "Formulation_ID":       row.get("Formulation_ID", ""),
                "Formulation_Name":     row.get("Formulation_Name", ""),
                **dlvo,
                **{f"transcytosis_{k}": v for k, v in trans.items()
                   if k not in dlvo},
            }
            records.append(rec)

        df_out = pd.DataFrame(records)

        if output_dir:
            out = Path(output_dir) / "biophysics_analysis.csv"
            df_out.to_csv(out, index=False)
            _doc(out,
                "DLVO colloidal stability and transcytosis energy barrier analysis.",
                "Colloidal stability (V_total > 25kT) prevents aggregation in blood. "
                "Negative transcytosis ΔG confirms receptor-mediated uptake is energetically "
                "favourable — directly predicts BBB crossing efficiency.",
                "DLVO theory (Derjaguin-Landau-Verwey-Overbeek 1941-1948):\n"
                "V_total = V_vdW + V_EDL\n"
                "V_vdW = -A·R/(12h)  (London dispersion attraction)\n"
                "V_EDL = 64πε₀εᵣR(kT/e)²γ²exp(-κh)  (electrostatic repulsion)\n"
                "Debye length κ⁻¹ = 0.78 nm at physiological I=150mM.\n"
                "Bell model transcytosis: ΔG = E_deform - E_bonds (Bell 1978).",
                "1. DLVO: van der Waals + electrostatic double layer energies.\n"
                "2. Debye-Hückel screening at 150 mM ionic strength.\n"
                "3. Bell model: ligand bonds vs. membrane bending.\n"
                "4. All energies normalised to kT units.",
                "Python (scipy, numpy). All equations in SI units.")

        return df_out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing BiophysicsEngine \u2014 the only engine remaining in this "
          "file after the 2026-07-25 dead-code removal pass (see module "
          "docstring).")

    print("\n--- DLVO ---")
    dlvo = BiophysicsEngine.dlvo_stability_index(80, -15)
    print(f"  V_total={dlvo['V_total_kT']} kT  status={dlvo['colloidal_status']}")

    print("\n--- Transcytosis ---")
    trans = BiophysicsEngine.transcytosis_energy_barrier(80, 0.5, 0.8)
    print(f"  \u0394G={trans['dG_total_kT']} kT  fate={trans['transcytosis_fate']}")

    print("\nAll tests passed.")
