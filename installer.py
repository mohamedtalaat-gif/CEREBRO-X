"""
================================================================================
CEREBRO-X — Runtime Dependency Installer
================================================================================
File: installer.py

Extracted from run.py (was Section 3, "DEPENDENCY INSTALLER") as part of
splitting run.py's mixed responsibilities into focused modules — see
docs/AUDIT_REPORT.md section 13 ("Split run.py into focused modules").

Fallback installer only — primary installs are in Dockerfile. Called once
from run.py's __main__ block before pipeline imports run.
================================================================================
"""
from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger("CEREBRO-INSTALL")

# Maps pip package name -> actual importable module name.
# Without this mapping __import__("scikit-learn") always fails even when
# sklearn IS installed, causing a pointless re-install every startup.
_IMPORT_NAME: dict = {
    "scikit-learn":               "sklearn",
    "python-dotenv":              "dotenv",
    "pyyaml":                     "yaml",
    "biopython":                  "Bio",
    "chembl-webresource-client":  "chembl_webresource_client",
    "prometheus-client":          "prometheus_client",
    "mdanalysis":                 "MDAnalysis",
    "uvicorn[standard]":          "uvicorn",
}

# Core packages — fast to install, required for pipeline
REQUIRED = [
    "numpy", "pandas", "matplotlib", "seaborn", "scipy",
    "scikit-learn", "xgboost", "shap", "joblib",
    "requests", "pubchempy", "networkx", "openpyxl",
    "pydantic", "python-dotenv", "pyyaml",
    "fastapi", "uvicorn[standard]", "apscheduler",
    "prometheus-client", "reportlab",
]

# Chemistry packages — medium-weight, 30 s timeout each
CHEM_PACKAGES = [
    "rdkit",                      # molecular descriptors, SMILES, fingerprints
    "biopython",                  # FASTA, protein analysis, sequence utilities
    "chembl-webresource-client",  # ChEMBL API
    "mendeleev",                  # periodic table, atomic properties
    "periodictable",              # physical/nuclear properties of elements
    "thermo",                     # chemical thermodynamics
    "pint",                       # unit conversion
    "molmass",                    # molecular mass from formula
    "mdanalysis",                 # molecular dynamics trajectory analysis
    "qcelemental",                # quantum chemistry constants
]

# Heavy/optional packages (PyTorch-dependent or very slow to compile).
# Skipped silently if install fails or times out — pipeline degrades gracefully.
OPTIONAL_HEAVY = [
    "chempy",     # equilibria/kinetics — optional science engine
    "ase",        # DFT geometry — optional science engine
    "pymatgen",   # materials science — optional science engine
    # deepchem requires torch — install manually if GPU available
]


def install_missing() -> None:
    """
    Install missing packages at runtime (fallback — Dockerfile is primary).
    Uses correct module name for import check to avoid spurious reinstalls.
    """
    def _is_importable(pkg: str) -> bool:
        mod = _IMPORT_NAME.get(pkg, pkg.split("[")[0].replace("-", "_").split(">=")[0])
        try:
            __import__(mod)
            return True
        except ImportError:
            return False

    def _pip_install(pkg: str, timeout: int = 60) -> bool:
        try:
            # --upgrade matters here, not just for freshness: every caller of
            # this function already found the package present but broken
            # (_is_importable returned False for something __import__ raised
            # on). Without --upgrade, `pip install pkg` sees the existing
            # broken install already "satisfies" an unconstrained spec and
            # no-ops -- silently leaving the package exactly as broken as
            # before "fixing" it (this is exactly how thermo stayed on a
            # version whose serialize.py imports a chemicals constant that
            # newer chemicals releases removed, even after this function
            # logged that it was reinstalling thermo).
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", pkg,
                 "-q", "--break-system-packages"],
                capture_output=True, timeout=timeout, check=False,
            )
            return result.returncode == 0
        except Exception as e:
            log.warning(f"  Could not install {pkg}: {e}")
            return False

    # Core + chemistry packages
    for pkg in REQUIRED + CHEM_PACKAGES:
        if not _is_importable(pkg):
            log.info(f"  Installing {pkg} …")
            _pip_install(pkg, timeout=90)

    # Heavy optional packages — longer timeout, failures are non-fatal
    for pkg in OPTIONAL_HEAVY:
        if not _is_importable(pkg):
            log.info(f"  Installing optional: {pkg} …")
            ok = _pip_install(pkg, timeout=180)
            if not ok:
                log.warning(f"  Optional package {pkg} skipped — pipeline continues")
