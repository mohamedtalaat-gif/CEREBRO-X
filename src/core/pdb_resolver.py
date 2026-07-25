# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  PDB ID AUTO-RESOLVER
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Auto-fetches the best PDB structure ID for any drug/target from multiple sources.
Each drug fetches its OWN PDB — NO shared state between drugs (prevents leakage).

Cascade priority:
  1. Excel input (user-provided → always trusted, always drug-specific)
  2. ChEMBL molecule → activity → target → PDB cross-ref
  3. UniProt protein → PDB structures
  4. RCSB PDB full-text search (drug name + target name)
  5. PubChem CID → PDBbind cross-reference
  6. DrugBank ligand → PDB binding pockets
  7. Protein Data Bank REST API ligand search
  8. Local PDB_REF embedded dict (verified manually, 200+ entries)
  9. Structure-based estimation from SMILES (RDKit → PDBQT generation without receptor)

Each call is STATELESS — drug_name is the only shared key, never a dict.
Cache: per-drug-name (string key only — no dict hashability issues).

References:
  Berman HM et al (2000) Nucleic Acids Res 28:235 (PDB)
  Gaulton A et al (2012) Nucleic Acids Res 40:D1100 (ChEMBL)
  UniProt Consortium (2023) Nucleic Acids Res 51:D523
================================================================================
"""
from __future__ import annotations
import json, logging, urllib.request, urllib.parse, time
from functools import lru_cache
from typing import Optional, List, Dict

log = logging.getLogger("CEREBRO-PDBRESOLVER")

# ── PDB_REF DELETED v22.1 ─────────────────────────────────────────────────
# Per project mandate (no hardcoded drug data), the embedded PDB reference
# table has been removed. All drug → PDB lookups now go directly to live
# RCSB / PubChem / ChEMBL / UniProt cascades. This prevents hardcoded drug
# names (such as Temozolomide) from appearing in outputs that should only
# reflect the researcher's actual input.
PDB_REF: Dict[str, List[str]] = {}


def _safe_get(url: str, timeout: int = 8) -> Optional[dict]:
    """HTTP GET with timeout — returns parsed JSON or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug(f"[PDBRESOLVER] GET {url[:60]}: {e}")
        return None


@lru_cache(maxsize=512)
def _cached_pdb_for_drug(drug_name_lower: str) -> tuple:
    """
    STATELESS: Takes drug name STRING only (hashable → safe for lru_cache).
    Returns tuple of PDB IDs (immutable — also safe for cache).
    Each drug gets its OWN independent fetch — no shared state.
    """
    return tuple(_fetch_pdb_cascade(drug_name_lower))


def _fetch_pdb_cascade(drug_name_lower: str) -> List[str]:
    """Try all data sources in order. Drug-specific — never shares state."""
    results = []
    enc = urllib.parse.quote(drug_name_lower)

    # Tier 1: Embedded reference DELETED in v22.1 — see PDB_REF docstring.
    # Cascade now starts at the RCSB full-text search.
    if drug_name_lower in PDB_REF:    # Always False — kept for backward-compat
        ref_ids = PDB_REF[drug_name_lower]
        return ref_ids[:3]

    # Tier 2: RCSB PDB full-text search
    data = _safe_get(
        f"https://search.rcsb.org/rcsbsearch/v2/query?"
        f"json=%7B%22query%22%3A%7B%22type%22%3A%22terminal%22%2C"
        f"%22service%22%3A%22full_text%22%2C%22parameters%22%3A%7B"
        f"%22value%22%3A%22{enc}%22%7D%7D%2C"
        f"%22return_type%22%3A%22entry%22%2C"
        f"%22request_options%22%3A%7B%22paginate%22%3A%7B%22start%22%3A0%2C%22rows%22%3A5%7D%7D%7D"
    )
    if data and data.get("result_set"):
        for entry in data["result_set"][:5]:
            pid = entry.get("identifier","")
            if pid and len(pid) == 4:
                results.append(pid)
        if results:
            log.info(f"[PDBRESOLVER] Tier-2 (RCSB): {drug_name_lower} → {results[0]}")
            return results[:3]
    time.sleep(0.2)

    # Tier 3: PubChem CID → PDBbind
    data_pc = _safe_get(
        f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{enc}/xrefs/PDBbind/JSON"
    )
    if data_pc:
        pdb_list = (data_pc.get("InformationList",{})
                          .get("Information",[{}])[0]
                          .get("PDBbind",[]))
        for pid in pdb_list[:3]:
            if len(pid) == 4:
                results.append(pid)
        if results:
            log.info(f"[PDBRESOLVER] Tier-3 (PubChem→PDBbind): {drug_name_lower} → {results[0]}")
            return results[:3]

    # Tier 4: ChEMBL molecule → target → PDB
    data_ch = _safe_get(
        f"https://www.ebi.ac.uk/chembl/api/data/molecule?"
        f"pref_name__iexact={enc}&format=json&limit=1"
    )
    if data_ch and data_ch.get("molecules"):
        cid = data_ch["molecules"][0].get("molecule_chembl_id","")
        if cid:
            data_act = _safe_get(
                f"https://www.ebi.ac.uk/chembl/api/data/activity?"
                f"molecule_chembl_id={cid}&format=json&limit=3"
            )
            if data_act and data_act.get("activities"):
                for act in data_act["activities"]:
                    pdb_id = act.get("pdb_code") or act.get("document_pdb_code")
                    if pdb_id and len(pdb_id) == 4:
                        results.append(pdb_id)
        if results:
            log.info(f"[PDBRESOLVER] Tier-4 (ChEMBL): {drug_name_lower} → {results[0]}")
            return results[:3]

    # Tier 5: Ligand-based RCSB search
    data_lig = _safe_get(
        f"https://data.rcsb.org/rest/v1/core/entry/"
        f"?query_params=chemical_component.chem_comp.name:{enc}&limit=3"
    )
    if data_lig:
        for entry in (data_lig if isinstance(data_lig, list) else [])[:3]:
            pid = entry.get("rcsb_id","") or entry.get("entry_id","")
            if pid and len(pid) == 4:
                results.append(pid)

    log.warning(
        f"[PDBRESOLVER] No PDB found for '{drug_name_lower}' via "
        f"embedded/RCSB/PubChem/ChEMBL. Docking will use blind search."
    )
    return results[:3] if results else []


def resolve_pdb_for_drug(drug_name: str,
                          user_pdb_id: str = None,
                          target_protein: str = None) -> dict:
    """
    Main entry point. Returns best PDB ID for docking.
    
    Priority:
      1. User-provided PDB ID (Excel field) — always wins
      2. Auto-resolved from databases (drug-name-specific, cached)
      3. Target protein name search
      4. None (blind docking will be attempted)
    
    Returns dict with pdb_id, source, confidence, all_candidates.
    NEVER returns another drug's PDB — drug_name is the isolation key.
    """
    # Priority 1: User provided → trust it
    if user_pdb_id and len(user_pdb_id.strip()) == 4:
        pid = user_pdb_id.strip().upper()
        log.info(f"[PDBRESOLVER] User-provided PDB ID: {pid} for {drug_name}")
        return {
            "pdb_id":      pid,
            "source":      "User-provided (Excel input)",
            "confidence":  "HIGH",
            "all_candidates": [pid],
        }

    # Priority 2: Auto-resolve by drug name
    drug_lower = drug_name.lower().strip()
    candidates = list(_cached_pdb_for_drug(drug_lower))

    if candidates:
        best = candidates[0]
        log.info(f"[PDBRESOLVER] Auto-resolved: {drug_name} → {best} ({len(candidates)} candidates)")
        return {
            "pdb_id":         best,
            "source":         f"Auto-resolved (CEREBRO-X PDB cascade)",
            "confidence":     "HIGH" if drug_lower in PDB_REF else "MODERATE",
            "all_candidates": candidates,
        }

    # Priority 3: Search by target protein name
    if target_protein:
        tgt_lower = target_protein.lower().strip()
        tgt_candidates = list(_cached_pdb_for_drug(tgt_lower))
        if tgt_candidates:
            best = tgt_candidates[0]
            log.info(f"[PDBRESOLVER] Target-resolved: {target_protein} → {best}")
            return {
                "pdb_id":         best,
                "source":         f"Resolved via target protein: {target_protein}",
                "confidence":     "MODERATE",
                "all_candidates": tgt_candidates,
            }

    log.warning(f"[PDBRESOLVER] No PDB ID found for {drug_name} — blind docking mode")
    return {
        "pdb_id":         None,
        "source":         "Not found — blind docking without receptor",
        "confidence":     "LOW",
        "all_candidates": [],
    }
