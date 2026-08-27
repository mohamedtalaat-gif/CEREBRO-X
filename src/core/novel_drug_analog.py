"""
================================================================================
CEREBRO-X | NOVEL DRUG ANALOG ENGINE — NO HARDCODED REFERENCE DB
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

VERSION CHANGE (v22.1, 2026-04-28):
  The previous embedded REFERENCE_DRUGS list (220 drug name + property entries)
  was REMOVED because it caused unrelated drug names (e.g., Temozolomide) to
  surface in pipeline outputs whenever the researcher's input was incomplete.

  This module now performs analog matching ONLY against drugs that the live
  ChEMBL/PubChem APIs return as similarity hits for the actual input SMILES.
  It never invents drug names that the researcher did not provide.

PUBLIC INTERFACE (preserved for backward compatibility):
  find_closest_analog(drug_name, mol_profile, smiles) -> dict
================================================================================
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger("CEREBRO-ANALOG")

# Empty list — preserved for any code that still imports REFERENCE_DRUGS.
REFERENCE_DRUGS: list[dict] = []


def _safe_get(url: str, timeout: int = 10) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug(f"[ANALOG] GET failed {url[:80]}: {e}")
        return None


def _live_chembl_similarity(smiles: str, threshold_pct: int = 60,
                              limit: int = 5) -> list[dict]:
    """Live ChEMBL similarity search."""
    if not smiles: return []
    try:
        enc = urllib.parse.quote(smiles)
        url = (f"https://www.ebi.ac.uk/chembl/api/data/similarity/"
                f"{enc}/{threshold_pct}.json?limit={limit}")
        data = _safe_get(url)
        if not data or not data.get("molecules"):
            return []
        out = []
        for mol in data["molecules"][:limit]:
            cid = mol.get("molecule_chembl_id","")
            sim = float(mol.get("similarity", 0))
            pref = (mol.get("pref_name") or
                     (mol.get("molecule_synonyms") or [{}])[0].get("synonyms","")
                     or cid)
            out.append({
                "name":           pref,
                "chembl_id":      cid,
                "similarity_pct": round(sim, 2),
                "similarity_is_exact": True,   # ChEMBL returns a real per-compound Tanimoto score
                "_source":        f"https://www.ebi.ac.uk/chembl/compound_report_card/{cid}/",
                "method":         "live_chembl_tanimoto",
            })
        return out
    except Exception as e:
        log.warning(f"[ANALOG] ChEMBL similarity failed: {e}")
        return []


def _live_pubchem_similarity(smiles: str, threshold: int = 90,
                                limit: int = 5) -> list[dict]:
    """Live PubChem 2D similarity search."""
    if not smiles: return []
    try:
        enc = urllib.parse.quote(smiles)
        url_start = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
                      f"similarity/smiles/{enc}/JSON?Threshold={threshold}&MaxRecords={limit}")
        data = _safe_get(url_start)
        if not data: return []
        wait_key = (data.get("Waiting", {}).get("ListKey") or
                     data.get("IdentifierList", {}).get("ListKey"))
        cids = (data.get("IdentifierList", {}).get("CID", []) or
                 data.get("CID_List", []))
        if wait_key and not cids:
            time.sleep(2)
            data2 = _safe_get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/listkey/{wait_key}/cids/JSON")
            cids = (data2.get("IdentifierList", {}).get("CID", [])
                     if data2 else [])
        if not cids: return []
        cids_str = ",".join(str(c) for c in cids[:limit])
        names_data = _safe_get(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cids_str}/"
            f"property/IUPACName,Title/JSON")
        out = []
        if names_data and names_data.get("PropertyTable"):
            for entry in names_data["PropertyTable"]["Properties"]:
                cid = entry.get("CID")
                title = entry.get("Title") or entry.get("IUPACName") or f"CID:{cid}"
                out.append({
                    "name":           title,
                    "pubchem_cid":    cid,
                    # PubChem's similarity-search endpoint returns the set of
                    # CIDs meeting the threshold, not a per-compound score —
                    # this is a floor ("at least `threshold`% similar"), not
                    # a measurement. Every hit used to report this identical
                    # value as "similarity_pct" with no indication it wasn't
                    # actually computed per-molecule, which then competed
                    # directly against ChEMBL's real per-compound Tanimoto
                    # scores in the best-match selection below.
                    "similarity_pct": float(threshold),
                    "similarity_is_exact": False,
                    "_source":        f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                    "method":         "live_pubchem_2d",
                })
        return out
    except Exception as e:
        log.warning(f"[ANALOG] PubChem similarity failed: {e}")
        return []


def find_closest_analog(drug_name: str, mol_profile: dict,
                          smiles: str | None = None) -> dict:
    """Find the closest analog using live databases ONLY."""
    smiles = smiles or mol_profile.get("smiles") or mol_profile.get("SMILES") or ""
    smiles = str(smiles).strip()

    if not smiles:
        return {
            "is_novel_drug":  True,
            "confirmed_absent_from_databases": False,
            "closest_analog": {
                "name":           f"(no SMILES provided for {drug_name or 'drug'})",
                "similarity_pct": 0.0,
                "method":         "no_smiles_input",
                "_source":        "none",
            },
            "disclaimer": ("No SMILES provided. Cannot query live similarity "
                            "databases. Provide SMILES or canonical drug name "
                            "(PubChem will resolve it to SMILES) for analog matching."),
        }

    chembl_hits = _live_chembl_similarity(smiles, threshold_pct=60, limit=5)
    pubchem_hits = _live_pubchem_similarity(smiles, threshold=90, limit=5)

    all_hits = chembl_hits + pubchem_hits
    if not all_hits:
        return {
            "is_novel_drug":  True,
            "confirmed_absent_from_databases": True,
            "closest_analog": {
                "name":           "(no live analog found)",
                "similarity_pct": 0.0,
                "method":         "no_analog_found",
                "_source":        "none",
            },
            "disclaimer": ("Live ChEMBL and PubChem similarity searches "
                            "returned no analogs for the provided SMILES. "
                            "This may indicate a genuinely novel chemical entity."),
        }

    best = max(all_hits, key=lambda h: h["similarity_pct"])
    is_novel = best["similarity_pct"] < 70
    sim_phrase = (f"{best['similarity_pct']:.1f}% similarity"
                  if best.get("similarity_is_exact", True)
                  else f"≥{best['similarity_pct']:.0f}% similarity "
                       f"(PubChem threshold — not an exact per-compound score)")
    return {
        "is_novel_drug":  is_novel,
        "confirmed_absent_from_databases": False,
        "closest_analog": best,
        "all_hits":        all_hits,
        "disclaimer": (f"Closest live analog: {best['name']} "
                        f"({sim_phrase} via {best['method']}). "
                        f"Source: {best.get('_source','—')}. "
                        f"This match is derived from live database queries — "
                        f"no hardcoded reference list."),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Generic test SMILES — basic-amine small molecule (no drug name).
    r = find_closest_analog(
        "TEST_BASIC_AMINE", {},
        "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2")
    print(json.dumps(r, indent=2)[:800])
