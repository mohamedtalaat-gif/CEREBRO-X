# -*- coding: utf-8 -*-
"""
================================================================================
CEREBRO-X | cerebro_resolved_bundles.py — Milestone 2
================================================================================
Pre-resolved property bundles for the surrogate-function pipeline.

DESIGN (per project owner decision, 2026-04-30):
  Pattern (B) — call the resolver ONCE per (drug, DDS) and cache.
  Surrogate functions then take pre-resolved bundles, not raw IDs.

THREE-LAYER CACHING:
  Layer 1: drug_cache  — keyed on canonical SMILES/FASTA/sequence
                          → all 30+ drug-side properties
  Layer 2: dds_cache   — keyed on (carrier, ligand, formulation_id)
                          → all 20+ DDS-side properties
  Layer 3: combo_cache — keyed on (drug_key, dds_key)
                          → cross-properties (drug-loading, partition, etc.)

PUBLIC API:
  resolve_drug_bundle(name=, smiles=, fasta=, sequence=, molecule_class=,
                        researcher_overrides={}) -> dict
  resolve_dds_bundle(carrier_type=, ligand=, formulation_id=,
                       researcher_overrides={}) -> dict
  resolve_combo_bundle(drug_bundle, dds_bundle) -> dict
  clear_all_caches()
  cache_stats() -> dict

EVERY VALUE in the returned bundle carries ResolvedValue metadata
(value, tier, source, _computational_method, reference, confidence).
================================================================================
"""
from __future__ import annotations
import logging, hashlib, json
from typing import Dict, Any, Optional, List
from cerebro_value_resolver import resolve_value

log = logging.getLogger("CEREBRO-BUNDLES")

# ──────────────────────────────────────────────────────────────────────────
# 3-layer cache (in-memory; cleared per pipeline run if requested)
# ──────────────────────────────────────────────────────────────────────────
_drug_cache: Dict[str, Dict] = {}
_dds_cache:  Dict[str, Dict] = {}
_combo_cache: Dict[str, Dict] = {}

# Stats counters
_cache_stats = {
    "drug_hits": 0,   "drug_misses": 0,
    "dds_hits":  0,   "dds_misses":  0,
    "combo_hits":0,   "combo_misses":0,
}


def _drug_cache_key(name: str, smiles: str, fasta: str, sequence: str) -> str:
    """Canonical cache key from any drug identifier."""
    canonical_parts = [name.strip().lower(), smiles.strip(),
                         fasta.strip(), sequence.strip()]
    h = hashlib.sha1("|".join(canonical_parts).encode()).hexdigest()[:16]
    return f"drug:{h}"


def _dds_cache_key(carrier_type: str, ligand: str,
                     formulation_id: str) -> str:
    parts = [carrier_type.strip().lower(), ligand.strip().lower(),
              formulation_id.strip()]
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    return f"dds:{h}"


def _combo_cache_key(drug_key: str, dds_key: str) -> str:
    return f"combo:{drug_key}+{dds_key}"


# ──────────────────────────────────────────────────────────────────────────
# DRUG BUNDLE — all 30+ drug-side properties resolved once
# ──────────────────────────────────────────────────────────────────────────
DRUG_BUNDLE_CATEGORIES = [
    # Identity
    "drug_smiles", "drug_fasta", "drug_type",
    # Basic descriptors
    "drug_mw", "drug_logp", "drug_tpsa", "drug_hbd", "drug_hba",
    "drug_rotbonds", "drug_aromatic_rings", "drug_formal_charge",
    "drug_stereocenters",
    # Ionization
    "drug_pka_acidic", "drug_pka_basic", "drug_pka_dominant",
    "drug_microspecies",
    # Clinical PK
    "pk_halflife", "pk_clearance", "pk_volume_distribution",
    "pk_protein_binding", "pk_oral_bioavailability",
    # BBB
    "bbb_cns_mpo", "bbb_logBB", "bbb_permeability",
    # ADMET
    "drug_solubility_logS", "drug_caco2_papp",
    "drug_pgp_efflux_ratio", "drug_cyp3a4_inhibition", "drug_herg_ic50",
    "drug_clearance_route",
    # Drug-target binding
    "drug_target_kd", "drug_target_ic50", "drug_target_ki",
    # Quantum
    "quantum_polarizability", "quantum_dipole_moment",
    "quantum_homo_lumo_gap", "quantum_atomic_charges_sum",
]


def resolve_drug_bundle(name: str = "", smiles: str = "",
                          fasta: str = "", sequence: str = "",
                          molecule_class: str = "",
                          researcher_overrides: Optional[Dict] = None,
                          **extra_kwargs) -> Dict:
    """Resolve ALL drug-side properties in a single bundle.

    Args:
        name, smiles, fasta, sequence: identifiers (any combination)
        molecule_class: optional pre-classified type
        researcher_overrides: dict mapping category → user-provided value
            from the Excel "Your Input" column

    Returns:
        bundle dict with `_meta` and a key per category:
            {
              "_meta": {"cache_key", "drug_type", "identifiers"},
              "drug_logp":  ResolvedValue dict,
              "drug_mw":    ResolvedValue dict,
              ...
            }
    """
    researcher_overrides = researcher_overrides or {}
    cache_key = _drug_cache_key(name, smiles, fasta, sequence)

    # Hit check
    if cache_key in _drug_cache:
        _cache_stats["drug_hits"] += 1
        log.debug(f"[bundle] drug cache HIT: {cache_key}")
        return _drug_cache[cache_key]
    _cache_stats["drug_misses"] += 1

    bundle: Dict[str, Any] = {
        "_meta": {
            "cache_key": cache_key,
            "name":      name,
            "identifiers": {
                "smiles":   smiles or None,
                "fasta":    fasta or None,
                "sequence": sequence or None,
            },
            "researcher_overrides": list(researcher_overrides.keys()),
        }
    }

    # FIRST: resolve drug_type (governs subsequent computations)
    drug_type_rec = resolve_value(
        "drug_type",
        name=name, smiles=smiles, fasta=fasta,
        sequence=sequence, molecule_class=molecule_class,
        researcher_override=researcher_overrides.get("drug_type"))
    bundle["drug_type"] = drug_type_rec
    bundle["_meta"]["drug_type"] = drug_type_rec.get("value")

    # SECOND: resolve canonical SMILES (validation + canonicalization)
    smi_rec = resolve_value(
        "drug_smiles",
        name=name, smiles=smiles,
        researcher_override=researcher_overrides.get("drug_smiles"))
    bundle["drug_smiles"] = smi_rec
    canonical_smiles = smi_rec.get("value") or smiles

    # FASTA if biologic
    fasta_rec = resolve_value(
        "drug_fasta",
        name=name, fasta=fasta,
        researcher_override=researcher_overrides.get("drug_fasta"))
    bundle["drug_fasta"] = fasta_rec

    # THIRD: resolve everything else, passing canonical SMILES
    for cat in DRUG_BUNDLE_CATEGORIES:
        if cat in bundle:    # already resolved above
            continue
        try:
            rec = resolve_value(
                cat,
                name=name, smiles=canonical_smiles,
                fasta=fasta, sequence=sequence,
                molecule_class=bundle["_meta"]["drug_type"],
                researcher_override=researcher_overrides.get(cat))
            bundle[cat] = rec
        except Exception as e:
            log.warning(f"[bundle] {cat} failed: {e}")
            bundle[cat] = {"value": None, "tier": 7,
                            "source": "cerebro_resolved_bundles:exception",
                            "method": f"Resolution crashed: {e}",
                            "confidence": "FAILED",
                            "_computational_method":
                                f"Bundle resolver caught {type(e).__name__}: {e}"}

    # Pass MW/LogP into PK + BBB resolvers (they need them for empirical fallbacks)
    mw_val = bundle.get("drug_mw", {}).get("value")
    logp_val = bundle.get("drug_logp", {}).get("value")
    tpsa_val = bundle.get("drug_tpsa", {}).get("value")
    hbd_val = bundle.get("drug_hbd", {}).get("value")
    pka_b_val = bundle.get("drug_pka_basic", {}).get("value")
    arom_val = bundle.get("drug_aromatic_rings", {}).get("value")

    # Re-run PK resolvers with these context values for better empirical fallback
    for cat in ["pk_halflife", "pk_clearance", "pk_volume_distribution",
                  "pk_protein_binding", "bbb_cns_mpo", "bbb_logBB",
                  "bbb_permeability"]:
        # Skip if researcher already overrode
        if cat in researcher_overrides:
            continue
        # Skip if Tier-1 hit (live DB returned a value)
        if bundle.get(cat, {}).get("tier", 7) <= 4:
            continue
        try:
            rec = resolve_value(
                cat,
                name=name, smiles=canonical_smiles,
                mw_Da=mw_val, logp=logp_val, tpsa=tpsa_val, hbd=hbd_val,
                pka_basic=pka_b_val, aromatic_rings=arom_val,
                molecule_class=bundle["_meta"]["drug_type"],
                researcher_override=researcher_overrides.get(cat))
            # Only replace if new resolution is better (lower tier)
            if rec.get("tier", 7) < bundle.get(cat, {}).get("tier", 7):
                bundle[cat] = rec
        except Exception:
            pass

    # Cache + return
    _drug_cache[cache_key] = bundle
    log.info(f"[bundle] drug bundle resolved: {len(DRUG_BUNDLE_CATEGORIES)} "
              f"categories, drug_type={bundle['_meta']['drug_type']}")
    return bundle


# ──────────────────────────────────────────────────────────────────────────
# DDS BUNDLE
# ──────────────────────────────────────────────────────────────────────────
DDS_BUNDLE_CATEGORIES = [
    # Type
    "dds_type",
    # Polymer (for material carriers)
    "material_polymer_tg", "material_polymer_tm", "material_polymer_mw",
    "material_polymer_hydrolysis_ea", "material_polymer_density",
    # Lipid (for liposome/SLN)
    "material_lipid_tm", "material_lipid_packing_parameter",
    "material_lipid_area_per_lipid", "material_lipid_bending_modulus",
    # Surface
    "material_zeta_intrinsic", "material_dielectric",
    "material_refractive_index", "material_surface_tension",
    "material_hamaker_constant",
    # Manufacturing
    "material_pdi", "material_porosity",
]


def resolve_dds_bundle(carrier_type: str = "", ligand: str = "",
                         formulation_id: str = "",
                         formulation_name: str = "",
                         researcher_overrides: Optional[Dict] = None,
                         **extra_kwargs) -> Dict:
    """Resolve all DDS-side properties for a given carrier."""
    researcher_overrides = researcher_overrides or {}
    cache_key = _dds_cache_key(carrier_type, ligand, formulation_id)

    if cache_key in _dds_cache:
        _cache_stats["dds_hits"] += 1
        log.debug(f"[bundle] dds cache HIT: {cache_key}")
        return _dds_cache[cache_key]
    _cache_stats["dds_misses"] += 1

    bundle: Dict[str, Any] = {
        "_meta": {
            "cache_key": cache_key,
            "carrier_type": carrier_type,
            "ligand":       ligand,
            "formulation_id": formulation_id,
            "formulation_name": formulation_name,
            "researcher_overrides": list(researcher_overrides.keys()),
        }
    }

    # FIRST: resolve dds_type
    dds_type_rec = resolve_value(
        "dds_type",
        carrier=carrier_type, carrier_type=carrier_type,
        formulation_name=formulation_name,
        researcher_override=researcher_overrides.get("dds_type"))
    bundle["dds_type"] = dds_type_rec
    bundle["_meta"]["dds_type"] = dds_type_rec.get("value")

    # Resolve all material categories
    for cat in DDS_BUNDLE_CATEGORIES:
        if cat == "dds_type": continue
        try:
            rec = resolve_value(
                cat, carrier=carrier_type,
                researcher_override=researcher_overrides.get(cat))
            bundle[cat] = rec
        except Exception as e:
            log.warning(f"[bundle] {cat} failed: {e}")
            bundle[cat] = {"value": None, "tier": 7,
                            "source": "cerebro_resolved_bundles:exception",
                            "_computational_method": f"Crashed: {e}"}

    _dds_cache[cache_key] = bundle
    log.info(f"[bundle] DDS bundle resolved: {len(DDS_BUNDLE_CATEGORIES)} "
              f"categories, dds_type={bundle['_meta']['dds_type']}")
    return bundle


# ──────────────────────────────────────────────────────────────────────────
# COMBO BUNDLE — drug × DDS interaction properties
# ──────────────────────────────────────────────────────────────────────────
COMBO_BUNDLE_CATEGORIES = [
    "drug_loading_capacity_pct",
]


def resolve_combo_bundle(drug_bundle: Dict, dds_bundle: Dict,
                            researcher_overrides: Optional[Dict] = None) -> Dict:
    """Resolve drug-DDS interaction properties.

    These are properties that depend on BOTH the drug and the DDS:
    drug-loading capacity, partition coefficient, encapsulation
    efficiency proxy, etc.
    """
    researcher_overrides = researcher_overrides or {}
    drug_key = drug_bundle.get("_meta", {}).get("cache_key", "?")
    dds_key  = dds_bundle.get("_meta", {}).get("cache_key", "?")
    cache_key = _combo_cache_key(drug_key, dds_key)

    if cache_key in _combo_cache:
        _cache_stats["combo_hits"] += 1
        return _combo_cache[cache_key]
    _cache_stats["combo_misses"] += 1

    bundle: Dict[str, Any] = {
        "_meta": {
            "cache_key": cache_key,
            "drug_key":  drug_key,
            "dds_key":   dds_key,
            "drug_type": drug_bundle.get("_meta",{}).get("drug_type"),
            "dds_type":  dds_bundle.get("_meta",{}).get("dds_type"),
        }
    }

    # Pull values needed for combo computation
    logp = drug_bundle.get("drug_logp",{}).get("value")
    mw   = drug_bundle.get("drug_mw",{}).get("value")
    carrier = dds_bundle.get("_meta",{}).get("carrier_type","")

    for cat in COMBO_BUNDLE_CATEGORIES:
        try:
            rec = resolve_value(
                cat, carrier=carrier, logp=logp, mw_Da=mw,
                researcher_override=researcher_overrides.get(cat))
            bundle[cat] = rec
        except Exception as e:
            log.warning(f"[bundle] {cat} failed: {e}")
            bundle[cat] = {"value": None, "tier": 7,
                            "_computational_method": f"Crashed: {e}"}

    _combo_cache[cache_key] = bundle
    return bundle


# ──────────────────────────────────────────────────────────────────────────
# Cache management
# ──────────────────────────────────────────────────────────────────────────
def clear_all_caches() -> None:
    _drug_cache.clear()
    _dds_cache.clear()
    _combo_cache.clear()
    for k in _cache_stats: _cache_stats[k] = 0
    log.info("[bundle] all caches cleared")


def cache_stats() -> Dict[str, Any]:
    return {
        **_cache_stats,
        "drug_cache_size": len(_drug_cache),
        "dds_cache_size":  len(_dds_cache),
        "combo_cache_size": len(_combo_cache),
    }


# ──────────────────────────────────────────────────────────────────────────
# Convenience: extract scalar values from bundle (for surrogate functions)
# ──────────────────────────────────────────────────────────────────────────
def b_value(bundle: Dict, category: str, default: Any = None) -> Any:
    """Extract just the resolved value from a bundle category."""
    return bundle.get(category, {}).get("value", default)


def b_tier(bundle: Dict, category: str) -> int:
    """Extract the tier of a bundle category (for confidence checks)."""
    return bundle.get(category, {}).get("tier", 7)


def b_method(bundle: Dict, category: str) -> str:
    """Extract the computational method string."""
    return bundle.get(category, {}).get("_computational_method", "")
