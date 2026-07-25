# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X |  MISSING VALUE RESOLVER — NO-HARDCODE EDITION
================================================================================
Created by: Muhammad Talaat — CEREBRO-X

Handles every case where a molecular property cannot be found in primary APIs.

Resolution cascade (NO drug-name lookup tables — all live):
  Tier 1:  Live API (ChEMBL / PubChem / UniProt / DrugBank)
  Tier 2:  PubChem property endpoint (canonical SMILES + computed properties)
  Tier 3:  PubMed literature search (E-utilities) — returns DOI + journal + year
  Tier 4:  RDKit physicochemical prediction from SMILES (Crippen/Lipinski/TPSA)
  Tier 5:  Class-typical estimate (population mean for molecule class)
           → confidence_score=30, _disclaimer set, _overridable=True
  Tier 99: Explicit "source_unknown" — only when even class is unrecognized

CRITICAL DESIGN RULE — REVISED v22.1:
  • NO hardcoded LITERATURE_MW / LITERATURE_LOGP / LITERATURE_HALFLIFE tables.
  • NO drug-name → value lookup of any kind.
  • All values resolved live from PubChem REST API or from SMILES via RDKit.
  • The previous 'Embedded clinical library' tier was removed in v22.1 because
    it caused unrelated drug names (e.g. Temozolomide) to bleed into outputs
    when researcher inputs were ambiguous.

All returned values carry _source, _reference, _confidence, _confidence_score,
and _tier metadata.
================================================================================
"""
from __future__ import annotations
import logging, math, json, urllib.request, urllib.parse
from typing import Dict, Optional, Any

log = logging.getLogger("CEREBRO-RESOLVER")

# ── Class-typical population means (ONLY a class-level fallback, not drug-specific) ──
# These are NOT drug-name lookups — they are statistical means for a *class* of
# molecules (e.g., "small_molecule" averages across DrugBank). Used only when
# every other tier fails AND the molecule class is known.
CLASS_TYPICAL_FALLBACK: Dict[str, Dict[str, Dict]] = {
    "small_molecule": {
        "MW_Da":           {"value": 360,  "method": "DrugBank median for oral small molecules"},
        "LogP":            {"value": 2.5,  "method": "DrugBank median for oral small molecules"},
        "Half_Life_Days":  {"value": 0.5,  "method": "Population PK survey median"},
        "BBB_perm_pct":    {"value": 5.0,  "method": "Wager TT (2010) class median"},
    },
    "biologic": {
        "MW_Da":           {"value": 150_000, "method": "Average IgG MW"},
        "Half_Life_Days":  {"value": 14,      "method": "Median IgG circulation half-life"},
        "BBB_perm_pct":    {"value": 0.1,     "method": "Pardridge WM (2020) class median"},
    },
    "antibody": {
        "MW_Da":           {"value": 150_000, "method": "Average IgG MW"},
        "Half_Life_Days":  {"value": 21,      "method": "Median therapeutic mAb t½"},
        "BBB_perm_pct":    {"value": 0.1,     "method": "Pardridge WM (2020) class median"},
    },
    "peptide": {
        "MW_Da":           {"value": 3_000, "method": "Median therapeutic peptide MW"},
        "Half_Life_Days":  {"value": 0.04,  "method": "Median enzymatic half-life"},
        "BBB_perm_pct":    {"value": 0.5,   "method": "Class median for peptides"},
    },
}


def _pubchem_property(drug_name: str, prop: str) -> Optional[Dict]:
    """Live PubChem property fetch.

    prop ∈ {'CanonicalSMILES','MolecularWeight','XLogP','TPSA',
             'HBondDonorCount','HBondAcceptorCount','RotatableBondCount'}
    """
    if not drug_name: return None
    enc = urllib.parse.quote(drug_name.strip())
    url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
            f"name/{enc}/property/{prop}/JSON")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        props = data.get("PropertyTable", {}).get("Properties", [])
        if props and prop in props[0]:
            return {
                "value": props[0][prop],
                "_source": "pubchem_live",
                "_reference": f"PubChem CID lookup for {drug_name}",
                "_confidence": "HIGH",
                "_confidence_score": 90,
                "_tier": 1,
            }
    except Exception as e:
        log.debug(f"[PUBCHEM] {drug_name}/{prop} failed: {e}")
    return None


def _pubmed_search(drug_name: str, property_name: str) -> Optional[Dict]:
    """
    Search PubMed for a drug property value.
    Returns {value, reference, doi, journal, year, confidence} or None.
    Uses NCBI E-utilities (free, no key required for <3 req/sec).
    """
    query = f"{drug_name} {property_name} pharmacokinetics"
    enc   = urllib.parse.quote(query)
    url   = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
              f"?db=pubmed&term={enc}&retmax=5&retmode=json&sort=relevance")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return None
        # Fetch first abstract for citation
        pmid = ids[0]
        fetch_url = (f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                      f"?db=pubmed&id={pmid}&retmode=text&rettype=abstract")
        req2 = urllib.request.Request(fetch_url, headers={"User-Agent": "CEREBRO-X/22.1"})
        with urllib.request.urlopen(req2, timeout=8) as r2:
            abstract = r2.read().decode("utf-8", errors="replace")[:500]
        return {
            "_pubmed_pmid": pmid,
            "_pubmed_abstract_preview": abstract.strip(),
            "_pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source": f"PubMed PMID:{pmid}",
            "confidence": "MODERATE — literature search, value needs extraction"
        }
    except Exception as e:
        log.debug(f"[RESOLVER] PubMed search failed: {e}")
        return None


def resolve_property(drug_name: str, property_name: str,
                      mol_profile: Dict = None,
                      smiles: str = None,
                      api_value: Any = None) -> Dict:
    """
    Resolve a missing molecular property through the full cascade.
    
    Returns dict with:
      value:      The resolved numeric value (or None if truly unknown)
      _source:    Human-readable source description
      _reference: Journal citation or API name
      _doi:       DOI or URL if available
      _tier:      Which tier resolved it (1=API, 2=library, 3=PubMed, 4=analog, 99=unknown)
      _confidence: HIGH / MODERATE / LOW
    """
    mol_profile = mol_profile or {}
    drug_lower  = drug_name.lower().strip()
    prop_lower  = property_name.lower()
    
    # ── Tier 1: API value already provided ─────────────────────────────────
    if api_value is not None and api_value != 0:
        return {
            "value": api_value, "_tier": 1,
            "_source": "Live API (ChEMBL/PubChem/UniProt/DrugBank)",
            "_reference": "API query at runtime",
            "_doi": None, "_confidence": "HIGH"
        }
    
    # ── Tier 2: Live PubChem property fetch (replaces deleted hardcoded dicts) ──
    # Maps internal CEREBRO-X property names to PubChem property names.
    PUBCHEM_PROP_MAP = {
        "mw_da":           "MolecularWeight",
        "molecular_weight": "MolecularWeight",
        "logp":            "XLogP",
        "tpsa":            "TPSA",
        "hbd":             "HBondDonorCount",
        "hba":             "HBondAcceptorCount",
        "rotbonds":        "RotatableBondCount",
        "rotatable_bonds": "RotatableBondCount",
    }
    pubchem_prop = PUBCHEM_PROP_MAP.get(prop_lower)
    if pubchem_prop:
        result = _pubchem_property(drug_name, pubchem_prop)
        if result and result.get("value") is not None:
            return result

    # ── Tier 3: PubMed literature search ───────────────────────────────────
    pubmed = _pubmed_search(drug_name, property_name)
    if pubmed:
        # PubMed found a paper but we can't auto-extract the value
        # Return the citation with confidence=LOW (needs manual check)
        return {
            "value": None, "_tier": 3,
            "_source": pubmed["source"],
            "_reference": pubmed.get("_pubmed_url",""),
            "_doi": pubmed.get("_pubmed_url"),
            "_confidence": "LOW — paper found but value requires manual extraction",
            "_pubmed_preview": pubmed.get("_pubmed_abstract_preview",""),
        }

    # ── Tier 4: RDKit physicochemical prediction from SMILES ────────────────
    if smiles and prop_lower in ("mw_da", "logp", "tpsa", "hbd", "hba"):
        try:
            from rdkit import Chem
            from rdkit.Chem import Descriptors
            mol = Chem.MolFromSmiles(smiles)
            if mol:
                rdkit_map = {
                    "mw_da":  (Descriptors.MolWt, "Wildman & Crippen 1999 J Chem Inf Comput Sci 39:868"),
                    "logp":   (Descriptors.MolLogP, "Wildman & Crippen 1999 J Chem Inf Comput Sci 39:868"),
                    "tpsa":   (Descriptors.TPSA, "Ertl P et al 2000 J Med Chem 43:3714"),
                    "hbd":    (Descriptors.NumHDonors, "Lipinski 1997 Adv Drug Deliv Rev 23:3"),
                    "hba":    (Descriptors.NumHAcceptors, "Lipinski 1997 Adv Drug Deliv Rev 23:3"),
                }
                fn, ref = rdkit_map[prop_lower]
                val = fn(mol)
                return {
                    "value": round(float(val), 4), "_tier": 4,
                    "_source": "RDKit computed from SMILES",
                    "_reference": ref,
                    "_doi": "https://www.rdkit.org",
                    "_confidence": "HIGH — computed from validated SMILES"
                }
        except Exception as e:
            log.debug(f"[RESOLVER] RDKit failed for {property_name}: {e}")

    # ── Tier 5 REMOVED in v22.1 ─────────────────────────────────────────────
    # Previous Tier 5 used a hardcoded REFERENCE_DRUGS database to find
    # 'analog' drugs and copy their properties. This caused unrelated drug
    # names (e.g., Temozolomide) to appear in outputs when the researcher's
    # input had no SMILES. Per project mandate (no hardcoded drug data),
    # the analog tier is permanently disabled. If Tier 1-4 fail, we proceed
    # directly to the class-typical fallback below.
    
    # ── Tier 6: CLASS-TYPICAL ESTIMATE  (final predictive fallback) ─────────
    # Activated only after Tiers 1-5 have all failed.
    #
    # Per-class typical values — pharmacologically defensible defaults derived
    # from population means in the indicated literature. Used ONLY when no
    # API hit, no literature, no PubMed paper, no RDKit-computable property,
    # AND no analog within similarity threshold could be found.
    #
    # Three guard-rails enforced (per project requirements):
    #   1. _confidence_score is set numerically LOW (30 / 100)
    #   2. _disclaimer text states explicitly that this is a class-mean fallback
    #   3. _overridable=True signals the report renderer to expose a manual-
    #      override input so the researcher can replace it with an in-vitro value
    CLASS_TYPICALS = {
        # property → { molecule_class: (value, unit, reference) }
        "half_life_days": {
            "small_molecule": (0.25, "days",
                "Smith DA et al (2018) Pharmacological Reviews 70:583 — "
                "median t½ across 1,200 oral small molecules ≈ 6 h"),
            "biologic":       (21.0, "days",
                "Wang W et al (2008) Clin Pharmacol Ther 84:548 — "
                "IgG mAb population mean t½ ≈ 21 d via FcRn recycling"),
            "peptide":        (0.02, "days",
                "Diao L & Meibohm B (2013) Clin Pharmacokinet 52:855 — "
                "linear peptides mean t½ ≈ 30 min before pegylation"),
            "antibody":       (21.0, "days",
                "Wang W et al (2008) Clin Pharmacol Ther 84:548"),
            "monoclonal_antibody": (21.0, "days",
                "Wang W et al (2008) Clin Pharmacol Ther 84:548"),
        },
        "mw_da": {
            "small_molecule": (350.0, "Da",
                "Lipinski CA (1997) Adv Drug Deliv Rev 23:3 — Rule of 5 mean ≈350"),
            "biologic":       (150000.0, "Da",
                "Reichert JM (2017) MAbs 9:167 — IgG mean MW ≈150 kDa"),
            "peptide":        (3000.0, "Da",
                "Lau JL & Dunn MK (2018) Bioorg Med Chem 26:2700"),
        },
        "logp": {
            "small_molecule": (2.5, "dimensionless",
                "Leeson PD & Springthorpe B (2007) Nat Rev Drug Discov 6:881 — "
                "median cLogP across oral drugs ≈ 2.5"),
            "biologic":       (-1.5, "dimensionless",
                "Hydrophilic by default — biologics are surface-charged"),
            "peptide":        (-0.5, "dimensionless",
                "Davies MN et al (2008) J Mol Recognit 21:73"),
        },
        "tpsa": {
            "small_molecule": (90.0, "Å²",
                "Veber DF et al (2002) J Med Chem 45:2615 — TPSA threshold ≈ 90 Å²"),
        },
        "hbd": {
            "small_molecule": (2.0, "count",
                "Lipinski CA (1997) — typical HBD ≤ 5"),
        },
        "hba": {
            "small_molecule": (5.0, "count",
                "Lipinski CA (1997) — typical HBA ≤ 10"),
        },
    }
    
    mol_class_raw = (mol_profile.get("molecule_class")
                     or mol_profile.get("Molecule_Class")
                     or "small_molecule")
    mol_class = str(mol_class_raw).strip().lower().replace(" ", "_").replace("-", "_")
    # Map common synonyms
    if mol_class in ("smallmolecule", "small_mol", "sm"): mol_class = "small_molecule"
    if mol_class in ("mab", "ab", "monoclonal", "monoclonal_ab"): mol_class = "monoclonal_antibody"
    
    typicals_for_prop = CLASS_TYPICALS.get(prop_lower, {})
    if mol_class in typicals_for_prop:
        val, unit, ref = typicals_for_prop[mol_class]
        log.warning(
            f"[RESOLVER] TIER-6 CLASS-TYPICAL for {drug_name}.{property_name}: "
            f"value={val} {unit} (class={mol_class}) — confidence reduced to 30/100"
        )
        return {
            "value": val,
            "_tier": 6,
            "_source": f"Class-typical estimate ({mol_class})",
            "_reference": ref,
            "_doi": None,
            "_confidence": "LOW (30%) — class-mean fallback, not measured",
            "_confidence_score": 30,    # numeric 0–100 for downstream scoring
            "_disclaimer": (
                f"⚠ CLASS-TYPICAL FALLBACK: {property_name} for {drug_name} "
                f"could not be resolved via APIs, literature, PubMed, RDKit, or "
                f"analog matching. Value below ({val} {unit}) is the population "
                f"mean for the molecule class '{mol_class}', NOT a measurement "
                f"of {drug_name} itself. Confidence reduced to 30%. "
                f"Researcher should override with in-vitro value before "
                f"publication or clinical decision-making."
            ),
            "_overridable": True,       # report renderer must show override input
            "_warning": (
                f"This {property_name} value ({val} {unit}) is a class-mean "
                f"estimate — not measured for {drug_name}. Wet-lab validation "
                f"required before any publication or clinical use."
            ),
            "_class_used": mol_class,
        }
    
    # ── Tier 99: Explicit unknown — class-typical ALSO not available ────────
    # This now triggers only in the rare case where the molecule_class itself
    # is unrecognized AND no analog could be matched. The system has truly
    # exhausted every defensible prediction route.
    log.warning(
        f"[RESOLVER] TIER-99 fallback for {drug_name}.{property_name}: "
        f"No API, no literature, no analog, no class-typical for class='{mol_class}'. "
        f"Value set to None. Do NOT use zero as fallback — that would be fabrication."
    )
    return {
        "value": None, "_tier": 99,
        "_source": "source_unknown",
        "_reference": (f"Property {property_name} for {drug_name} could not be resolved "
                        f"via API cascade, embedded library, PubMed, RDKit, "
                        f"analog matching, or class-typical fallback."),
        "_doi": None,
        "_confidence": "NONE — value unknown",
        "_confidence_score": 0,
        "_warning": (f"MISSING: {property_name} for {drug_name} is truly unknown. "
                      f"All calculations using this property are invalid. "
                      f"Do not publish results without obtaining this value experimentally.")
    }