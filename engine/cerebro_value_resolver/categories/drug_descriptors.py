"""
================================================================================
CEREBRO-X | categories/drug_descriptors.py
================================================================================
PRIORITY 1 — basic physicochemical descriptors.

Categories registered:
    drug_logp           — Crippen-Wildman LogP
    drug_mw             — molecular weight (Da)
    drug_tpsa           — topological polar surface area (Å²)
    drug_hbd            — H-bond donors (Lipinski)
    drug_hba            — H-bond acceptors (Lipinski)
    drug_rotbonds       — rotatable bonds
    drug_aromatic_rings — aromatic ring count
    drug_formal_charge  — net formal charge
    drug_stereocenters  — number of CIP-assigned stereocenters
================================================================================
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from collections.abc import Callable

from .._core import (
    _HAS_RDKIT,
    _HAS_REQUESTS,
    _HAS_THERMO,
    _resolved,
    cached_safe_get,
    register,
)
from ..computations import ghose_crippen_logp_atomic

log = logging.getLogger("CEREBRO-RESOLVER.descriptors")


# ──────────────────────────────────────────────────────────────────────────
# Generic PubChem property fetcher (any descriptor)
# ──────────────────────────────────────────────────────────────────────────
def _pubchem_property(name: str, smiles: str, prop: str) -> float | None:
    """prop ∈ {XLogP, MolecularWeight, TPSA, HBondDonorCount,
              HBondAcceptorCount, RotatableBondCount, MolecularFormula,
              CanonicalSMILES, Charge}"""
    if name:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"name/{enc}/property/{prop}/JSON")
        if txt:
            try:
                d = json.loads(txt)
                props = d.get("PropertyTable", {}).get("Properties", [])
                if props and prop in props[0] and props[0][prop] is not None:
                    return float(props[0][prop])
            except Exception: pass
    if smiles and _HAS_RDKIT:
        try:
            from rdkit import Chem
            mol = Chem.MolFromSmiles(smiles)
            if mol is not None:
                ikey = Chem.MolToInchiKey(mol)
                txt = cached_safe_get(
                    f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                    f"inchikey/{ikey}/property/{prop}/JSON")
                if txt:
                    d = json.loads(txt)
                    props = d.get("PropertyTable", {}).get("Properties", [])
                    if props and prop in props[0] and props[0][prop] is not None:
                        return float(props[0][prop])
        except Exception: pass
    return None


def _chembl_property(name: str, key: str) -> float | None:
    """key ∈ {alogp, full_mwt, psa, hbd, hba, rtb, aromatic_rings, full_molformula}"""
    if not name or not _HAS_REQUESTS: return None
    enc = urllib.parse.quote(name)
    txt = cached_safe_get(
        f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
        f"pref_name__iexact={enc}&limit=1")
    if not txt: return None
    try:
        d = json.loads(txt)
        mols = d.get("molecules", [])
        if mols:
            props = mols[0].get("molecule_properties") or {}
            v = props.get(key)
            if v is not None:
                try: return float(v)
                except: pass
    except Exception: pass
    return None


# ──────────────────────────────────────────────────────────────────────────
# RDKit Tier-3 dispatchers
# ──────────────────────────────────────────────────────────────────────────
def _rdkit_descriptor(smiles: str, name: str) -> dict | None:
    if not (smiles and _HAS_RDKIT): return None
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None: return None
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        n_stereo = sum(1 for a in mol.GetAtoms() if a.HasProp('_CIPCode'))
        return {
            "MW_Da":         float(Descriptors.MolWt(mol)),
            "LogP":          float(Crippen.MolLogP(mol)),
            "TPSA_A2":       float(Descriptors.TPSA(mol)),
            "HBD":           int(Lipinski.NumHDonors(mol)),
            "HBA":           int(Lipinski.NumHAcceptors(mol)),
            "RotBonds":      int(Lipinski.NumRotatableBonds(mol)),
            "AromaticRings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
            "FormalCharge":  int(Chem.GetFormalCharge(mol)),
            "Stereocenters": int(n_stereo),
        }
    except Exception as e:
        log.debug(f"[RDKit-desc] {smiles[:30]}: {e}")
        return None


def _thermo_descriptor(name: str, key: str) -> float | None:
    """key ∈ {logP, MW, atom_count}"""
    if not _HAS_THERMO or not name: return None
    try:
        from thermo import Chemical
        c = Chemical(name)
        if key == "logP" and c.logP is not None: return float(c.logP)
        if key == "MW" and c.MW is not None: return float(c.MW)
    except Exception: pass
    return None


# ──────────────────────────────────────────────────────────────────────────
# Biologic / oligonucleotide MW computation (Tier 4 — sequence sum)
# ──────────────────────────────────────────────────────────────────────────
# Average residue masses (Da) — IUPAC recommendations (Tarini 2008, Anal Chem 80:4789)
_AA_AVG_MASS = {
    "A": 89.09,  "R": 174.20, "N": 132.12, "D": 133.10, "C": 121.16,
    "E": 147.13, "Q": 146.15, "G": 75.07,  "H": 155.16, "I": 131.17,
    "L": 131.17, "K": 146.19, "M": 149.21, "F": 165.19, "P": 115.13,
    "S": 105.09, "T": 119.12, "W": 204.23, "Y": 181.19, "V": 117.15,
}
_WATER_MASS = 18.015     # subtracted per peptide bond
_PEPTIDE_BOND_DELTA = 18.015

# Average nucleotide masses (Da) — DNA (deoxyribonucleotide monophosphate)
_DNA_AVG_MASS = {
    "A": 313.21, "T": 304.20, "G": 329.21, "C": 289.18, "U": 306.17,
}
# RNA (ribonucleotide monophosphate)
_RNA_AVG_MASS = {
    "A": 329.21, "U": 306.17, "G": 345.21, "C": 305.18, "T": 320.20,
}
# 2'-MOE phosphorothioate modification adds ~88 Da per nucleotide vs DNA
# (used by Nusinersen, Inotersen, etc.)
_MOE_PS_DELTA = 88.0


def _biologic_mw_from_fasta(fasta: str) -> float | None:
    """Compute biologic MW from FASTA via summed average residue masses.

    For an n-residue protein:
        MW = Σ(residue_avg_mass) - (n-1) × H₂O
        (each peptide bond formation releases one water)

    NOTE: For full mAbs (which have 2 heavy + 2 light chains + glycosylation),
    a single VH FASTA underestimates MW by ~10×. If the sequence is short
    (<200 aa) but the molecule is labeled monoclonal_antibody, return None
    so a higher-tier source can override.
    """
    if not fasta:
        return None
    # Strip FASTA header, whitespace, common boilerplate
    seq = "".join(c for c in fasta.upper()
                    if c in "ACDEFGHIKLMNPQRSTVWY")
    if len(seq) < 5:
        return None
    total = sum(_AA_AVG_MASS.get(aa, 110.0) for aa in seq)
    n_bonds = max(0, len(seq) - 1)
    mw = total - n_bonds * _WATER_MASS
    return float(mw)


def _oligonucleotide_mw_from_sequence(sequence: str,
                                          modification: str = "DNA"
                                          ) -> float | None:
    """Compute oligonucleotide MW from sequence.

    Args:
        sequence: nucleotide string (ACGTU + IUPAC)
        modification: "DNA" | "RNA" | "MOE_PS" (2'-MOE phosphorothioate)

    For an n-mer oligonucleotide:
        MW ≈ Σ(nucleotide_avg_mass) - (n-1) × H₂O + (terminal phosphate adjustment)
        For 2'-MOE PS: add ~88 Da per nucleotide for 2'-O-methoxyethyl + sulphur
    """
    if not sequence:
        return None
    seq = "".join(c for c in sequence.upper() if c in "ACGTUN")
    if len(seq) < 3:
        return None

    # Detect modification automatically from name hints in caller, but default
    # to DNA-like (most ASOs are PS-DNA backbone)
    mw_table = _RNA_AVG_MASS if "U" in seq and "T" not in seq else _DNA_AVG_MASS
    total = sum(mw_table.get(nt, 309.0) for nt in seq)
    n_bonds = max(0, len(seq) - 1)
    mw = total - n_bonds * _WATER_MASS
    # Add terminal hydroxyl/phosphate
    mw += 79.98     # one terminal phosphate group (PO₄H₃ minus H)

    # Modification correction
    if modification == "MOE_PS":
        mw += len(seq) * _MOE_PS_DELTA

    return float(mw)



def _build_descriptor_resolver(category: str,
                                 pubchem_prop: str | None,
                                 chembl_key: str | None,
                                 rdkit_key: str | None,
                                 thermo_key: str | None,
                                 tier7_fn: Callable | None,
                                 default_value: float,
                                 reference_t3: str,
                                 unit: str = "",
                                 supports_biologic: bool = False):
    """Generic resolver builder. Returns a closure that runs the
    full 7-tier cascade for one descriptor.

    Args:
        supports_biologic: if True, the descriptor can be computed from
            FASTA (biologics) or sequence (oligos) at Tier 4 via
            _biologic_mw_from_fasta / _oligonucleotide_mw_from_sequence.
            Currently only `drug_mw` and `drug_logp` use this — most
            descriptors (HBD, HBA, TPSA, aromatic_rings) don't apply
            to proteins/oligos in any meaningful way.
    """
    def resolver(name: str = "", smiles: str = "",
                  fasta: str = "", sequence: str = "",
                  molecule_class: str = "",
                  researcher_override: float | None = None,
                  **kwargs) -> dict:
        db_misses: list[str] = []

        if researcher_override is not None:
            return _resolved(
                value=float(researcher_override), tier=0,
                source="researcher_override",
                method="User-provided value via Excel input",
                reference="Researcher input — accepted as-given",
                live_db_misses=[])

        # Tier 1a: PubChem
        if pubchem_prop:
            try:
                v = _pubchem_property(name, smiles, pubchem_prop)
                if v is not None:
                    return _resolved(
                        value=v, tier=1, source=f"PubChem.{pubchem_prop}",
                        method=f"Live PubChem REST property fetch ({pubchem_prop})",
                        reference="",
                        live_db_misses=db_misses)
            except Exception: pass
            db_misses.append(f"PubChem.{pubchem_prop}")

        # Tier 1b: ChEMBL
        if chembl_key:
            try:
                v = _chembl_property(name, chembl_key)
                if v is not None:
                    return _resolved(
                        value=v, tier=1, source=f"ChEMBL.{chembl_key}",
                        method=f"Live ChEMBL REST property fetch ({chembl_key})",
                        reference="",
                        live_db_misses=db_misses)
            except Exception: pass
            db_misses.append(f"ChEMBL.{chembl_key}")

        # Tier 3: RDKit (small molecules only — needs SMILES)
        if rdkit_key:
            try:
                desc = _rdkit_descriptor(smiles, name)
                if desc and rdkit_key in desc:
                    return _resolved(
                        value=desc[rdkit_key], tier=3, source=f"RDKit.{rdkit_key}",
                        method=f"RDKit cheminformatics: {rdkit_key}",
                        reference=reference_t3,
                        live_db_misses=db_misses)
            except Exception: pass
            db_misses.append(f"RDKit.{rdkit_key}")

        # Tier 4: Biologic / oligonucleotide sequence-sum (only for compatible categories)
        # This is what handles Lecanemab (FASTA) and Nusinersen (oligo sequence)
        # for the drug_mw category.
        if supports_biologic and category == "drug_mw":
            if fasta:
                v = _biologic_mw_from_fasta(fasta)
                if v is not None:
                    # Sanity check: if molecule_class indicates full mAb but
                    # FASTA is too short to be the full antibody, flag with
                    # an additive correction note (full IgG ≈ 4× single VH chain)
                    is_full_mab = (molecule_class or "").lower() in (
                        "monoclonal_antibody", "mab", "antibody")
                    n_aa = len(fasta.replace(">","").replace("\n","").strip())
                    extra: dict = {"residue_count": n_aa}
                    method_note = ("Sequence-sum biologic MW: "
                                     f"Σ(residue_avg_mass × {n_aa}) − (n−1)·H₂O. "
                                     "Average residue masses from IUPAC Tarini 2008.")
                    if is_full_mab and n_aa < 400:
                        # Only one chain provided; full mAb has 2H + 2L = ~1,300 aa
                        extra["warning"] = (
                            f"FASTA contains {n_aa} aa, but molecule_class is "
                            f"'monoclonal_antibody' (typical full mAb ≈ 1,300 aa, "
                            f"~150 kDa). MW reported is for the provided fragment "
                            f"only. For full IgG estimation, multiply by ~"
                            f"{int(1300/max(n_aa,1))}× or provide complete sequence.")
                        extra["estimated_full_mab_MW_Da"] = round(v * (1300 / max(n_aa, 1)), 0)
                    return _resolved(
                        value=v, tier=4,
                        source="cerebro_value_resolver:biologic_seq_sum",
                        method=method_note,
                        reference="",
                        live_db_misses=db_misses,
                        extra=extra)
                db_misses.append("biologic_seq_sum:fasta")

            if sequence:
                # Detect modification from molecule_class OR drug name
                modification = "DNA"
                mc = (molecule_class or "").lower()
                nm = (name or "").lower()
                # Nusinersen, Inotersen, Tofersen — known 2'-MOE PS ASOs
                # Generic ASO without explicit hint → assume PS-DNA backbone
                # (most marketed ASOs are PS-modified)
                known_moe_ps = ("nusinersen", "inotersen", "tofersen", "mipomersen",
                                  "volanesorsen", "patisiran")
                if "moe" in mc or "phosphoroth" in mc or any(k in nm for k in known_moe_ps):
                    modification = "MOE_PS"
                elif "rna" in mc or "sirna" in mc or "mrna" in mc:
                    modification = "RNA"
                elif "aso" in mc or "antisense" in mc or "gapmer" in mc:
                    # Generic ASO defaults to PS-DNA (~10% MW boost from S replacing O)
                    modification = "MOE_PS"
                v = _oligonucleotide_mw_from_sequence(sequence, modification=modification)
                if v is not None:
                    n_nt = len(sequence.replace(">","").replace("\n","").strip())
                    return _resolved(
                        value=v, tier=4,
                        source="cerebro_value_resolver:oligo_seq_sum",
                        method=(f"Sequence-sum oligonucleotide MW: "
                                  f"Σ(nucleotide_avg_mass × {n_nt}) − "
                                  f"(n−1)·H₂O + terminal phosphate "
                                  f"(modification: {modification}). "),
                        reference="",
                        live_db_misses=db_misses,
                        extra={"nucleotide_count": n_nt,
                                "modification": modification})
                db_misses.append("oligo_seq_sum:sequence")

        # Tier 5: thermo
        if thermo_key:
            try:
                v = _thermo_descriptor(name, thermo_key)
                if v is not None:
                    return _resolved(
                        value=v, tier=5, source=f"thermo.{thermo_key}",
                        method=f"thermo.Chemical.{thermo_key}",
                        reference="",
                        live_db_misses=db_misses)
            except Exception: pass
            db_misses.append(f"thermo.{thermo_key}")

        # Tier 7: pure-math
        if tier7_fn:
            try:
                v = tier7_fn(smiles)
                if v is not None:
                    return _resolved(
                        value=float(v), tier=7,
                        source="cerebro_value_resolver:pure_math",
                        method=f"Pure-math first-principles ({tier7_fn.__name__})",
                        reference="See computations/group_contribution.py",
                        live_db_misses=db_misses)
            except Exception: pass
            db_misses.append("pure_math")

        # Final fallback
        return _resolved(
            value=default_value, tier=7,
            source="cerebro_value_resolver:class_typical_mean",
            method=f"Class-typical mean for small molecules ({unit})",
            reference="",
            live_db_misses=db_misses,
            extra={"confidence": "LOW",
                    "warning": "ALL tiers failed — class mean returned."})
    resolver.__name__ = f"resolve_{category}"
    return register(category)(resolver)


# ──────────────────────────────────────────────────────────────────────────
# Pure-math tier-7 helpers
# ──────────────────────────────────────────────────────────────────────────
def _t7_mw(smiles: str) -> float | None:
    """Sum of atomic weights from SMILES tokenization."""
    if not smiles: return None
    ATOMIC_WT = {
        "C":12.011,"c":12.011,"N":14.007,"n":14.007,"O":15.999,"o":15.999,
        "S":32.06,"s":32.06,"F":18.998,"Cl":35.453,"Br":79.904,"I":126.904,
        "P":30.974,"H":1.008,"Si":28.086,
    }
    from ..computations.group_contribution import _tokenize_smiles_to_atoms
    atoms = _tokenize_smiles_to_atoms(smiles)
    if not atoms: return None
    mw = sum(ATOMIC_WT.get(a, 12.0) for a in atoms)
    # Add ~1 H per heavy atom for missing-H estimation in pure-math fallback
    n_heavy = sum(1 for a in atoms if a.upper() != "H")
    mw += n_heavy * 1.008  # rough Hs
    return round(mw, 2)


def _t7_tpsa(smiles: str) -> float | None:
    """Approximate TPSA from polar atom count (Ertl 2000 approximation).
    Each O ≈ 9 Å², each N ≈ 12 Å², charge correction +6 each.
    """
    if not smiles: return None
    from ..computations.group_contribution import _tokenize_smiles_to_atoms
    atoms = _tokenize_smiles_to_atoms(smiles)
    if not atoms: return None
    tpsa = sum(9.0 if a in ("O","o") else
                 12.0 if a in ("N","n") else
                 0.0 for a in atoms)
    return round(tpsa, 1)


def _t7_hbd(smiles: str) -> float | None:
    """Count -OH and -NH from SMILES patterns."""
    if not smiles: return None
    n = smiles.count("OH") + smiles.count("NH") + smiles.count("[nH]")
    return float(n)


def _t7_hba(smiles: str) -> float | None:
    """Count N + O atoms (Lipinski definition includes all)."""
    if not smiles: return None
    return float(smiles.count("O") + smiles.count("o")
                  + smiles.count("N") + smiles.count("n"))


def _t7_rotbonds(smiles: str) -> float | None:
    """Approximate single-bond C-C/C-N/C-O count outside rings."""
    if not smiles: return None
    n = smiles.count("CC") + smiles.count("CN") + smiles.count("CO") \
         + smiles.count("CS")
    # Penalty for ring closures (~30% of single bonds are intra-ring)
    return float(max(0, int(n * 0.7)))


def _t7_arom_rings(smiles: str) -> float | None:
    """Aromatic ring count: count distinct ring closures involving lowercase
    aromatic atoms (c, n, o, s)."""
    if not smiles: return None
    n_arom_atoms = sum(1 for c in smiles if c in "cnos")
    return float(int(n_arom_atoms / 6))   # rings of 6


def _t7_formal_charge(smiles: str) -> float | None:
    if not smiles: return None
    return float(smiles.count("+") - smiles.count("-"))


def _t7_stereo(smiles: str) -> float | None:
    if not smiles: return None
    return float(smiles.count("@") - smiles.count("@@"))   # rough


# ──────────────────────────────────────────────────────────────────────────
# Register all 9 descriptor resolvers via the factory
# ──────────────────────────────────────────────────────────────────────────
_build_descriptor_resolver(
    "drug_logp",
    pubchem_prop="XLogP", chembl_key="alogp",
    rdkit_key="LogP", thermo_key="logP",
    tier7_fn=ghose_crippen_logp_atomic,
    default_value=2.5,
    reference_t3="",
    unit="dimensionless")

_build_descriptor_resolver(
    "drug_mw",
    pubchem_prop="MolecularWeight", chembl_key="full_mwt",
    rdkit_key="MW_Da", thermo_key="MW",
    tier7_fn=_t7_mw,
    default_value=350.0,
    reference_t3="RDKit Descriptors.MolWt (atomic weight summation)",
    unit="g/mol (Da)",
    supports_biologic=True)

_build_descriptor_resolver(
    "drug_tpsa",
    pubchem_prop="TPSA", chembl_key="psa",
    rdkit_key="TPSA_A2", thermo_key=None,
    tier7_fn=_t7_tpsa,
    default_value=60.0,
    reference_t3="",
    unit="Å²")

_build_descriptor_resolver(
    "drug_hbd",
    pubchem_prop="HBondDonorCount", chembl_key="hbd",
    rdkit_key="HBD", thermo_key=None,
    tier7_fn=_t7_hbd,
    default_value=2.0,
    reference_t3="",
    unit="count")

_build_descriptor_resolver(
    "drug_hba",
    pubchem_prop="HBondAcceptorCount", chembl_key="hba",
    rdkit_key="HBA", thermo_key=None,
    tier7_fn=_t7_hba,
    default_value=5.0,
    reference_t3="",
    unit="count")

_build_descriptor_resolver(
    "drug_rotbonds",
    pubchem_prop="RotatableBondCount", chembl_key="rtb",
    rdkit_key="RotBonds", thermo_key=None,
    tier7_fn=_t7_rotbonds,
    default_value=5.0,
    reference_t3="",
    unit="count")

_build_descriptor_resolver(
    "drug_aromatic_rings",
    pubchem_prop=None, chembl_key="aromatic_rings",
    rdkit_key="AromaticRings", thermo_key=None,
    tier7_fn=_t7_arom_rings,
    default_value=1.0,
    reference_t3="RDKit rdMolDescriptors.CalcNumAromaticRings",
    unit="count")

_build_descriptor_resolver(
    "drug_formal_charge",
    pubchem_prop="Charge", chembl_key=None,
    rdkit_key="FormalCharge", thermo_key=None,
    tier7_fn=_t7_formal_charge,
    default_value=0.0,
    reference_t3="RDKit Chem.GetFormalCharge",
    unit="e")

_build_descriptor_resolver(
    "drug_stereocenters",
    pubchem_prop=None, chembl_key=None,
    rdkit_key="Stereocenters", thermo_key=None,
    tier7_fn=_t7_stereo,
    default_value=0.0,
    reference_t3="RDKit AssignStereochemistry + CIP code count",
    unit="count")
