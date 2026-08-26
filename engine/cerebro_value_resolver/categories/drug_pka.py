"""
================================================================================
CEREBRO-X | categories/drug_pka.py
================================================================================
PRIORITY 1 — pKa resolution (acidic + basic separately).

Categories registered:
    drug_pka_acidic    — strongest acidic pKa (most ionized at physiological pH)
    drug_pka_basic     — strongest basic pKa
    drug_pka_dominant  — pKa closest to pH 7.4
    drug_microspecies  — full Bjerrum 4-microspecies fractions at pH 7.4
================================================================================
"""
from __future__ import annotations

import json
import logging
import urllib.parse

from .._core import (
    _HAS_REQUESTS,
    _HAS_THERMO,
    _resolved,
    cached_safe_get,
    register,
)
from ..computations import (
    compute_pka_from_first_principles,
    find_x_h_bonds_in_smiles,
    hh_microspeciation,
    select_dominant_pka,
)
from ..computations.pka_first_principles import (
    compute_pka_BH_plus_from_first_principles,
    find_basic_sites_in_smiles,
    select_dominant_pka_BH_plus,
)

log = logging.getLogger("CEREBRO-RESOLVER.pka")


# ──────────────────────────────────────────────────────────────────────────
# Tier-1: live DBs that report pKa
# ──────────────────────────────────────────────────────────────────────────
def _pka_chembl(name: str) -> dict | None:
    """ChEMBL records 'acd_logp', 'acd_logd', 'acd_most_apka', 'acd_most_bpka'.
    Returns dict {acidic, basic} or None."""
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
            apka = props.get("acd_most_apka")
            bpka = props.get("acd_most_bpka")
            r = {}
            if apka is not None: r["acidic"] = float(apka)
            if bpka is not None: r["basic"]  = float(bpka)
            return r if r else None
    except Exception: pass
    return None


def _pka_drugbank_xref(name: str) -> dict | None:
    """DrugBank's pKa via ChEMBL xref (DrugBank API requires license)."""
    return _pka_chembl(name)    # ChEMBL aggregates DrugBank


def _pka_pubchem_classification(name: str) -> dict | None:
    """PubChem rarely exposes pKa as a property, but we can try."""
    return None


# ──────────────────────────────────────────────────────────────────────────
# Tier-5: thermo
# ──────────────────────────────────────────────────────────────────────────
def _pka_thermo(name: str) -> dict | None:
    if not _HAS_THERMO or not name: return None
    try:
        from thermo import Chemical
        c = Chemical(name)
        # thermo doesn't directly give pKa for arbitrary molecules
        return None
    except Exception: return None


# ──────────────────────────────────────────────────────────────────────────
# Tier-7: pure-math group-contribution pKa
# Reference: Bryantsev & Goddard (2007) J Phys Chem A 111:6422 + Lee et al
# (2018) J Comput Aided Mol Des 32:1037
# ──────────────────────────────────────────────────────────────────────────
PKA_GROUPS = [
    # (SMARTS pattern, type, pKa_value, label)
    ("[CX3](=O)[OX2H]",          "acid", 4.2,  "carboxylic acid"),
    ("c[OX2H]",                    "acid", 9.5,  "phenol"),
    ("[SX4](=O)(=O)[OX2H]",       "acid", -2.0, "sulfonic acid"),
    ("[PX4](=O)([OX2H])([OX2H])", "acid", 2.1,  "phosphate"),
    ("[NX2H]C(=O)",                "acid", 14.5, "amide N-H"),
    ("[NX3]([CX4])([CX4])[CX4]",  "base", 9.8,  "tertiary amine"),
    ("[NX3H]([CX4])[CX4]",         "base", 10.5, "secondary amine"),
    ("[NX3H2][CX4]",               "base", 10.6, "primary amine"),
    ("c1ccncc1",                   "base", 5.2,  "pyridine"),
    ("[nX2]",                      "base", 6.0,  "imidazole-like N"),
    ("[NX3]([CX4])(C)C(=N)",      "base", 12.5, "guanidine"),
]


def _pka_t7_groups(smiles: str) -> dict | None:
    """First-principles pKa via Bordwell-Hammett-Born hybrid.

    Identifies ALL ionizable X-H bonds in the SMILES and computes a pKa
    for each from first principles (no hardcoded molecule-specific values).
    The atom-class base values come from Reich's Bordwell pKa Tables (a
    peer-reviewed compilation of experimental pKa data) and are corrected
    per molecule by BDE shift, Hammett inductive effects, and Born solvation.

    Returns dict with 'acidic', 'basic', and computational provenance.
    """
    if not smiles:
        return None
    try:
        # X-H bonds for ACIDIC pKa (Bordwell-Hammett-Born)
        bonds = find_x_h_bonds_in_smiles(smiles)
        # Lone-pair sites for BASIC pKa(BH+)
        basic_sites = find_basic_sites_in_smiles(smiles)

        # Acidic side
        dom_acid = select_dominant_pka(bonds, "acidic") if bonds else None
        # Basic side: use lone-pair sites, NOT X-H acidity
        dom_basic_BH = select_dominant_pka_BH_plus(basic_sites) if basic_sites else None

        # If no X-H bonds at all, compute generic
        if not bonds:
            generic = compute_pka_from_first_principles(
                "H_C_sp3", neighbour_atoms=["C","C"])
            dom_acid_pka = generic["pKa"]
            acid_label = "computed_sp3_CH_generic"
            acid_method = generic["_computational_method"]
        else:
            dom_acid_pka = dom_acid["pKa"]
            acid_label = dom_acid["bond_type"]
            acid_method = dom_acid["_computational_method"]

        # If no basic lone-pair sites, compute generic non-basic estimate
        if not basic_sites:
            generic_BH = compute_pka_BH_plus_from_first_principles(
                "no_basic_site", neighbour_atoms=["C"])
            dom_basic_pka = generic_BH["pKa"]
            basic_label = "no_basic_site_computed"
            basic_method = generic_BH["_computational_method"]
        else:
            dom_basic_pka = dom_basic_BH["pKa"]
            basic_label = dom_basic_BH["site_type"]
            basic_method = dom_basic_BH["_computational_method"]

        return {
            "acidic": dom_acid_pka,
            "basic":  dom_basic_pka,
            "acidic_label": acid_label,
            "basic_label":  basic_label,
            "canonical_acidic_groups_found": [b for b in bonds if "carboxyl" in b
                                                  or "phenol" in b
                                                  or "phosphonic" in b],
            "canonical_basic_groups_found":  list(basic_sites.keys()),
            "_computational_method_acidic": acid_method,
            "_computational_method_basic":  basic_method,
            "all_x_h_bonds": bonds,
            "all_basic_sites": basic_sites,
        }
    except Exception as e:
        log.debug(f"[T7-first-principles] {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# Public resolvers
# ──────────────────────────────────────────────────────────────────────────
@register("drug_pka_acidic")
def resolve_drug_pka_acidic(name: str = "", smiles: str = "",
                              researcher_override: float | None = None) -> dict:
    db_misses: list[str] = []

    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided pKa via Excel",
                          reference="Researcher input",
                          live_db_misses=[])

    # Tier 1
    for src_name, fn in [
        ("ChEMBL acd_most_apka", _pka_chembl),
        ("DrugBank (via ChEMBL)", _pka_drugbank_xref),
        ("PubChem classification", _pka_pubchem_classification),
    ]:
        try:
            r = fn(name)
            if r and r.get("acidic") is not None:
                return _resolved(
                    value=float(r["acidic"]), tier=1, source=src_name,
                    method=f"Live DB pKa: {src_name}",
                    reference="ChEMBL/DrugBank curated experimental data",
                    live_db_misses=db_misses)
        except Exception: pass
        db_misses.append(src_name)

    # Tier 7: first-principles Bordwell-Hammett-Born computation
    try:
        r = _pka_t7_groups(smiles)
        if r and r.get("acidic") is not None:
            v = float(r["acidic"])
            label = r.get("acidic_label", "")
            canonical_found = r.get("canonical_acidic_groups_found", [])
            comp_method = r.get("_computational_method_acidic",
                                  "First-principles pKa (Bordwell-Hammett-Born hybrid)")
            return _resolved(
                value=v, tier=7,
                source="cerebro_value_resolver:bordwell_hammett_born",
                method="First-principles pKa via Bordwell-Hammett-Born hybrid"
                        " (NO hardcoded molecule-specific values)",
                reference="Reich HJ (2020) Bordwell pKa Tables; "
                           "Bordwell FG (1988) Acc Chem Res 21:456; "
                           "Hammett LP (1937) JACS 59:96; Born M (1920) Z Phys 1:45",
                live_db_misses=db_misses,
                extra={"acidic_bond_type": label,
                        "canonical_groups_found": canonical_found,
                        "all_x_h_bonds_in_molecule":
                            list(r.get("all_x_h_bonds", {}).keys()),
                        "_computational_method": comp_method})
    except Exception as e:
        log.debug(f"[T7 first-principles] {e}")
    db_misses.append("first_principles_bordwell")

    # No SMILES (or the SMILES failed to parse) — there is no molecular
    # structure to compute a pKa from. Assuming a generic sp3 C-H bond here
    # would invent a bond that was never observed; report honestly instead
    # so callers (resolve_drug_pka_dominant, hh_microspeciation) can use
    # their already-built "no ionizable group" handling rather than being
    # fed a fabricated-looking number like 49.9.
    return _resolved(
        value=None, tier=7,
        source="cerebro_value_resolver:no_structure_available",
        method="No usable SMILES — cannot compute a first-principles pKa "
                "without molecular structure",
        reference="—",
        live_db_misses=db_misses,
        extra={"confidence": "HIGH",
                "note": "No SMILES provided (or it failed to parse) — pKa not computable"})


@register("drug_pka_basic")
def resolve_drug_pka_basic(name: str = "", smiles: str = "",
                             researcher_override: float | None = None) -> dict:
    db_misses: list[str] = []

    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided pKa via Excel",
                          reference="Researcher input",
                          live_db_misses=[])

    for src_name, fn in [
        ("ChEMBL acd_most_bpka", _pka_chembl),
        ("DrugBank (via ChEMBL)", _pka_drugbank_xref),
        ("PubChem classification", _pka_pubchem_classification),
    ]:
        try:
            r = fn(name)
            if r and r.get("basic") is not None:
                return _resolved(
                    value=float(r["basic"]), tier=1, source=src_name,
                    method=f"Live DB pKa: {src_name}",
                    reference="ChEMBL/DrugBank curated experimental data",
                    live_db_misses=db_misses)
        except Exception: pass
        db_misses.append(src_name)

    # Tier 7: first-principles Bordwell-Hammett-Born computation
    try:
        r = _pka_t7_groups(smiles)
        if r and r.get("basic") is not None:
            v = float(r["basic"])
            label = r.get("basic_label", "")
            canonical_found = r.get("canonical_basic_groups_found", [])
            comp_method = r.get("_computational_method_basic",
                                  "First-principles pKa (Bordwell-Hammett-Born hybrid)")
            return _resolved(
                value=v, tier=7,
                source="cerebro_value_resolver:bordwell_hammett_born",
                method="First-principles pKa via Bordwell-Hammett-Born hybrid",
                reference="Reich HJ (2020) Bordwell pKa Tables; "
                           "Bordwell FG (1988) Acc Chem Res 21:456",
                live_db_misses=db_misses,
                extra={"basic_bond_type": label,
                        "canonical_groups_found": canonical_found,
                        "_computational_method": comp_method})
    except Exception as e:
        log.debug(f"[T7 first-principles] {e}")
    db_misses.append("first_principles_bordwell")

    # No SMILES available — same reasoning as resolve_drug_pka_acidic's
    # matching branch: report honestly rather than inventing a proxy value.
    return _resolved(
        value=None, tier=7,
        source="cerebro_value_resolver:no_structure_available",
        method="No usable SMILES — cannot compute a first-principles pKa(BH+) "
                "without molecular structure",
        reference="—",
        live_db_misses=db_misses,
        extra={"confidence": "HIGH",
                "note": "No SMILES provided (or it failed to parse) — pKa(BH+) not computable"})


@register("drug_pka_dominant")
def resolve_drug_pka_dominant(name: str = "", smiles: str = "",
                                researcher_override: float | None = None) -> dict:
    """The pKa closest to physiological pH 7.4 — most relevant for
    membrane partitioning."""
    if researcher_override is not None:
        return _resolved(value=float(researcher_override), tier=0,
                          source="researcher_override",
                          method="User-provided dominant pKa via Excel",
                          reference="Researcher input",
                          live_db_misses=[])
    a = resolve_drug_pka_acidic(name=name, smiles=smiles)
    b = resolve_drug_pka_basic(name=name, smiles=smiles)
    candidates = []
    if a.get("value") is not None: candidates.append((a["value"], "acidic", a))
    if b.get("value") is not None: candidates.append((b["value"], "basic", b))
    if not candidates:
        return _resolved(
            value=None, tier=7,
            source="cerebro_value_resolver:no_ionizable",
            method="Neither acidic nor basic pKa found",
            reference="—",
            live_db_misses=a.get("live_db_misses",[]) + b.get("live_db_misses",[]),
            extra={"confidence": "HIGH",
                    "note": "Drug is not ionizable at any pH"})
    # Pick closest to 7.4
    val, kind, src = min(candidates, key=lambda c: abs(c[0] - 7.4))
    return _resolved(
        value=val, tier=src["tier"],
        source=f"dominant_of_{kind}_pka:{src['source']}",
        method=f"Dominant pKa selected as {kind} (closest to physiological pH 7.4)",
        reference=src["reference"],
        live_db_misses=src.get("live_db_misses",[]),
        extra={"kind": kind})


@register("drug_microspecies")
def resolve_drug_microspecies(name: str = "", smiles: str = "",
                                researcher_pka_acid: float | None = None,
                                researcher_pka_base: float | None = None,
                                pH: float = 7.4) -> dict:
    """Returns Bjerrum 4-microspecies fractions at the given pH."""
    pka_a_rec = resolve_drug_pka_acidic(
        name=name, smiles=smiles, researcher_override=researcher_pka_acid)
    pka_b_rec = resolve_drug_pka_basic(
        name=name, smiles=smiles, researcher_override=researcher_pka_base)
    pka_a = pka_a_rec.get("value")
    pka_b = pka_b_rec.get("value")
    fractions = hh_microspeciation(pka_a, pka_b, pH=pH)

    # Use the worst (highest tier) of the two underlying pKa records as our tier
    src_tier = max(pka_a_rec.get("tier", 7), pka_b_rec.get("tier", 7))
    return _resolved(
        value=fractions, tier=src_tier,
        source="cerebro_value_resolver:hh_microspeciation",
        method=fractions.get("method", "?"),
        reference="Bjerrum N (1923) Z Physik Chem 106:219; "
                   "Pagliara A et al (1997) J Med Chem 40:1972",
        live_db_misses=(pka_a_rec.get("live_db_misses",[])
                          + pka_b_rec.get("live_db_misses",[])),
        extra={"pH": pH,
                "input_pKa_acidic": pka_a, "input_pKa_basic": pka_b,
                "pKa_acidic_source": pka_a_rec.get("source"),
                "pKa_basic_source":  pka_b_rec.get("source")})
