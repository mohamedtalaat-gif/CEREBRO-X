"""
================================================================================
CEREBRO-X | categories/drug_identifiers.py
================================================================================
PRIORITY 0 — runs before every other resolver.

The resolver doesn't just FIND identifiers; it VALIDATES and CANONICALIZES
them. If the user types "C(=O)O CC" with a stray space, this module either
fixes it or returns a meaningful error.

Categories registered:
    drug_smiles  — canonical SMILES from any input
    drug_fasta   — canonical FASTA sequence from any input

Tier cascade:
    Tier 0: researcher override (input as-given, validated)
    Tier 1: live drug DB (PubChem → ChEMBL → RxNorm → CAS → Wikidata → UniChem)
    Tier 2: (n/a for identifiers)
    Tier 3: RDKit/OpenBabel canonicalization (input is SMILES, validate it)
    Tier 4: bioinformatics: UniProt/NCBI/Ensembl/PDB/BLAST cascade for FASTA
    Tier 5: thermo.Chemical(name).smiles
    Tier 6: (n/a)
    Tier 7: best-effort SMILES sanitization
================================================================================
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from .._core import (
    _HAS_RDKIT,
    _HAS_REQUESTS,
    _HAS_THERMO,
    _resolved,
    cached_safe_get,
    register,
)

log = logging.getLogger("CEREBRO-RESOLVER.identifiers")

# ──────────────────────────────────────────────────────────────────────────
# SMILES — Tier 1 live cascade
# ──────────────────────────────────────────────────────────────────────────
def _smiles_t1_pubchem(name: str) -> str | None:
    if not name: return None
    enc = urllib.parse.quote(name)
    txt = cached_safe_get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
        f"name/{enc}/property/CanonicalSMILES/JSON")
    if txt:
        try:
            d = json.loads(txt)
            props = d.get("PropertyTable", {}).get("Properties", [])
            if props and "CanonicalSMILES" in props[0]:
                return props[0]["CanonicalSMILES"]
        except Exception: pass
    return None


def _smiles_t1_chembl(name: str) -> str | None:
    if not name: return None
    enc = urllib.parse.quote(name)
    # Pref-name exact
    txt = cached_safe_get(
        f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
        f"pref_name__iexact={enc}&limit=1")
    if txt:
        try:
            d = json.loads(txt)
            mols = d.get("molecules", [])
            if mols:
                struct = mols[0].get("molecule_structures") or {}
                smi = struct.get("canonical_smiles")
                if smi: return smi
        except Exception: pass
    # Synonym
    txt2 = cached_safe_get(
        f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
        f"molecule_synonyms__synonyms__iexact={enc}&limit=1")
    if txt2:
        try:
            d = json.loads(txt2)
            mols = d.get("molecules", [])
            if mols:
                struct = mols[0].get("molecule_structures") or {}
                smi = struct.get("canonical_smiles")
                if smi: return smi
        except Exception: pass
    return None


def _smiles_t1_rxnorm(name: str) -> str | None:
    if not name or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://rxnav.nlm.nih.gov/REST/rxcui.json?name={enc}")
        if not txt: return None
        d = json.loads(txt)
        rxcuis = d.get("idGroup", {}).get("rxnormId", [])
        if not rxcuis: return None
        # Get UNII
        txt2 = cached_safe_get(
            f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcuis[0]}/"
            f"property.json?propName=UNII_CODE")
        if not txt2: return None
        d2 = json.loads(txt2)
        props = d2.get("propConceptGroup", {}).get("propConcept", [])
        unii = next((p["propValue"] for p in props
                       if p.get("propName") == "UNII_CODE"), None)
        if not unii: return None
        # PubChem by UNII (RegistryID)
        txt3 = cached_safe_get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"xref/RegistryID/{unii}/property/CanonicalSMILES/JSON")
        if not txt3: return None
        d3 = json.loads(txt3)
        props2 = d3.get("PropertyTable", {}).get("Properties", [])
        if props2 and "CanonicalSMILES" in props2[0]:
            return props2[0]["CanonicalSMILES"]
    except Exception as e:
        log.debug(f"[SMILES:RxNorm] {name!r}: {e}")
    return None


def _smiles_t1_cas(name: str) -> str | None:
    if not name or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://commonchemistry.cas.org/api/search?q={enc}")
        if not txt: return None
        d = json.loads(txt)
        results = d.get("results", [])
        if not results: return None
        rn = results[0].get("rn")
        if not rn: return None
        txt2 = cached_safe_get(
            f"https://commonchemistry.cas.org/api/detail?cas_rn={rn}")
        if not txt2: return None
        d2 = json.loads(txt2)
        smi = d2.get("canonicalSmile")
        if smi: return smi
    except Exception as e:
        log.debug(f"[SMILES:CAS] {name!r}: {e}")
    return None


def _smiles_t1_wikidata(name: str) -> str | None:
    if not name or not _HAS_REQUESTS: return None
    try:
        sparql = f'''
        SELECT ?smiles WHERE {{
          ?drug rdfs:label "{name}"@en .
          ?drug wdt:P233 ?smiles .
        }} LIMIT 1
        '''
        import requests
        r = requests.get("https://query.wikidata.org/sparql",
                          params={"query": sparql, "format": "json"},
                          headers={"User-Agent": "CEREBRO-X/22.1",
                                    "Accept": "application/json"},
                          timeout=10)
        if r.status_code == 200:
            d = r.json()
            bindings = d.get("results", {}).get("bindings", [])
            if bindings:
                smi = bindings[0].get("smiles", {}).get("value")
                if smi: return smi
    except Exception as e:
        log.debug(f"[SMILES:Wikidata] {name!r}: {e}")
    return None


def _smiles_t1_unichem(name: str) -> str | None:
    """UniChem via PubChem CID cross-ref."""
    if not name: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"name/{enc}/cids/JSON")
        if not txt: return None
        d = json.loads(txt)
        cids = d.get("IdentifierList", {}).get("CID", [])
        if not cids: return None
        txt2 = cached_safe_get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"cid/{cids[0]}/property/CanonicalSMILES/JSON")
        if not txt2: return None
        d2 = json.loads(txt2)
        props = d2.get("PropertyTable", {}).get("Properties", [])
        if props:
            return props[0].get("CanonicalSMILES")
    except Exception as e:
        log.debug(f"[SMILES:UniChem] {name!r}: {e}")
    return None


SMILES_T1_CASCADE = [
    ("PubChem PUG-REST",        _smiles_t1_pubchem),
    ("ChEMBL REST",             _smiles_t1_chembl),
    ("NIH NLM RxNorm/RxNav",    _smiles_t1_rxnorm),
    ("CAS Common Chemistry",    _smiles_t1_cas),
    ("Wikidata SPARQL (P233)",  _smiles_t1_wikidata),
    ("UniChem (via PubChem)",   _smiles_t1_unichem),
]


# ──────────────────────────────────────────────────────────────────────────
# Tier-3 SMILES validation/canonicalization
# ──────────────────────────────────────────────────────────────────────────
def _smiles_t3_rdkit_canonical(smi: str) -> str | None:
    """Validate + canonicalize via RDKit. Returns the RDKit canonical form,
    or None if the SMILES is unparseable."""
    if not smi or not _HAS_RDKIT: return None
    from rdkit import Chem
    try:
        # Strip any accidental whitespace
        clean = smi.strip().replace(" ", "")
        mol = Chem.MolFromSmiles(clean)
        if mol is None: return None
        return Chem.MolToSmiles(mol, canonical=True)
    except Exception:
        return None


def _smiles_t5_thermo(name: str) -> str | None:
    """thermo's Chemical class can resolve names to SMILES via PubChem
    (its own cache). Used as a redundancy after our 6-tier cascade."""
    if not name or not _HAS_THERMO: return None
    try:
        from thermo import Chemical
        c = Chemical(name)
        return c.smiles
    except Exception as e:
        log.debug(f"[SMILES:thermo] {name!r}: {e}")
        return None


def _smiles_t7_sanitize(raw: str) -> str | None:
    """Last-ditch fallback: best-effort cleanup. Returns the input string
    minus whitespace, or None if it doesn't look like a SMILES at all."""
    if not raw: return None
    candidate = raw.strip().replace(" ", "")
    # Heuristic: must contain at least one of CNOSPHF or aromatic equiv
    if not any(c in candidate for c in "CNOSPHFcnoscl"):
        return None
    return candidate


# ──────────────────────────────────────────────────────────────────────────
# Public resolver
# ──────────────────────────────────────────────────────────────────────────
@register("drug_smiles")
def resolve_drug_smiles(name: str = "", smiles: str = "",
                          researcher_override: str | None = None) -> dict:
    """Resolve and canonicalize a drug's SMILES from any input.

    Priority:
      0. researcher_override (validated through RDKit if available)
      1. If SMILES provided: validate + canonicalize via RDKit
      1b. If only name: live 6-tier DB cascade
      3. RDKit canonicalization of best DB hit
      5. thermo.Chemical fallback
      7. Sanitize raw input

    Returns a ResolvedValue whose `value` is the canonical SMILES string.
    """
    db_misses: list[str] = []

    # Tier 0: researcher override (validate it, but never reject)
    if researcher_override:
        canonical = _smiles_t3_rdkit_canonical(researcher_override) \
                     or researcher_override.strip()
        return _resolved(
            value=canonical, tier=0, source="researcher_override",
            method="User-provided SMILES, RDKit-canonicalized if possible",
            reference="Researcher input via Excel",
            live_db_misses=[])

    # Tier 1a: if SMILES already provided, just validate & canonicalize
    if smiles:
        canonical = _smiles_t3_rdkit_canonical(smiles)
        if canonical:
            return _resolved(
                value=canonical, tier=3,
                source="rdkit.MolToSmiles(canonical=True)",
                method="RDKit input validation + canonicalization",
                reference="Weininger D (1988) J Chem Inf Comput Sci 28:31",
                live_db_misses=[])
        # SMILES provided but unparseable → continue to live DBs as if name
        db_misses.append("user_SMILES_unparseable")

    # Tier 1: live DB cascade by NAME
    if name:
        for src_name, fn in SMILES_T1_CASCADE:
            try:
                v = fn(name)
                if v:
                    # Canonicalize the DB result through RDKit
                    canonical = _smiles_t3_rdkit_canonical(v) or v
                    return _resolved(
                        value=canonical, tier=1, source=src_name,
                        method=f"Live database query: {src_name}",
                        reference=f"{src_name} REST API; queried at runtime",
                        live_db_misses=db_misses)
            except Exception as e:
                log.debug(f"[SMILES:T1:{src_name}] {e}")
            db_misses.append(src_name)

    # Tier 5: thermo library
    if name:
        try:
            v = _smiles_t5_thermo(name)
            if v:
                canonical = _smiles_t3_rdkit_canonical(v) or v
                return _resolved(
                    value=canonical, tier=5, source="thermo.Chemical",
                    method="thermo library name→SMILES (cached PubChem proxy)",
                    reference="thermo (Bell, 2018) https://github.com/CalebBell/thermo",
                    live_db_misses=db_misses)
        except Exception:
            pass
        db_misses.append("thermo.Chemical")

    # Tier 7: sanitize raw input as last resort
    raw = smiles or name
    cleaned = _smiles_t7_sanitize(raw) if raw else None
    if cleaned:
        return _resolved(
            value=cleaned, tier=7,
            source="cerebro_value_resolver:sanitize",
            method="Best-effort whitespace strip + minimal validation",
            reference="—",
            live_db_misses=db_misses,
            extra={"warning": "SMILES could not be canonicalized; may be invalid"})

    # Total failure — return None with explicit FAILED tag
    return _resolved(
        value=None, tier=7,
        source="cerebro_value_resolver:unresolvable",
        method="All tiers exhausted",
        reference="—",
        live_db_misses=db_misses,
        extra={"confidence": "FAILED",
                "warning": f"Could not resolve SMILES for name={name!r}, "
                            f"smiles={smiles!r}. The molecule may be novel "
                            f"or the input may be malformed."})


# ──────────────────────────────────────────────────────────────────────────
# FASTA — Tier 4 cascade
# ──────────────────────────────────────────────────────────────────────────
def _fasta_t4_uniprot_reviewed(query: str) -> str | None:
    if not query or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(query)
        txt = cached_safe_get(
            f"https://rest.uniprot.org/uniprotkb/search?"
            f"query={enc}+AND+reviewed:true&format=tsv&"
            f"fields=accession,sequence&size=1", accept="text/plain")
        if not txt: return None
        lines = txt.strip().split("\n")
        if len(lines) >= 2:
            _, seq = lines[1].split("\t")
            return seq
    except Exception as e:
        log.debug(f"[FASTA:UniProt-rev] {query!r}: {e}")
    return None


def _fasta_t4_uniprot_trembl(query: str) -> str | None:
    if not query or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(query)
        txt = cached_safe_get(
            f"https://rest.uniprot.org/uniprotkb/search?"
            f"query={enc}&format=tsv&fields=accession,sequence&size=1",
            accept="text/plain")
        if not txt: return None
        lines = txt.strip().split("\n")
        if len(lines) >= 2:
            _, seq = lines[1].split("\t")
            return seq
    except Exception as e:
        log.debug(f"[FASTA:TrEMBL] {query!r}: {e}")
    return None


def _fasta_t4_ncbi(query: str) -> str | None:
    if not query or not _HAS_REQUESTS: return None
    try:
        import requests
        enc = urllib.parse.quote(query)
        e1 = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db":"protein","term":query,"retmode":"json","retmax":1},
            timeout=10)
        if e1.status_code != 200: return None
        ids = e1.json().get("esearchresult", {}).get("idlist", [])
        if not ids: return None
        e2 = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db":"protein","id":ids[0],"rettype":"fasta","retmode":"text"},
            timeout=10)
        if e2.status_code == 200:
            text = e2.text.strip()
            seq = "".join(l for l in text.split("\n") if not l.startswith(">"))
            if seq: return seq
    except Exception as e:
        log.debug(f"[FASTA:NCBI] {query!r}: {e}")
    return None


def _fasta_t4_pdb(query: str) -> str | None:
    if not query or not _HAS_REQUESTS: return None
    try:
        import requests
        payload = {
            "query": {"type":"terminal","service":"full_text",
                       "parameters":{"value": query}},
            "return_type": "polymer_entity",
            "request_options": {"paginate": {"rows": 1}}
        }
        r = requests.post("https://search.rcsb.org/rcsbsearch/v2/query",
                           json=payload, timeout=10)
        if r.status_code != 200: return None
        results = r.json().get("result_set", [])
        if not results: return None
        polymer_id = results[0]["identifier"]
        pdb_id, ent = polymer_id.split("_")
        info = requests.get(
            f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pdb_id}/{ent}",
            timeout=10)
        if info.status_code == 200:
            seq = info.json().get("entity_poly", {}).get(
                "pdbx_seq_one_letter_code_can")
            if seq: return seq.replace("\n", "").strip()
    except Exception as e:
        log.debug(f"[FASTA:PDB] {query!r}: {e}")
    return None


def _fasta_t4_ensembl(query: str) -> str | None:
    if not query or not _HAS_REQUESTS: return None
    try:
        import requests
        enc = urllib.parse.quote(query)
        r = requests.get(
            f"https://rest.ensembl.org/lookup/symbol/homo_sapiens/{enc}?expand=1",
            headers={"Accept":"application/json"}, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        trans = data.get("Transcript", [])
        canon = next((t for t in trans if t.get("is_canonical")), None)
        if not canon: return None
        prot_id = (canon.get("Translation") or {}).get("id")
        if not prot_id: return None
        r2 = requests.get(
            f"https://rest.ensembl.org/sequence/id/{prot_id}?type=protein",
            headers={"Accept":"text/x-fasta"}, timeout=10)
        if r2.status_code == 200:
            text = r2.text
            seq = "".join(l for l in text.split("\n") if not l.startswith(">"))
            if seq: return seq
    except Exception as e:
        log.debug(f"[FASTA:Ensembl] {query!r}: {e}")
    return None


FASTA_T4_CASCADE = [
    ("UniProt (Swiss-Prot reviewed)", _fasta_t4_uniprot_reviewed),
    ("UniProt (TrEMBL unreviewed)",   _fasta_t4_uniprot_trembl),
    ("NCBI Protein E-utilities",       _fasta_t4_ncbi),
    ("RCSB PDB polymer entity",        _fasta_t4_pdb),
    ("Ensembl REST",                   _fasta_t4_ensembl),
]


def _validate_fasta(seq: str) -> str | None:
    """Strip headers/whitespace, uppercase, validate amino acid alphabet."""
    if not seq: return None
    s = seq.strip()
    # Strip FASTA header(s)
    if s.startswith(">"):
        s = "\n".join(l for l in s.split("\n") if not l.startswith(">"))
    s = s.replace("\n", "").replace(" ", "").upper()
    if len(s) < 5: return None
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    if not all(c in valid_aa for c in s): return None
    return s


@register("drug_fasta")
def resolve_drug_fasta(name: str = "", fasta: str = "",
                         researcher_override: str | None = None) -> dict:
    """Resolve and canonicalize a biologic drug's FASTA sequence.

    Priority:
      0. researcher_override (validated)
      4a. If FASTA provided: validate + cleanup
      4b. If only name: live 5-tier DB cascade
      7. Best-effort cleanup of raw input
    """
    db_misses: list[str] = []

    # Tier 0
    if researcher_override:
        cleaned = _validate_fasta(researcher_override)
        return _resolved(
            value=cleaned or researcher_override.strip(),
            tier=0, source="researcher_override",
            method="User-provided FASTA, header/whitespace stripped",
            reference="Researcher input via Excel",
            live_db_misses=[])

    # Tier 4a: input FASTA validated
    if fasta:
        cleaned = _validate_fasta(fasta)
        if cleaned:
            return _resolved(
                value=cleaned, tier=4,
                source="researcher_provided_FASTA_validated",
                method="Header/whitespace strip + amino-acid alphabet check",
                reference="—", live_db_misses=[])
        db_misses.append("user_FASTA_invalid_alphabet")

    # Tier 4b: live DB cascade by name
    if name:
        for src_name, fn in FASTA_T4_CASCADE:
            try:
                v = fn(name)
                if v:
                    cleaned = _validate_fasta(v) or v
                    return _resolved(
                        value=cleaned, tier=4, source=src_name,
                        method=f"Live database query: {src_name}",
                        reference=f"{src_name} REST API; queried at runtime",
                        live_db_misses=db_misses)
            except Exception as e:
                log.debug(f"[FASTA:T4:{src_name}] {e}")
            db_misses.append(src_name)

    return _resolved(
        value=None, tier=7,
        source="cerebro_value_resolver:unresolvable",
        method="All FASTA tiers exhausted",
        reference="—",
        live_db_misses=db_misses,
        extra={"confidence": "FAILED",
                "warning": f"Could not resolve FASTA for name={name!r}, "
                            f"fasta_provided={bool(fasta)}"})
