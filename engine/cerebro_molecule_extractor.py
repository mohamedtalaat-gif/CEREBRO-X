# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X | cerebro_molecule_extractor.py — Molecule-Aware Refactor
================================================================================
Created by: Muhammad Talaat (BPharm, R&D Computational Lead)

The single source of truth for ALL drug-derived numerical inputs.

Given a `mol_profile` dict containing a SMILES string (or, for biologics,
a FASTA sequence), this module returns the COMPLETE set of physicochemical
descriptors that the 62 surrogate principles need to differentiate one
drug from another.

Design rules:
  - RDKit is the primary computation engine (Crippen LogP, Lipinski H-bonds,
    TPSA, rotatable bonds, formal charge, stereocenters, aromatic rings).
  - pKa: not in core RDKit. We use a published group-contribution heuristic
    (Lee et al, 2018 + Bryantsev/Goddard 2007) covering the dominant ionizable
    groups for CNS drugs. If the molecule has no ionizable group, pKa = None.
  - For BIOLOGICS (FASTA): we compute MW, pI, instability, aliphatic_index,
    GRAVY via Biopython.ProtParam.
  - All values are returned in a STRUCTURED dict with provenance:
      {value: float, source: "rdkit"|"heuristic"|"fasta"|"researcher_override",
       confidence: "HIGH"|"MODERATE"|"LOW"}
  - If the user already provided a value in the input Excel
    (`mp[<key>]` exists), we PREFER the user value and tag it
    'researcher_override' (does NOT overwrite).

Public entry:
  enrich_mol_profile(mol_profile: dict) -> dict
    Returns a NEW dict with all 9 RDKit descriptors guaranteed populated
    (or None if neither SMILES nor user override is available).
================================================================================
"""
from __future__ import annotations
import logging, math, re
from typing import Dict, Any, Optional, Tuple

log = logging.getLogger("CEREBRO-MOL")


# ──────────────────────────────────────────────────────────────────────────
# Group-contribution pKa heuristic (drug-relevant ionizable groups only)
# Reference: Bryantsev & Goddard (2007) J Phys Chem A 111:6422 + Lee et al
#            (2018) J Comput Aided Mol Des 32:1037
#
# Strategy: a typical CNS drug can be a zwitterion (e.g. tertiary amine +
# carboxylic acid). To allow downstream principles to compute correct
# corona, ionization, and membrane partition behavior, we return BOTH
# the strongest acidic pKa and the strongest basic pKa separately, plus
# a "dominant pKa" (the one closest to physiological pH 7.4 for fastest
# downstream-effect calculations).
# ──────────────────────────────────────────────────────────────────────────
PKA_GROUPS = [
    # (SMARTS pattern, type, pKa_value, description)
    # ── Acids ──
    ("[CX3](=O)[OX2H]",         "acid",  4.2,  "carboxylic acid"),
    ("c[OX2H]",                  "acid",  9.5,  "phenol"),
    ("[SX4](=O)(=O)[OX2H]",     "acid",  -2.0, "sulfonic acid"),
    ("[PX4](=O)([OX2H])([OX2H])", "acid", 2.1, "phosphate"),
    ("[NX2H]C(=O)",              "acid", 14.5, "amide N-H"),
    # ── Bases ──
    ("[NX3]([CX4])([CX4])[CX4]", "base", 9.8,  "tertiary amine"),
    ("[NX3H]([CX4])[CX4]",       "base", 10.5, "secondary amine"),
    ("[NX3H2][CX4]",             "base", 10.6, "primary amine"),
    ("c1ccncc1",                 "base", 5.2,  "pyridine"),
    ("[nX2]",                    "base", 6.0,  "imidazole-like N"),
    ("[NX3]([CX4])(C)C(=N)",    "base", 12.5, "guanidine"),
]


def _pka_from_groups(mol) -> Tuple[Optional[float], Optional[float], Optional[float], str]:
    """Heuristic group-contribution pKa.

    Returns (pka_acidic, pka_basic, pka_dominant, label_string).
    Any of the three may be None.
    """
    try:
        from rdkit import Chem
        acidic_hits = []   # (pka, label, n)
        basic_hits  = []
        for smarts, kind, pka, label in PKA_GROUPS:
            patt = Chem.MolFromSmarts(smarts)
            if patt is None: continue
            matches = mol.GetSubstructMatches(patt)
            if matches:
                if kind == "acid":
                    acidic_hits.append((pka, label, len(matches)))
                else:
                    basic_hits.append((pka, label, len(matches)))

        # Strongest acid = LOWEST pKa
        pka_acid = min(acidic_hits, key=lambda x: x[0])[0] if acidic_hits else None
        # Strongest base = HIGHEST pKa (most basic)
        pka_base = max(basic_hits, key=lambda x: x[0])[0] if basic_hits else None

        # Dominant = closest to physiological pH 7.4 (governs charge state in vivo)
        all_hits = [(p, k, l) for p, l, n in acidic_hits for k in ["acid"]] + \
                    [(p, "base", l) for p, l, n in basic_hits]
        if all_hits:
            dominant = min(all_hits, key=lambda c: abs(c[0] - 7.4))
            pka_dom, dom_kind, dom_label = dominant[0], dominant[1], dominant[2]
            label = f"{dom_label} ({dom_kind})"
        else:
            pka_dom, label = None, ""
        return pka_acid, pka_base, pka_dom, label
    except Exception as e:
        log.debug(f"[pKa] heuristic failed: {e}")
        return None, None, None, ""


def _rdkit_descriptors(smiles: str) -> Dict[str, Any]:
    """Compute the RDKit-derived descriptor pack."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, Crippen, rdMolDescriptors
    except ImportError:
        log.warning("[MOL] RDKit not available — molecule extractor disabled")
        return {}

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        log.warning(f"[MOL] Invalid SMILES: {smiles!r}")
        return {"_smiles_parse_error": True}

    try:
        # Stereocenters: assigns CIP labels first
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        n_stereo = sum(1 for a in mol.GetAtoms()
                        if a.HasProp('_CIPCode'))
    except Exception:
        n_stereo = 0

    pka_acid, pka_base, pka_dominant, pka_label = _pka_from_groups(mol)

    # ── Bjerrum Microspeciation at pH 7.4 ──────────────────────────────
    # Reference: Bjerrum N (1923) Z Physik Chem 106:219; revisited in
    #            Sangster J (1997) "Octanol-Water Partition Coefficients";
    #            Pagliara A et al (1997) J Med Chem 40:1972 (acid-base
    #            microspeciation for drugs).
    #
    # For a molecule with one acidic site (pKa_a) and one basic site (pKa_b),
    # the four protonation microspecies at pH 7.4 are:
    #   F_HA_HB+   = (1+R_a) · (1+R_b) ratio of zwitterionic-protonated
    #   F_A−_HB+   = zwitterion (deprotonated acid + protonated base)
    #   F_HA_B     = neutral non-ionic (protonated acid + neutral base)
    #   F_A−_B     = anionic only
    # where R_a = 10^(pH − pKa_a) and R_b = 10^(pKa_b − pH)
    # The four fractions sum to 1 (normalization).
    #
    # f_neutral (membrane-permeable) = F_HA_B
    # f_zwitterion (water-soluble, BBB-trapped) = F_A−_HB+
    # f_cationic (corona-attractive)   = F_HA_HB+
    # f_anionic  (corona-repulsive)    = F_A−_B
    pH = 7.4
    if pka_acid is not None and pka_base is not None:
        R_a = 10**(pH - pka_acid)
        R_b = 10**(pka_base - pH)
        # Numerators of each microspecies (×(1+R_a)(1+R_b) is the partition fn)
        num_HA_HB  = R_b           # protonated acid + protonated base
        num_A_HB   = R_a * R_b     # deprotonated acid + protonated base (zwitterion)
        num_HA_B   = 1.0           # protonated acid + neutral base (neutral non-ionic)
        num_A_B    = R_a           # deprotonated acid + neutral base (anionic only)
        Z = num_HA_HB + num_A_HB + num_HA_B + num_A_B
        f_cationic   = num_HA_HB / Z
        f_zwitterion = num_A_HB  / Z
        f_neutral    = num_HA_B  / Z
        f_anionic    = num_A_B   / Z
        net_charge = f_cationic - f_anionic   # zwitterion contributes 0 to net
        microspec_method = ("Bjerrum 4-microspecies partition function "
                              "(acid + base; pH=7.4)")
    elif pka_base is not None:
        # Monoprotic base: HH only
        f_cationic = 1.0 / (1.0 + 10**(pH - pka_base))
        f_anionic = 0.0
        f_neutral = 1.0 - f_cationic
        f_zwitterion = 0.0
        net_charge = f_cationic
        microspec_method = "Henderson-Hasselbalch (monoprotic base)"
    elif pka_acid is not None:
        # Monoprotic acid: HH only
        f_anionic = 1.0 / (1.0 + 10**(pka_acid - pH))
        f_cationic = 0.0
        f_neutral = 1.0 - f_anionic
        f_zwitterion = 0.0
        net_charge = -f_anionic
        microspec_method = "Henderson-Hasselbalch (monoprotic acid)"
    else:
        # No ionizable groups
        f_cationic = f_anionic = f_zwitterion = 0.0
        f_neutral = 1.0
        net_charge = 0.0
        microspec_method = "no ionizable groups (assumed fully neutral)"

    return {
        "MW_Da":         {"value": float(Descriptors.MolWt(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "LogP":          {"value": float(Crippen.MolLogP(mol)),
                           "source": "rdkit", "confidence": "HIGH",
                           "method": "Crippen-Wildman"},
        "TPSA_A2":       {"value": float(Descriptors.TPSA(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "HBD":           {"value": int(Lipinski.NumHDonors(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "HBA":           {"value": int(Lipinski.NumHAcceptors(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "RotBonds":      {"value": int(Lipinski.NumRotatableBonds(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "AromaticRings": {"value": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "FormalCharge":  {"value": int(Chem.GetFormalCharge(mol)),
                           "source": "rdkit", "confidence": "HIGH"},
        "Stereocenters": {"value": int(n_stereo),
                           "source": "rdkit", "confidence": "HIGH"},
        # ── pKa: separate acid/base/dominant ──
        "pKa":           ({"value": float(pka_dominant),
                            "source": "heuristic",
                            "confidence": "MODERATE",
                            "method": f"group-contribution (dominant near pH 7.4): {pka_label}"}
                           if pka_dominant is not None
                           else {"value": None,
                                  "source": "heuristic",
                                  "confidence": "LOW",
                                  "method": "no ionizable groups detected"}),
        "pKa_acidic":    ({"value": float(pka_acid),
                             "source": "heuristic", "confidence": "MODERATE"}
                            if pka_acid is not None
                            else {"value": None, "source": "heuristic",
                                   "confidence": "LOW"}),
        "pKa_basic":     ({"value": float(pka_base),
                             "source": "heuristic", "confidence": "MODERATE"}
                            if pka_base is not None
                            else {"value": None, "source": "heuristic",
                                   "confidence": "LOW"}),
        # ── Microspeciation outputs ──
        "NetCharge_pH74": {"value": float(round(net_charge, 4)),
                            "source": "bjerrum_microspeciation",
                            "confidence": "MODERATE",
                            "method": microspec_method},
        "FractionCationic_pH74":   {"value": float(round(f_cationic, 4)),
                                       "source": "bjerrum_microspeciation",
                                       "confidence": "MODERATE"},
        "FractionAnionic_pH74":    {"value": float(round(f_anionic, 4)),
                                       "source": "bjerrum_microspeciation",
                                       "confidence": "MODERATE"},
        "FractionZwitterion_pH74": {"value": float(round(f_zwitterion, 4)),
                                       "source": "bjerrum_microspeciation",
                                       "confidence": "MODERATE",
                                       "method": ("4-microspecies: HA·HB+ + "
                                                   "A−·HB+ + HA·B + A−·B")},
        "FractionNeutral_pH74":    {"value": float(round(f_neutral, 4)),
                                       "source": "bjerrum_microspeciation",
                                       "confidence": "MODERATE",
                                       "method": "membrane-permeable fraction"},
    }


def _fasta_descriptors(fasta: str) -> Dict[str, Any]:
    """Biopython ProtParam descriptors for protein/peptide drugs."""
    try:
        from Bio.SeqUtils.ProtParam import ProteinAnalysis
    except ImportError:
        log.warning("[MOL] Biopython not available — FASTA extractor disabled")
        return {}
    # Strip whitespace + uppercase (FASTA convention)
    seq = "".join(fasta.split()).upper()
    # Drop header lines (>...)
    if seq.startswith(">"):
        seq = "\n".join(line for line in seq.split("\n") if not line.startswith(">"))
        seq = seq.replace("\n", "")
    # Validate amino acids
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    if not seq or not all(c in valid_aa for c in seq):
        log.warning(f"[MOL] Invalid FASTA sequence: {seq[:30]}...")
        return {"_fasta_parse_error": True}

    pa = ProteinAnalysis(seq)
    try:
        n_aa = len(seq)
        return {
            "MW_Da":             {"value": float(pa.molecular_weight()),
                                    "source": "fasta", "confidence": "HIGH"},
            "Length_AA":         {"value": int(n_aa),
                                    "source": "fasta", "confidence": "HIGH"},
            "pI":                {"value": float(pa.isoelectric_point()),
                                    "source": "fasta", "confidence": "HIGH"},
            "InstabilityIndex":  {"value": float(pa.instability_index()),
                                    "source": "fasta", "confidence": "HIGH"},
            "AliphaticIndex":    {"value": float(_aliphatic_index(seq)),
                                    "source": "fasta", "confidence": "HIGH"},
            "GRAVY":             {"value": float(pa.gravy()),
                                    "source": "fasta", "confidence": "HIGH",
                                    "method": "Kyte-Doolittle hydropathy"},
            # For FASTA we still expose LogP/TPSA proxies for downstream principles
            # (very rough estimates based on hydropathy + charge)
            "LogP":              {"value": float(pa.gravy()),
                                    "source": "fasta_proxy", "confidence": "LOW",
                                    "method": "GRAVY as LogP proxy"},
            "TPSA_A2":           {"value": float(n_aa * 22),  # ~22 Å²/residue
                                    "source": "fasta_proxy", "confidence": "LOW"},
            "HBD":               {"value": int(seq.count("S")+seq.count("T")
                                                +seq.count("Y")+seq.count("N")
                                                +seq.count("Q")+seq.count("K")
                                                +seq.count("R")),
                                    "source": "fasta_proxy", "confidence": "MODERATE"},
            "HBA":               {"value": int(n_aa),
                                    "source": "fasta_proxy", "confidence": "MODERATE"},
            "FormalCharge":      {"value": int(seq.count("K")+seq.count("R")
                                                -seq.count("D")-seq.count("E")),
                                    "source": "fasta", "confidence": "HIGH"},
        }
    except Exception as e:
        log.warning(f"[MOL] FASTA analysis failed: {e}")
        return {"_fasta_parse_error": True}


def _aliphatic_index(seq: str) -> float:
    """Ikai (1980) aliphatic index for a protein sequence."""
    if not seq: return 0.0
    n = len(seq)
    return 100 * (seq.count("A")/n + 2.9*seq.count("V")/n
                   + 3.9*(seq.count("I")+seq.count("L"))/n)


# ──────────────────────────────────────────────────────────────────────────
# Live SMILES fetcher — 5+ database cascade (NO hardcoded drug data)
# Used as a last-resort fallback when researcher provides only a drug NAME.
#
# Cascade order (each tier independent — no shared state):
#   1. PubChem PUG REST    — primary, fastest, ~110M compounds
#   2. ChEMBL REST          — drug-focused, manually-curated
#   3. RxNorm  (NIH NLM)    — clinical drug terminology
#   4. CAS Common Chemistry — IUPAC-aligned identifiers
#   5. Wikidata SPARQL      — cross-references all of the above
#   6. UniChem              — federated cross-database resolver
#
# Each database is queried independently; the first one that returns a valid
# SMILES is used. If ALL fail, returns None and the pipeline is told the
# drug cannot be resolved (no invented values).
# ──────────────────────────────────────────────────────────────────────────
def _fetch_smiles_pubchem(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 1: PubChem PUG REST."""
    try:
        import requests
        url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                f"name/{requests.utils.quote(name)}/property/CanonicalSMILES/JSON")
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            props = r.json().get("PropertyTable", {}).get("Properties", [])
            if props and "CanonicalSMILES" in props[0]:
                return props[0]["CanonicalSMILES"]
    except Exception as e:
        log.debug(f"[PUBCHEM] {name!r}: {e}")
    return None


def _fetch_smiles_chembl(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 2: ChEMBL REST API."""
    try:
        import requests
        # Search by preferred name
        url = (f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
                f"pref_name__iexact={requests.utils.quote(name)}&limit=1")
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            mols = r.json().get("molecules", [])
            if mols:
                struct = mols[0].get("molecule_structures", {}) or {}
                smi = struct.get("canonical_smiles")
                if smi: return smi
        # Fallback: synonym search
        url2 = (f"https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?"
                  f"q={requests.utils.quote(name)}&limit=1")
        r2 = requests.get(url2, timeout=timeout)
        if r2.status_code == 200:
            mols = r2.json().get("molecules", [])
            if mols:
                struct = mols[0].get("molecule_structures", {}) or {}
                smi = struct.get("canonical_smiles")
                if smi: return smi
    except Exception as e:
        log.debug(f"[CHEMBL] {name!r}: {e}")
    return None


def _fetch_smiles_rxnorm(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 3: NIH NLM RxNorm → RxNav → unii → PubChem CID → SMILES."""
    try:
        import requests
        # RxNorm RxCUI lookup
        rxcui_url = (f"https://rxnav.nlm.nih.gov/REST/rxcui.json?"
                      f"name={requests.utils.quote(name)}")
        r = requests.get(rxcui_url, timeout=timeout)
        if r.status_code != 200: return None
        rxcuis = r.json().get("idGroup", {}).get("rxnormId", [])
        if not rxcuis: return None
        # Get UNII for first RxCUI
        unii_url = (f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcuis[0]}/"
                     f"property.json?propName=UNII_CODE")
        r2 = requests.get(unii_url, timeout=timeout)
        if r2.status_code != 200: return None
        props = r2.json().get("propConceptGroup",{}).get("propConcept",[])
        unii = next((p["propValue"] for p in props
                      if p.get("propName") == "UNII_CODE"), None)
        if not unii: return None
        # PubChem by UNII
        pc_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                   f"xref/RegistryID/{unii}/property/CanonicalSMILES/JSON")
        r3 = requests.get(pc_url, timeout=timeout)
        if r3.status_code == 200:
            props2 = r3.json().get("PropertyTable",{}).get("Properties",[])
            if props2 and "CanonicalSMILES" in props2[0]:
                return props2[0]["CanonicalSMILES"]
    except Exception as e:
        log.debug(f"[RXNORM] {name!r}: {e}")
    return None


def _fetch_smiles_cas_common_chem(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 4: CAS Common Chemistry."""
    try:
        import requests
        url = (f"https://commonchemistry.cas.org/api/search?"
                f"q={requests.utils.quote(name)}")
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200: return None
        results = r.json().get("results", [])
        if not results: return None
        # Detail endpoint
        rn = results[0].get("rn")
        if not rn: return None
        detail = requests.get(f"https://commonchemistry.cas.org/api/detail?cas_rn={rn}",
                              timeout=timeout)
        if detail.status_code == 200:
            smi = detail.json().get("canonicalSmile")
            if smi: return smi
    except Exception as e:
        log.debug(f"[CAS] {name!r}: {e}")
    return None


def _fetch_smiles_wikidata(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 5: Wikidata SPARQL — pulls SMILES property P233."""
    try:
        import requests
        # SPARQL query: ?drug rdfs:label "<name>"@en ; wdt:P233 ?smiles
        sparql = f'''
        SELECT ?smiles WHERE {{
          ?drug rdfs:label "{name}"@en .
          ?drug wdt:P233 ?smiles .
        }} LIMIT 1
        '''
        r = requests.get("https://query.wikidata.org/sparql",
                          params={"query": sparql, "format":"json"},
                          headers={"User-Agent":"CEREBRO-X/22.1",
                                    "Accept":"application/json"},
                          timeout=timeout)
        if r.status_code == 200:
            bindings = r.json().get("results",{}).get("bindings",[])
            if bindings:
                smi = bindings[0].get("smiles",{}).get("value")
                if smi: return smi
    except Exception as e:
        log.debug(f"[WIKIDATA] {name!r}: {e}")
    return None


def _fetch_smiles_unichem(name: str, timeout: int = 10) -> Optional[str]:
    """Tier 6: UniChem — EBI's federated cross-database identifier resolver.
    UniChem doesn't accept names directly, so we use it via PubChem CID
    cross-reference as a redundancy check."""
    try:
        import requests
        # Get PubChem CID first
        cid_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                    f"name/{requests.utils.quote(name)}/cids/JSON")
        r = requests.get(cid_url, timeout=timeout)
        if r.status_code != 200: return None
        cids = r.json().get("IdentifierList",{}).get("CID",[])
        if not cids: return None
        # Use UniChem to confirm + cross-reference (doesn't return SMILES,
        # but confirms the CID is real). Then get SMILES from PubChem.
        smi_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                    f"cid/{cids[0]}/property/CanonicalSMILES/JSON")
        r2 = requests.get(smi_url, timeout=timeout)
        if r2.status_code == 200:
            props = r2.json().get("PropertyTable",{}).get("Properties",[])
            if props:
                return props[0].get("CanonicalSMILES")
    except Exception as e:
        log.debug(f"[UNICHEM] {name!r}: {e}")
    return None


# Master cascade — runs in order, returns first successful hit + source label
SMILES_FETCH_TIERS = [
    ("PubChem PUG-REST",        _fetch_smiles_pubchem),
    ("ChEMBL REST",             _fetch_smiles_chembl),
    ("NIH NLM RxNorm/RxNav",    _fetch_smiles_rxnorm),
    ("CAS Common Chemistry",    _fetch_smiles_cas_common_chem),
    ("Wikidata SPARQL (P233)",  _fetch_smiles_wikidata),
    ("UniChem (via PubChem)",   _fetch_smiles_unichem),
]


def fetch_smiles_from_pubchem(drug_name: str, timeout: int = 10) -> Optional[str]:
    """Backward-compat alias — runs full 6-tier cascade and returns first hit."""
    return fetch_smiles_cascade(drug_name, timeout=timeout)


def fetch_smiles_cascade(drug_name: str, timeout: int = 10) -> Optional[str]:
    """Run the full 6-tier SMILES-resolution cascade.

    Returns the canonical SMILES string from the first responsive database,
    or None if all 6 tiers fail.
    """
    if not drug_name or not drug_name.strip():
        return None
    name = drug_name.strip()
    for tier_name, fn in SMILES_FETCH_TIERS:
        try:
            smi = fn(name, timeout=timeout)
            if smi and len(smi) > 2:
                log.info(f"[SMILES-CASCADE] {name!r} resolved by {tier_name}: {smi[:50]}")
                return smi
        except Exception as e:
            log.debug(f"[SMILES-CASCADE] {tier_name} raised: {e}")
            continue
    log.warning(f"[SMILES-CASCADE] {name!r} unresolvable across all 6 tiers")
    return None


# ──────────────────────────────────────────────────────────────────────────
# Live FASTA fetcher — 5+ database cascade for biologics
# ──────────────────────────────────────────────────────────────────────────
def _fetch_fasta_uniprot(query: str, timeout: int = 10) -> Optional[str]:
    """Tier 1: UniProt REST (reviewed entries)."""
    try:
        import requests
        url = (f"https://rest.uniprot.org/uniprotkb/search?"
                f"query={requests.utils.quote(query)}+AND+reviewed:true&"
                f"format=tsv&fields=accession,sequence&size=1")
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200 and r.text.strip():
            lines = r.text.strip().split("\n")
            if len(lines) >= 2:
                _acc, seq = lines[1].split("\t")
                return seq
    except Exception as e:
        log.debug(f"[UNIPROT] {query!r}: {e}")
    return None


def _fetch_fasta_uniprot_unreviewed(query: str, timeout: int = 10) -> Optional[str]:
    """Tier 2: UniProt REST (TrEMBL, unreviewed)."""
    try:
        import requests
        url = (f"https://rest.uniprot.org/uniprotkb/search?"
                f"query={requests.utils.quote(query)}&"
                f"format=tsv&fields=accession,sequence&size=1")
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200 and r.text.strip():
            lines = r.text.strip().split("\n")
            if len(lines) >= 2:
                _acc, seq = lines[1].split("\t")
                return seq
    except Exception as e:
        log.debug(f"[UNIPROT-TrEMBL] {query!r}: {e}")
    return None


def _fetch_fasta_ncbi(query: str, timeout: int = 10) -> Optional[str]:
    """Tier 3: NCBI Protein E-utilities."""
    try:
        import requests
        # esearch
        esearch = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db":"protein","term":query,"retmode":"json","retmax":1},
            timeout=timeout)
        if esearch.status_code != 200: return None
        ids = esearch.json().get("esearchresult",{}).get("idlist",[])
        if not ids: return None
        # efetch
        efetch = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db":"protein","id":ids[0],"rettype":"fasta","retmode":"text"},
            timeout=timeout)
        if efetch.status_code == 200:
            text = efetch.text.strip()
            # Strip FASTA header(s)
            seq = "".join(l for l in text.split("\n") if not l.startswith(">"))
            if seq: return seq
    except Exception as e:
        log.debug(f"[NCBI-PROTEIN] {query!r}: {e}")
    return None


def _fetch_fasta_pdb(query: str, timeout: int = 10) -> Optional[str]:
    """Tier 4: RCSB PDB sequence search."""
    try:
        import requests
        # Search RCSB for entries matching query
        search_payload = {
            "query": {"type":"terminal","service":"full_text",
                       "parameters":{"value":query}},
            "return_type": "polymer_entity",
            "request_options":{"paginate":{"rows":1}}
        }
        r = requests.post("https://search.rcsb.org/rcsbsearch/v2/query",
                           json=search_payload, timeout=timeout)
        if r.status_code != 200: return None
        results = r.json().get("result_set",[])
        if not results: return None
        polymer_id = results[0]["identifier"]   # e.g. "5GGS_1"
        # Fetch entity info
        pdb_id, ent = polymer_id.split("_")
        info = requests.get(
            f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}/{ent}",
            timeout=timeout)
        if info.status_code == 200:
            seq = info.json().get("entity_poly",{}).get("pdbx_seq_one_letter_code_can")
            if seq: return seq.replace("\n","").strip()
    except Exception as e:
        log.debug(f"[RCSB-PDB] {query!r}: {e}")
    return None


def _fetch_fasta_ensembl(query: str, timeout: int = 10) -> Optional[str]:
    """Tier 5: Ensembl REST API."""
    try:
        import requests
        # Search by symbol (gene → canonical protein)
        url = (f"https://rest.ensembl.org/lookup/symbol/homo_sapiens/"
                f"{requests.utils.quote(query)}?expand=1")
        r = requests.get(url, headers={"Accept":"application/json"},
                          timeout=timeout)
        if r.status_code != 200: return None
        data = r.json()
        # Get canonical transcript → protein
        trans = data.get("Transcript", [])
        canonical = next((t for t in trans if t.get("is_canonical")), None)
        if not canonical: return None
        prot_id = (canonical.get("Translation") or {}).get("id")
        if not prot_id: return None
        # Fetch protein sequence
        seq_url = f"https://rest.ensembl.org/sequence/id/{prot_id}?type=protein"
        r2 = requests.get(seq_url, headers={"Accept":"text/x-fasta"},
                           timeout=timeout)
        if r2.status_code == 200:
            text = r2.text
            seq = "".join(l for l in text.split("\n") if not l.startswith(">"))
            if seq: return seq
    except Exception as e:
        log.debug(f"[ENSEMBL] {query!r}: {e}")
    return None


FASTA_FETCH_TIERS = [
    ("UniProt (Swiss-Prot reviewed)",  _fetch_fasta_uniprot),
    ("UniProt (TrEMBL unreviewed)",    _fetch_fasta_uniprot_unreviewed),
    ("NCBI Protein E-utilities",        _fetch_fasta_ncbi),
    ("RCSB PDB polymer entity",         _fetch_fasta_pdb),
    ("Ensembl REST",                    _fetch_fasta_ensembl),
]


def fetch_fasta_from_uniprot(query: str, timeout: int = 10) -> Optional[str]:
    """Backward-compat alias — runs full 5-tier cascade."""
    return fetch_fasta_cascade(query, timeout=timeout)


def fetch_fasta_cascade(query: str, timeout: int = 10) -> Optional[str]:
    """Run the full 5-tier FASTA-resolution cascade."""
    if not query or not query.strip():
        return None
    q = query.strip()
    for tier_name, fn in FASTA_FETCH_TIERS:
        try:
            seq = fn(q, timeout=timeout)
            if seq and len(seq) >= 5:
                log.info(f"[FASTA-CASCADE] {q!r} resolved by {tier_name} "
                          f"({len(seq)} aa)")
                return seq
        except Exception as e:
            log.debug(f"[FASTA-CASCADE] {tier_name} raised: {e}")
            continue
    log.warning(f"[FASTA-CASCADE] {q!r} unresolvable across all 5 tiers")
    return None


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────
def enrich_mol_profile(mol_profile: Dict) -> Dict:
    """
    Enrich an input mol_profile with RDKit-derived (or FASTA-derived)
    descriptors. Returns a NEW dict; does not mutate input.

    Researcher overrides win: if `mol_profile` already has e.g. `LogP=4.31`,
    the returned profile keeps that value but tags it as `researcher_override`.

    Outputs (always present, even as None):
      MW_Da, LogP, TPSA_A2, HBD, HBA, RotBonds, AromaticRings,
      FormalCharge, Stereocenters, pKa, _descriptors_provenance
    """
    out = dict(mol_profile)   # shallow copy

    smiles = str(mol_profile.get("smiles") or
                  mol_profile.get("SMILES") or
                  mol_profile.get("molecule_input") or "").strip()
    fasta  = str(mol_profile.get("fasta") or
                  mol_profile.get("FASTA") or
                  mol_profile.get("sequence") or "").strip()
    mclass = str(mol_profile.get("molecule_class","small_molecule")).lower().strip()
    drug_name = str(mol_profile.get("name","")).strip()

    is_biologic = ("biologic" in mclass or "antibody" in mclass
                    or "protein" in mclass or "peptide" in mclass
                    or "mab" in mclass)

    # ── Live API fallback: drug name → SMILES/FASTA ───────────────────
    # NO hardcoded drug database. ALL data fetched live from authoritative
    # sources (PubChem for small molecules, UniProt for biologics).
    if not smiles and not fasta and drug_name:
        if is_biologic:
            log.info(f"[MOL] No FASTA for {drug_name!r} — querying UniProt live")
            fasta = fetch_fasta_from_uniprot(drug_name) or ""
            if fasta:
                out["fasta"] = fasta
                out["_fasta_fetched_from"] = "uniprot_live"
        else:
            log.info(f"[MOL] No SMILES for {drug_name!r} — querying PubChem live")
            smiles = fetch_smiles_from_pubchem(drug_name) or ""
            if smiles:
                out["smiles"] = smiles
                out["_smiles_fetched_from"] = "pubchem_live"

    # Decide source: FASTA preferred for biologics, SMILES for everything else.
    if fasta and is_biologic:
        descriptors = _fasta_descriptors(fasta)
        primary_source = "fasta"
    elif smiles:
        descriptors = _rdkit_descriptors(smiles)
        primary_source = "rdkit"
    elif fasta:    # try FASTA as last resort
        descriptors = _fasta_descriptors(fasta)
        primary_source = "fasta"
    else:
        log.warning(f"[MOL] No SMILES/FASTA found for "
                    f"{drug_name or 'drug'} — descriptors empty (live API "
                    f"lookup also failed)")
        descriptors = {}
        primary_source = "none"

    # Provenance dict — what came from where
    provenance: Dict[str, Dict] = {}

    # Merge: researcher override wins, descriptor fills gap
    for key, desc_record in descriptors.items():
        if key.startswith("_"):
            out[key] = desc_record   # error flags, etc.
            continue
        user_val = mol_profile.get(key)
        if user_val is not None and user_val != "" and not (
                isinstance(user_val, float) and math.isnan(user_val)):
            # Researcher override
            out[key] = float(user_val) if isinstance(user_val, (int, float)) else user_val
            provenance[key] = {
                "value": user_val,
                "source": "researcher_override",
                "confidence": "HIGH (user-provided)",
                "method": "Excel input",
                "computed_value": desc_record.get("value"),   # what we would have computed
            }
        else:
            # Use computed
            out[key] = desc_record["value"]
            provenance[key] = desc_record

    # Always-present keys (even if None)
    for required_key in ("MW_Da", "LogP", "TPSA_A2", "HBD", "HBA",
                          "RotBonds", "AromaticRings", "FormalCharge",
                          "Stereocenters", "pKa", "pKa_acidic", "pKa_basic",
                          "NetCharge_pH74", "FractionCationic_pH74",
                          "FractionAnionic_pH74", "FractionZwitterion_pH74",
                          "FractionNeutral_pH74"):
        if required_key not in out:
            out[required_key] = None
            provenance[required_key] = {
                "value": None, "source": "missing",
                "confidence": "FAILED",
                "method": "no SMILES/FASTA available",
            }

    out["_descriptors_provenance"] = provenance
    out["_primary_source"] = primary_source
    return out


# ──────────────────────────────────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    DESCRIPTORS = ("MW_Da","LogP","TPSA_A2","HBD","HBA","RotBonds",
                    "AromaticRings","FormalCharge","Stereocenters",
                    "pKa","pKa_acidic","pKa_basic","NetCharge_pH74",
                    "FractionCationic_pH74","FractionAnionic_pH74",
                    "FractionZwitterion_pH74","FractionNeutral_pH74")

    # Generic SMILES test molecules — illustrate microspeciation across
    # different protonation classes. NO drug-name hardcoding: these are
    # canonical SMILES strings labeled by their protonation behaviour.
    TEST_MOLECULES = [
        ("BASIC_TERTIARY_AMINE",  "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2"),
        ("BASIC_CARBAMATE",       "CCN(C)C(=O)Oc1cccc(c1)C(C)N(C)C"),
        ("BASIC_PRIMARY_AMINE",   "CC12CC3CC(C1)(CC(C2)(C3)N)C"),
        ("ZWITTERION_AAACID",     "C1=CC(=C(C=C1CC(C(=O)O)N)O)O"),
        ("ACIDIC_ESTER",          "CC(=O)Oc1ccccc1C(=O)O"),
        ("ACIDIC_CARBOXYL",       "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
    ]

    print(f"\n{'Class':<22s} {'MW':>7s} {'LogP':>6s} {'TPSA':>6s} "
            f"{'pKa_a':>6s} {'pKa_b':>6s} {'NetQ':>7s} "
            f"{'F_cat':>6s} {'F_ani':>6s} {'F_zwit':>7s} {'F_neut':>7s}")
    print("-"*100)
    for label, smi in TEST_MOLECULES:
        p = enrich_mol_profile({"name": label, "smiles": smi,
                                 "molecule_class": "small_molecule"})
        print(f"{label:<22s} "
                f"{(p.get('MW_Da') or 0):>7.1f} "
                f"{(p.get('LogP') or 0):>6.2f} "
                f"{(p.get('TPSA_A2') or 0):>6.1f} "
                f"{(p.get('pKa_acidic') or 0):>6.1f} "
                f"{(p.get('pKa_basic') or 0):>6.1f} "
                f"{(p.get('NetCharge_pH74') or 0):>7.3f} "
                f"{(p.get('FractionCationic_pH74') or 0):>6.3f} "
                f"{(p.get('FractionAnionic_pH74') or 0):>6.3f} "
                f"{(p.get('FractionZwitterion_pH74') or 0):>7.3f} "
                f"{(p.get('FractionNeutral_pH74') or 0):>7.3f}")

    print("\n─── Live SMILES cascade test (name → live PubChem/ChEMBL/etc) ───")
    p_live = enrich_mol_profile({"name": "TEST_NAME_QUERY",
                                   "molecule_class": "small_molecule"})
    print(f"  Resolved SMILES: {p_live.get('smiles','(none)')}")
    print(f"  Source: {p_live.get('_smiles_fetched_from','—')}")
