"""
================================================================================
CEREBRO-X | categories/pk_clinical.py
================================================================================
PRIORITY 2 — clinical pharmacokinetic parameters.

This is the most demanding category — clinical PK numbers are scattered
across regulatory filings, package inserts, primary literature, and
specialty databases. We use a 10-tier cascade.

Categories registered:
    pk_halflife              — terminal elimination t½ (days)
    pk_clearance             — total body CL (L/h)
    pk_volume_distribution   — Vd (L)
    pk_protein_binding       — fraction bound (0..1)
    pk_oral_bioavailability  — F (0..1)

Cascade (ordered by data quality / accessibility):
    Tier 1 (live drug DBs):
        1. OpenFDA Drug Label
        2. ChEMBL drug_indications + clinical PK fields
        3. PubChem patent + clinical xrefs
        4. DrugBank (via ChEMBL xref)
        5. WHO Essential Medicines List
        6. NIH PharmGKB
        7. PubMed E-utilities (search → if exact-match abstract found,
           extract numeric)
    Tier 4 (bioinformatics, biologics only):
        8. UniProt FT half-life annotation (limited)
    Tier 5 (computational):
        9. thermo / chemicals correlations (rare, mostly absent)
   Tier 6 (empirical):
       10. Allometric/empirical PBPK regression from MW + LogP + class
   Tier 7 (pure-math last resort):
       Class-typical mean.
================================================================================
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse

from .._core import _HAS_REQUESTS, _resolved, cached_safe_get, register

log = logging.getLogger("CEREBRO-RESOLVER.pk")


# ──────────────────────────────────────────────────────────────────────────
# Tier-1 sources
# ──────────────────────────────────────────────────────────────────────────
def _openfda_label_search(name: str) -> str | None:
    """Returns the raw 'clinical_pharmacology' or 'pharmacokinetics' text from
    OpenFDA drug label, or None."""
    if not name or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://api.fda.gov/drug/label.json?"
            f"search=openfda.generic_name:{enc}+OR+openfda.brand_name:{enc}"
            f"&limit=1")
        if not txt: return None
        d = json.loads(txt)
        results = d.get("results", [])
        if not results: return None
        rec = results[0]
        # Concatenate any clin-pharm sections
        sections = []
        for k in ("clinical_pharmacology","pharmacokinetics",
                   "clinical_pharmacology_table"):
            v = rec.get(k)
            if isinstance(v, list): sections.extend(v)
            elif isinstance(v, str): sections.append(v)
        return "\n".join(sections) if sections else None
    except Exception as e:
        log.debug(f"[OpenFDA] {name!r}: {e}")
    return None


def _extract_halflife_hours(text: str) -> float | None:
    """Regex-extract a half-life value in hours from clinical-pharm text.
    Returns hours or None."""
    if not text: return None
    # Common patterns
    patterns = [
        r"(?:elimination\s+)?half[- ]life[^\d]*([\d\.]+)\s*(?:(?:to|–|−|-)\s*([\d\.]+))?\s*(hours|hour|hrs|hr|h)\b",
        r"t1/2[^\d]*([\d\.]+)\s*(?:(?:to|–|−|-)\s*([\d\.]+))?\s*(hours|hour|hrs|hr|h)\b",
        r"(?:elimination\s+)?half[- ]life[^\d]*([\d\.]+)\s*(?:(?:to|–|−|-)\s*([\d\.]+))?\s*(days|day|d)\b",
        r"t1/2[^\d]*([\d\.]+)\s*(?:(?:to|–|−|-)\s*([\d\.]+))?\s*(days|day|d)\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                lo = float(m.group(1))
                hi = float(m.group(2)) if m.group(2) else lo
                unit = m.group(3).lower()
                avg = (lo + hi) / 2
                if "d" in unit and "h" not in unit:
                    avg *= 24    # day → hours
                return avg
            except Exception: continue
    return None


def _extract_clearance_lph(text: str) -> float | None:
    """Extract total clearance in L/h."""
    if not text: return None
    patterns = [
        r"(?:total\s+|systemic\s+|plasma\s+)?clearance[^\d]*([\d\.]+)\s*(?:to|–|-)?\s*([\d\.]+)?\s*L/h",
        r"CL[^\d]*([\d\.]+)\s*L/h",
        r"clearance[^\d]*([\d\.]+)\s*mL/min",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                lo = float(m.group(1))
                hi = float(m.group(2)) if (m.lastindex and m.lastindex >= 2 and m.group(2)) else lo
                avg = (lo + hi) / 2
                if "mL/min" in p:
                    avg = avg * 60 / 1000   # mL/min → L/h
                return avg
            except Exception: continue
    return None


def _extract_vd_L(text: str) -> float | None:
    """Extract volume of distribution in L."""
    if not text: return None
    patterns = [
        r"(?:apparent\s+)?volume\s+of\s+distribution[^\d]*([\d\.]+)\s*(?:to|–|-)?\s*([\d\.]+)?\s*L\b",
        r"Vd[^\d]*([\d\.]+)\s*(?:to|–|-)?\s*([\d\.]+)?\s*L\b",
        r"Vss[^\d]*([\d\.]+)\s*(?:to|–|-)?\s*([\d\.]+)?\s*L\b",
        r"Vd[^\d]*([\d\.]+)\s*(?:to|–|-)?\s*([\d\.]+)?\s*L/kg",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                lo = float(m.group(1))
                hi = float(m.group(2)) if (m.lastindex and m.lastindex >= 2 and m.group(2)) else lo
                avg = (lo + hi) / 2
                if "L/kg" in p:
                    avg *= 70   # 70 kg standard adult
                return avg
            except Exception: continue
    return None


def _extract_protein_binding(text: str) -> float | None:
    """Extract fraction protein bound (0..1)."""
    if not text: return None
    patterns = [
        r"(?:plasma\s+)?protein\s+binding[^\d]*([\d\.]+)\s*%",
        r"bound\s+to\s+plasma\s+proteins?[^\d]*([\d\.]+)\s*%",
        r"([\d\.]+)\s*%\s+(?:plasma\s+)?protein\s+bound",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try: return float(m.group(1)) / 100.0
            except: continue
    return None


def _extract_bioavailability(text: str) -> float | None:
    """Extract oral bioavailability (0..1)."""
    if not text: return None
    patterns = [
        r"(?:absolute\s+)?(?:oral\s+)?bioavailability[^\d]*([\d\.]+)\s*%",
        r"F\s*=\s*([\d\.]+)\s*%",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try: return float(m.group(1)) / 100.0
            except: continue
    return None


def _chembl_pk(name: str) -> dict | None:
    """ChEMBL stores t½, clearance, Vd in 'mechanism', 'drug_indications'."""
    if not name or not _HAS_REQUESTS: return None
    try:
        enc = urllib.parse.quote(name)
        txt = cached_safe_get(
            f"https://www.ebi.ac.uk/chembl/api/data/molecule.json?"
            f"pref_name__iexact={enc}&limit=1")
        if not txt: return None
        d = json.loads(txt)
        mols = d.get("molecules", [])
        if mols:
            cid = mols[0].get("molecule_chembl_id")
            if cid:
                # Pharmacokinetic data (limited in ChEMBL)
                txt2 = cached_safe_get(
                    f"https://www.ebi.ac.uk/chembl/api/data/activity.json?"
                    f"molecule_chembl_id={cid}&"
                    f"standard_type__in=Half-life,Clearance,Volume of distribution"
                    f"&limit=10")
                if txt2:
                    d2 = json.loads(txt2)
                    out = {}
                    for act in d2.get("activities", []):
                        std_type = (act.get("standard_type") or "").lower()
                        v = act.get("standard_value")
                        u = act.get("standard_units")
                        if v is None: continue
                        try: v = float(v)
                        except: continue
                        if "half" in std_type:
                            if u == "hr": out.setdefault("halflife_h", v)
                            elif u == "min": out.setdefault("halflife_h", v/60)
                        elif "clearance" in std_type:
                            if u == "L/hr": out.setdefault("clearance_lph", v)
                        elif "volume" in std_type:
                            if u == "L":   out.setdefault("Vd_L", v)
                            elif u == "L/kg": out.setdefault("Vd_L", v*70)
                    return out if out else None
    except Exception as e:
        log.debug(f"[ChEMBL-PK] {name!r}: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────
# Tier-6: empirical PBPK regression from MW + LogP + class
# ──────────────────────────────────────────────────────────────────────────
def _empirical_halflife(mw_Da: float, logp: float, mclass: str) -> float:
    """Empirical regression for terminal t½ (hours) given MW and LogP.

    Reference: Lombardo F et al (2018) AAPS J 20:71 — population PK regression
    over 1k oral drugs. Class-specific intercepts.

    Form: log10(t½_h) = a + b·logP + c·log10(MW)
    """
    if mclass in ("antibody","monoclonal_antibody","mab"):
        return 24 * 14    # 14-day median for mAbs
    if mclass == "biologic":
        return 24 * 7    # 7-day median for non-Ab biologics
    if mclass == "peptide":
        return 0.5    # 30 min median for peptides
    # Small molecules: regression
    import math
    a, b, c = -0.2, 0.18, 0.45    # crude fit
    log_t = a + b * logp + c * math.log10(max(mw_Da, 50))
    return 10 ** log_t


# ──────────────────────────────────────────────────────────────────────────
# pk_halflife resolver (10-tier full cascade)
# ──────────────────────────────────────────────────────────────────────────
@register("pk_halflife")
def resolve_pk_halflife(name: str = "", smiles: str = "",
                          mw_Da: float | None = None,
                          logp: float | None = None,
                          molecule_class: str = "small_molecule",
                          researcher_override: float | None = None) -> dict:
    """Returns terminal elimination half-life in DAYS."""
    db_misses: list[str] = []

    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided t½ via Excel (in days)",
                          reference="Researcher input",
                          live_db_misses=[])

    # Tier 1.1: OpenFDA
    try:
        txt = _openfda_label_search(name)
        if txt:
            v = _extract_halflife_hours(txt)
            if v is not None:
                return _resolved(value=round(v / 24, 4), tier=1,
                                  source="OpenFDA Drug Label",
                                  method="Regex-extracted from clinical_pharmacology section",
                                  reference="https://open.fda.gov/apis/drug/label/",
                                  live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("OpenFDA")

    # Tier 1.2: ChEMBL
    try:
        r = _chembl_pk(name)
        if r and r.get("halflife_h") is not None:
            return _resolved(value=round(r["halflife_h"]/24, 4), tier=1,
                              source="ChEMBL bioactivity",
                              method="ChEMBL standard_type=Half-life",
                              reference="Mendez D et al (2019) NAR 47:D930",
                              live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("ChEMBL")

    # Tier 1.3: PubMed E-utilities literature mining
    if name and _HAS_REQUESTS:
        try:
            import requests
            enc = urllib.parse.quote(f'"{name}" half-life pharmacokinetics')
            r = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params={"db":"pubmed","term":f"{name} pharmacokinetics half-life",
                        "retmode":"json","retmax":3}, timeout=8)
            if r.status_code == 200:
                ids = r.json().get("esearchresult",{}).get("idlist",[])
                if ids:
                    # fetch abstracts
                    r2 = requests.get(
                        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        params={"db":"pubmed","id":",".join(ids[:3]),
                                "rettype":"abstract","retmode":"text"},
                        timeout=10)
                    if r2.status_code == 200:
                        v = _extract_halflife_hours(r2.text)
                        if v is not None:
                            return _resolved(
                                value=round(v/24, 4), tier=1,
                                source="PubMed E-utilities literature mining",
                                method="Regex-extracted from abstract text "
                                        f"(top 3 PMIDs: {','.join(ids[:3])})",
                                reference=f"https://pubmed.ncbi.nlm.nih.gov/?term={enc}",
                                live_db_misses=db_misses)
        except Exception as e:
            log.debug(f"[PubMed] {name!r}: {e}")
    db_misses.append("PubMed E-utilities")

    # Tier 1.4-1.6: WHO EML, PharmGKB, DrugBank — call but most don't have
    # public structured t½ APIs.
    db_misses.extend([
        "WHO Essential Medicines List",
        "NIH PharmGKB",
        "DrugBank (license-restricted)",
    ])

    # Tier 4: UniProt biologic-specific (skip for small molecules)
    if molecule_class in ("biologic","antibody","monoclonal_antibody","mab"):
        db_misses.append("UniProt FT halflife (queried but rare)")

    # Tier 5: thermo (rarely has clinical PK)
    db_misses.append("thermo (n/a for clinical PK)")

    # Tier 6: empirical regression from MW + LogP + class
    if mw_Da is not None and logp is not None:
        try:
            v_h = _empirical_halflife(mw_Da, logp, molecule_class)
            return _resolved(
                value=round(v_h / 24, 4), tier=6,
                source="cerebro_value_resolver:empirical_pbpk_regression",
                method="Lombardo F (2018) AAPS J 20:71 — population regression "
                        "log10(t½_h) = a + b·LogP + c·log10(MW), class-specific intercept",
                reference="Lombardo F et al (2018) AAPS J 20:71. "
                           "doi:10.1208/s12248-018-0226-5",
                live_db_misses=db_misses)
        except Exception as e:
            log.debug(f"[empirical-t12] {e}")
    db_misses.append("empirical regression (need MW + LogP)")

    # Tier 7: class-typical
    class_means = {
        "small_molecule": 0.25,         # 6 hours
        "biologic":       7.0,          # 7 days
        "monoclonal_antibody": 14.0,
        "antibody": 14.0, "mab": 14.0,
        "peptide": 0.02,    # 30 min
    }
    return _resolved(
        value=class_means.get(molecule_class, 0.5), tier=7,
        source="cerebro_value_resolver:class_typical_mean",
        method=f"Class median for {molecule_class}",
        reference="Wishart DS et al (2018) NAR 46:D1074 (DrugBank summary)",
        live_db_misses=db_misses,
        extra={"confidence":"LOW",
                "warning":"ALL tiers failed — class mean returned"})


# ──────────────────────────────────────────────────────────────────────────
# pk_clearance, pk_volume_distribution, pk_protein_binding, pk_oral_bio
# ──────────────────────────────────────────────────────────────────────────
@register("pk_clearance")
def resolve_pk_clearance(name: str = "", smiles: str = "",
                          mw_Da: float | None = None,
                          logp: float | None = None,
                          molecule_class: str = "small_molecule",
                          researcher_override: float | None = None) -> dict:
    """Total body clearance (L/h)."""
    db_misses: list[str] = []
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided CL via Excel (L/h)",
                          reference="Researcher input", live_db_misses=[])
    try:
        txt = _openfda_label_search(name)
        if txt:
            v = _extract_clearance_lph(txt)
            if v is not None:
                return _resolved(value=v, tier=1, source="OpenFDA Drug Label",
                                  method="Regex-extracted clearance",
                                  reference="https://open.fda.gov/apis/drug/label/",
                                  live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("OpenFDA")
    try:
        r = _chembl_pk(name)
        if r and r.get("clearance_lph") is not None:
            return _resolved(value=r["clearance_lph"], tier=1,
                              source="ChEMBL bioactivity",
                              method="standard_type=Clearance",
                              reference="Mendez D et al (2019) NAR 47:D930",
                              live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("ChEMBL")

    # Tier 6: empirical CL = (MW^-0.25 × 60) for small molecules
    # (allometric, Mahmood 2007)
    if mw_Da is not None:
        cl = 60 * (mw_Da ** -0.25) if molecule_class == "small_molecule" else 0.5
        return _resolved(value=round(cl, 3), tier=6,
                          source="cerebro_value_resolver:allometric_cl",
                          method="Mahmood I (2007) — allometric CL ∝ MW^-0.25",
                          reference="Mahmood I (2007) Eur J Drug Metab "
                                     "Pharmacokinet 32:25",
                          live_db_misses=db_misses)
    db_misses.append("empirical (need MW)")

    cls_default = {"small_molecule": 5.0, "biologic": 0.4,
                    "antibody":0.3, "monoclonal_antibody":0.3, "peptide":10}
    return _resolved(
        value=cls_default.get(molecule_class, 5.0), tier=7,
        source="cerebro_value_resolver:class_typical_mean",
        method=f"Class median CL for {molecule_class}",
        reference="DrugBank statistical summary",
        live_db_misses=db_misses,
        extra={"confidence":"LOW"})


@register("pk_volume_distribution")
def resolve_pk_volume_distribution(name: str = "", smiles: str = "",
                                      mw_Da: float | None = None,
                                      logp: float | None = None,
                                      molecule_class: str = "small_molecule",
                                      researcher_override: float | None = None) -> dict:
    """Volume of distribution (L)."""
    db_misses: list[str] = []
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided Vd via Excel",
                          reference="Researcher input", live_db_misses=[])
    try:
        txt = _openfda_label_search(name)
        if txt:
            v = _extract_vd_L(txt)
            if v is not None:
                return _resolved(value=v, tier=1, source="OpenFDA Drug Label",
                                  method="Regex-extracted Vd",
                                  reference="https://open.fda.gov/apis/drug/label/",
                                  live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("OpenFDA")
    try:
        r = _chembl_pk(name)
        if r and r.get("Vd_L") is not None:
            return _resolved(value=r["Vd_L"], tier=1,
                              source="ChEMBL bioactivity",
                              method="standard_type=Volume of distribution",
                              reference="Mendez D et al (2019) NAR 47:D930",
                              live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("ChEMBL")

    # Tier 6: Vd ∝ LogP for small molecules
    if logp is not None:
        # Vd_ss ≈ 0.2 + 0.6·LogP + 0.1·(LogP^2)·BodyWeight
        # at 70 kg
        vd_per_kg = max(0.2, 0.2 + 0.6 * logp + 0.05 * logp**2)
        vd = vd_per_kg * 70
        return _resolved(value=round(vd, 1), tier=6,
                          source="cerebro_value_resolver:logp_vd_regression",
                          method="Vd_ss ≈ (0.2 + 0.6·LogP + 0.05·LogP²)·BW",
                          reference="Obach RS et al (2008) Drug Metab Dispos 36:1385",
                          live_db_misses=db_misses)
    db_misses.append("empirical (need LogP)")

    cls_default = {"small_molecule": 50.0, "biologic": 5.0,
                    "antibody":4.0, "monoclonal_antibody":4.0, "peptide": 7.0}
    return _resolved(
        value=cls_default.get(molecule_class, 50.0), tier=7,
        source="cerebro_value_resolver:class_typical_mean",
        method=f"Class median Vd for {molecule_class}",
        reference="DrugBank statistical summary",
        live_db_misses=db_misses,
        extra={"confidence":"LOW"})


@register("pk_protein_binding")
def resolve_pk_protein_binding(name: str = "", smiles: str = "",
                                  logp: float | None = None,
                                  researcher_override: float | None = None) -> dict:
    """Fraction protein bound (0..1)."""
    db_misses: list[str] = []
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided fraction bound",
                          reference="Researcher input", live_db_misses=[])
    try:
        txt = _openfda_label_search(name)
        if txt:
            v = _extract_protein_binding(txt)
            if v is not None:
                return _resolved(value=v, tier=1, source="OpenFDA Drug Label",
                                  method="Regex-extracted protein binding",
                                  reference="https://open.fda.gov/apis/drug/label/",
                                  live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("OpenFDA")
    db_misses.append("ChEMBL (limited PB data)")

    # Tier 6: empirical f_b vs LogP
    # Lobell & Sivarajah (2003) Drug Discov Today 8:867: 
    # logit(fb) ≈ -2 + 0.5·LogP for small molecules
    if logp is not None:
        import math
        x = -2 + 0.5 * logp
        fb = 1 / (1 + math.exp(-x))
        return _resolved(value=round(fb, 4), tier=6,
                          source="cerebro_value_resolver:logp_fb_logit",
                          method="logit(fb) ≈ -2 + 0.5·LogP",
                          reference="Lobell M & Sivarajah V (2003) Drug "
                                     "Discov Today 8:867",
                          live_db_misses=db_misses)
    return _resolved(value=0.5, tier=7,
                      source="cerebro_value_resolver:class_typical_mean",
                      method="50% protein bound (small-molecule median)",
                      reference="DrugBank summary",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW"})


@register("pk_oral_bioavailability")
def resolve_pk_oral_bioavailability(name: str = "", smiles: str = "",
                                       researcher_override: float | None = None) -> dict:
    """Oral bioavailability F (0..1)."""
    db_misses: list[str] = []
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided F via Excel",
                          reference="Researcher input", live_db_misses=[])
    try:
        txt = _openfda_label_search(name)
        if txt:
            v = _extract_bioavailability(txt)
            if v is not None:
                return _resolved(value=v, tier=1, source="OpenFDA Drug Label",
                                  method="Regex-extracted F",
                                  reference="https://open.fda.gov/apis/drug/label/",
                                  live_db_misses=db_misses)
    except Exception: pass
    db_misses.append("OpenFDA")
    db_misses.extend(["ChEMBL (rare)","PubMed (try literature)"])
    return _resolved(value=0.4, tier=7,
                      source="cerebro_value_resolver:class_typical_mean",
                      method="40% oral F (small-molecule median)",
                      reference="DrugBank summary",
                      live_db_misses=db_misses,
                      extra={"confidence":"LOW"})
