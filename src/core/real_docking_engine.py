"""
================================================================================
CEREBRO-X |  REAL AUTODOCK VINA DOCKING ENGINE
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Real molecular docking using AutoDock Vina 1.2.7 (official Python API).
Replaces the LIE approximation with genuine docking energies.

Workflow:
  1. Fetch receptor PDB from RCSB (using Target PDB ID from Excel input)
  2. Prepare receptor: add hydrogens, remove water, convert to PDBQT
  3. Prepare ligand: SMILES → 3D conformer (RDKit) → PDBQT
  4. Run AutoDock Vina (local, no server)
  5. Parse best pose ΔG (kcal/mol) → Kd
  6. Fallback to LIE if any step fails (graceful degradation)

References:
  Eberhardt J et al. (2021) AutoDock Vina 1.2.0. J Chem Inf Model.
  Trott O & Olson AJ (2010) AutoDock Vina. J Comput Chem 31:455.
================================================================================
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

log = logging.getLogger("CEREBRO-DOCKING")

_PDB_ID_RE = re.compile(r"^[A-Za-z0-9]{4}$")

# ─── Fallback LIE binding estimate (used when Vina unavailable) ─────────────
def _lie_estimate(ligand_mw: float, logp: float, tpsa: float,
                   hbd: int, hba: int, is_peptide: bool) -> dict:
    """LIE approximation — only used as fallback."""
    alpha = 0.181; beta = 0.137
    delta_G = -(alpha * logp + beta * (50 - tpsa/5) + 0.5 * (hbd + hba) * 0.3)
    delta_G = max(-20, min(-1, delta_G))
    # ΔG = RT·ln(Kd), R=1.987e-3 kcal/(mol·K) — same constant and units
    # already used for this identical conversion in run_autodock_vina below.
    # This used to divide by (8.314 * 310): 8.314 is the SI gas constant in
    # J/(mol·K), mismatched against delta_G*1000 (kcal/mol converted to
    # cal/mol) — mixing joules and calories without converting between them
    # (1 cal = 4.184 J) understated the exponent by that same ~4.18x factor,
    # which compounds inside exp() into a Kd wrong by 3-8 orders of
    # magnitude across the realistic ΔG range, always landing in the
    # "Weak (>1µM)" bucket regardless of how strong the real binding was.
    RT = 1.987e-3 * 310  # kcal/mol
    Kd_M = math.exp(delta_G / RT)
    Kd_nM = Kd_M * 1e9
    return {
        "docking_method":      "LIE approximation (fallback — Vina unavailable)",
        "delta_G_kcal_mol":    round(delta_G, 2),
        "Kd_nM":               round(Kd_nM, 3),
        "Kd_class":            ("Tight (<10nM)" if Kd_nM < 10 else
                                 "Moderate (10-1000nM)" if Kd_nM < 1000 else "Weak (>1µM)"),
        "vina_score_kcal_mol": None,
        "n_poses":             0,
        "receptor_pdb":        None,
        "confidence":          "LOW — LIE approximation only",
        "reference":           "",
    }


def _fetch_pdb(pdb_id: str, out_path: Path) -> bool:
    """Download PDB structure from RCSB."""
    import urllib.request
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.pdb"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req, timeout=12) as r:
            data = r.read()
        out_path.write_bytes(data)
        log.info(f"[DOCK] Downloaded PDB: {pdb_id} ({len(data)//1024} KB)")
        return True
    except Exception as e:
        log.warning(f"[DOCK] PDB fetch failed ({pdb_id}): {e}")
        return False


def _prepare_receptor_pdbqt(pdb_path: Path, pdbqt_path: Path) -> bool:
    """
    Convert PDB receptor to PDBQT format.
    Uses a minimal approach: remove HETATM (water/ligands), keep ATOM lines,
    then use Vina's built-in receptor preparation.
    """
    try:
        lines = pdb_path.read_text(errors='replace').splitlines()
        # Keep only protein ATOM lines (not water, not ligand HETATM)
        clean_lines = [l for l in lines
                         if l.startswith("ATOM") or l.startswith("TER") or l.startswith("END")]
        clean_pdb = pdb_path.parent / "receptor_clean.pdb"
        clean_pdb.write_text("\n".join(clean_lines))

        # Try using meeko for proper PDBQT preparation
        try:
            import subprocess
            result = subprocess.run(
                ["mk_prepare_receptor.py", "-i", str(clean_pdb),
                  "-o", str(pdbqt_path), "--add_hydrogen",],
                capture_output=True, text=True, timeout=30)
            if pdbqt_path.exists() and pdbqt_path.stat().st_size > 100:
                log.info(f"[DOCK] Receptor PDBQT via meeko: {pdbqt_path.stat().st_size//1024}KB")
                return True
        except Exception: pass

        # Fallback: create minimal PDBQT from PDB (AutoDock Vina 1.2 can handle PDB directly)
        # Just rename and let Vina parse it
        pdbqt_path.write_text("\n".join(clean_lines) + "\n")
        return True
    except Exception as e:
        log.warning(f"[DOCK] Receptor prep failed: {e}")
        return False


def _prepare_ligand_pdbqt(smiles: str, pdbqt_path: Path,
                             n_conf: int = 10) -> tuple[bool, str]:
    """
    Convert SMILES to 3D PDBQT using RDKit + meeko.
    Returns (success, error_message).
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from rdkit.Chem.rdForceFieldHelpers import MMFFOptimizeMolecule

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False, f"Invalid SMILES: {smiles[:30]}"

        # Add hydrogens and generate 3D conformer
        mol_h = Chem.AddHs(mol)
        AllChem.EmbedMolecule(mol_h, AllChem.ETKDGv3())
        result = MMFFOptimizeMolecule(mol_h)

        # Write SDF
        sdf_path = pdbqt_path.parent / "ligand.sdf"
        writer = Chem.SDWriter(str(sdf_path))
        writer.write(mol_h)
        writer.close()

        # Convert SDF → PDBQT using meeko
        try:
            from meeko import MoleculePreparation
            preparator = MoleculePreparation()
            setup, _ = preparator.prepare(mol_h)
            pdbqt_string = MoleculePreparation.write_pdbqt_string(setup)
            pdbqt_path.write_text(pdbqt_string)
            log.info(f"[DOCK] Ligand PDBQT via meeko: {pdbqt_path.stat().st_size}B")
            return True, ""
        except Exception as me:
            log.debug(f"[DOCK] Meeko failed ({me}), using basic PDBQT")
            # Write minimal PDBQT from atom coords
            pdbqt_lines = [f"REMARK CEREBRO-X ligand {smiles[:40]}"]
            conf = mol_h.GetConformer()
            for i, atom in enumerate(mol_h.GetAtoms()):
                pos = conf.GetAtomPosition(i)
                sym = atom.GetSymbol()
                pdbqt_lines.append(
                    f"ATOM  {i+1:5d}  {sym:<3s} LIG A   1    "
                    f"{pos.x:8.3f}{pos.y:8.3f}{pos.z:8.3f}"
                    f"  1.00  0.00          {sym:>2s}")
            pdbqt_lines.append("TORSDOF 0")
            pdbqt_path.write_text("\n".join(pdbqt_lines))
            return True, ""
    except Exception as e:
        return False, str(e)


def _detect_binding_site(pdb_path: Path) -> tuple[float, float, float, float]:
    """
    Auto-detect binding site center from PDB using geometric center of
    HETATM residues (ligand in crystal structure), or protein centroid fallback.
    Returns (center_x, center_y, center_z, box_size).
    """
    lines = pdb_path.read_text(errors='replace').splitlines()
    # Try HETATM (existing ligand in crystal)
    hetatm_coords = []
    for l in lines:
        if l.startswith("HETATM") and "HOH" not in l:
            try:
                x, y, z = float(l[30:38]), float(l[38:46]), float(l[46:54])
                hetatm_coords.append((x, y, z))
            except: pass

    if hetatm_coords:
        cx = sum(c[0] for c in hetatm_coords) / len(hetatm_coords)
        cy = sum(c[1] for c in hetatm_coords) / len(hetatm_coords)
        cz = sum(c[2] for c in hetatm_coords) / len(hetatm_coords)
        box = 20.0  # angstroms
        log.info(f"[DOCK] Binding site from HETATM: ({cx:.1f},{cy:.1f},{cz:.1f}) box={box}Å")
        return cx, cy, cz, box

    # Fallback: geometric center of all ATOM records
    atom_coords = []
    for l in lines:
        if l.startswith("ATOM"):
            try:
                x, y, z = float(l[30:38]), float(l[38:46]), float(l[46:54])
                atom_coords.append((x, y, z))
            except: pass

    if atom_coords:
        cx = sum(c[0] for c in atom_coords) / len(atom_coords)
        cy = sum(c[1] for c in atom_coords) / len(atom_coords)
        cz = sum(c[2] for c in atom_coords) / len(atom_coords)
        return cx, cy, cz, 25.0  # larger box for blind docking
    return 0.0, 0.0, 0.0, 30.0


def run_autodock_vina(smiles: str, pdb_id: str,
                        output_dir: Path,
                        mol_profile: dict,
                        n_poses: int = 9,
                        exhaustiveness: int = 8) -> dict:
    """
    Run real AutoDock Vina docking.

    Parameters:
      smiles:       Drug SMILES string
      pdb_id:       Target receptor PDB ID (e.g. "2NAO")
      output_dir:   Directory to save docking files
      mol_profile:  Drug molecular properties (for fallback)
      n_poses:      Number of binding poses to generate
      exhaustiveness: Vina exhaustiveness (8=default, 32=high accuracy)

    Returns:
      Dict with docking results including best ΔG (kcal/mol) and Kd (nM)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mw    = float(mol_profile.get("MW_Da", 300) or 300)
    logp  = float(mol_profile.get("LogP", 2) or 2)
    tpsa  = float(mol_profile.get("TPSA_A2") or mol_profile.get("TPSA", 80) or 80)
    hbd   = int(mol_profile.get("HBD") or 2)
    hba   = int(mol_profile.get("HBA") or 4)
    is_bio= str(mol_profile.get("molecule_class","")).lower() in ("biologic","protein","antibody")

    # Biologics can't be docked with Vina — use LIE
    if is_bio or mw > 2000:
        log.info(f"[DOCK] Biologic/large MW={mw:.0f} — using LIE approximation")
        result = _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)
        result["note"] = "Biologic molecules (MW>2000 Da) cannot be docked with AutoDock Vina"
        return result

    # No SMILES → fallback
    if not smiles or len(smiles) < 3:
        log.warning("[DOCK] No valid SMILES — LIE fallback")
        return _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)

    # No/invalid PDB ID → LIE fallback. Strict alphanumeric-4 check (not just
    # length) since pdb_id is interpolated into both a download URL and a
    # local filesystem path below — an unvalidated value like "../x" would
    # pass a length-only check and write outside output_dir.
    if not pdb_id or not _PDB_ID_RE.match(pdb_id):
        log.warning(f"[DOCK] No valid PDB ID ({pdb_id!r}) — LIE fallback")
        result = _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)
        result["note"] = "No valid Target PDB ID provided. Enter a 4-character alphanumeric PDB ID in Excel for real docking."
        return result

    try:
        from vina import Vina

        pdb_path    = output_dir / f"{pdb_id}.pdb"
        rec_pdbqt   = output_dir / "receptor.pdbqt"
        lig_pdbqt   = output_dir / "ligand.pdbqt"
        out_pdbqt   = output_dir / "docking_out.pdbqt"

        # Step 1: Download receptor
        if not pdb_path.exists():
            if not _fetch_pdb(pdb_id, pdb_path):
                return _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)

        # Step 2: Prepare receptor
        if not rec_pdbqt.exists():
            _prepare_receptor_pdbqt(pdb_path, rec_pdbqt)
        if not rec_pdbqt.exists():
            return _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)

        # Step 3: Prepare ligand
        ok, err = _prepare_ligand_pdbqt(smiles, lig_pdbqt)
        if not ok:
            log.warning(f"[DOCK] Ligand prep failed: {err}")
            return _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)

        # Step 4: Detect binding site
        cx, cy, cz, box = _detect_binding_site(pdb_path)

        # Step 5: Run AutoDock Vina
        v = Vina(sf_name="vina", cpu=2, verbosity=0)
        v.set_receptor(str(rec_pdbqt))
        v.set_ligand_from_file(str(lig_pdbqt))
        v.compute_vina_maps(center=[cx, cy, cz],
                              box_size=[box, box, box])
        v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)

        # Step 6: Parse results
        energies = v.energies(n_poses=n_poses)
        poses_dG = [float(e[0]) for e in energies if e[0] is not None]

        if not poses_dG:
            log.warning("[DOCK] Vina returned no poses — LIE fallback")
            return _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)

        best_dG = min(poses_dG)  # most negative = strongest binding

        # Convert ΔG → Kd: ΔG = RT·ln(Kd), R=1.987 cal/mol/K, T=310K
        RT  = 1.987e-3 * 310  # kcal/mol
        Kd_M  = math.exp(best_dG / RT)
        Kd_nM = Kd_M * 1e9

        # Save docking output
        v.write_poses(str(out_pdbqt), n_poses=n_poses)
        poses_summary = [{"rank": i+1, "dG_kcal_mol": round(e, 2)} for i, e in enumerate(poses_dG)]

        result = {
            "docking_method":      "AutoDock Vina 1.2.7 (real docking)",
            "receptor_pdb":        pdb_id,
            "binding_site_center": [round(cx,2), round(cy,2), round(cz,2)],
            "box_size_A":          round(box, 1),
            "vina_score_kcal_mol": round(best_dG, 2),
            "delta_G_kcal_mol":    round(best_dG, 2),
            "Kd_nM":               round(Kd_nM, 3),
            "Kd_class":            ("Tight (<10nM)" if Kd_nM < 10 else
                                     "Moderate (10-1000nM)" if Kd_nM < 1000 else "Weak (>1µM)"),
            "n_poses":             len(poses_dG),
            "all_poses_dG":        [round(e,2) for e in poses_dG],
            "poses_summary":       poses_summary[:5],
            "exhaustiveness":      exhaustiveness,
            "confidence":          "HIGH — real AutoDock Vina docking on experimental receptor structure",
            "reference":           "",
            "output_pdbqt":        str(out_pdbqt),
        }
        log.info(f"[DOCK] ✅ Real Vina docking: ΔG={best_dG:.2f} kcal/mol | Kd={Kd_nM:.1f}nM | {len(poses_dG)} poses")
        return result

    except Exception as e:
        log.warning(f"[DOCK] Vina failed ({e}) — LIE fallback")
        import traceback; log.debug(traceback.format_exc())
        result = _lie_estimate(mw, logp, tpsa, hbd, hba, is_bio)
        result["vina_error"] = str(e)
        return result