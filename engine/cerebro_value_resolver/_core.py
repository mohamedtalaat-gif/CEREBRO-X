"""
================================================================================
CEREBRO-X | cerebro_value_resolver/_core.py
================================================================================
Core infrastructure for the Universal Value Resolver.

EVERY category resolver in cerebro_value_resolver/categories/*.py imports from
here. This module:
  • Detects which Tier-5 libraries are available
  • Provides the standard ResolvedValue record builder (`_resolved`)
  • Provides shared HTTP fetcher (`_safe_get`)
  • Provides tier definitions and confidence levels
  • Provides a registry of categories so `resolve_value(category, **ctx)`
    can dispatch to the right resolver

Design note: this module never holds any cached drug-specific data; the
caches it does maintain are LRU (live HTTP responses) and are key-scoped
to (DB_name, identifier).
================================================================================
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

log = logging.getLogger("CEREBRO-RESOLVER")

# ──────────────────────────────────────────────────────────────────────────
# Library availability detection
# ──────────────────────────────────────────────────────────────────────────
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from rdkit import Chem
    from rdkit.Chem import (
        AllChem,
        Crippen,
        Descriptors,
        Draw,
        Lipinski,
        rdMolDescriptors,
    )
    _HAS_RDKIT = True
except ImportError:
    _HAS_RDKIT = False

try:
    import mendeleev
    _HAS_MENDELEEV = True
except ImportError:
    _HAS_MENDELEEV = False

try:
    import thermo
    from thermo import Chemical
    _HAS_THERMO = True
except ImportError:
    _HAS_THERMO = False

try:
    import chemicals
    _HAS_CHEMICALS = True
except ImportError:
    _HAS_CHEMICALS = False

try:
    import pint
    _UREG = pint.UnitRegistry()
    _HAS_PINT = True
except ImportError:
    _HAS_PINT = False

try:
    import periodictable
    _HAS_PERIODICTABLE = True
except ImportError:
    _HAS_PERIODICTABLE = False

try:
    from Bio.SeqUtils.ProtParam import ProteinAnalysis
    _HAS_BIOPYTHON = True
except ImportError:
    _HAS_BIOPYTHON = False


_LIB_STATUS = {
    "requests":      _HAS_REQUESTS,
    "rdkit":         _HAS_RDKIT,
    "mendeleev":     _HAS_MENDELEEV,
    "thermo":        _HAS_THERMO,
    "chemicals":     _HAS_CHEMICALS,
    "pint":          _HAS_PINT,
    "periodictable": _HAS_PERIODICTABLE,
    "biopython":     _HAS_BIOPYTHON,
}
log.info(f"[RESOLVER] Library availability: {_LIB_STATUS}")


# ──────────────────────────────────────────────────────────────────────────
# Tier definitions
# ──────────────────────────────────────────────────────────────────────────
TIER_DESCRIPTIONS = {
    0: "Researcher manual override (Excel input)",
    1: "Drug DB live (PubChem / ChEMBL / DrugBank / OpenFDA / RxNorm)",
    2: "Material/excipient DB live (NIST WebBook / FDA IID / ECHA / Sigma-Aldrich)",
    3: "Cheminformatics computation (RDKit / OpenBabel from SMILES)",
    4: "Bioinformatics computation (UniProt / BLAST / AlphaFold from FASTA)",
    5: "First-principles physical chemistry library (thermo / chemicals / mendeleev)",
    6: "Empirical correlation (Wilke-Chang / Hayduk-Laudie / Lennard-Jones combining)",
    7: "Pure-math first-principles computation (Joback / Bjerrum / WKB / TST)",
}

TIER_CONFIDENCE = {
    0: "HIGH (researcher-provided)",
    1: "HIGH",          2: "HIGH",          3: "HIGH",
    4: "HIGH",          5: "MODERATE",      6: "MODERATE",
    7: "COMPUTED_FALLBACK",
}


# ──────────────────────────────────────────────────────────────────────────
# Standard return record
# ──────────────────────────────────────────────────────────────────────────
def _resolved(value: Any, tier: int, source: str, method: str,
                reference: str, live_db_misses: list[str],
                computational_method: str | None = None,
                extra: dict | None = None) -> dict:
    """Build the standard ResolvedValue record returned by every resolver.

    Critical fields:
      - value:                 the resolved value (NEVER None unless explicitly intended)
      - tier:                  0..7 — provenance hierarchy
      - source:                short DB/lib identifier
      - method:                what was done in plain language
      - computational_method:  EXPLICIT step-by-step calculation when tier ≥ 5.
                                Documents the actual mathematical operation
                                so the researcher can verify by hand.
      - reference:             DOI/citation/textbook
      - confidence:            HIGH | MODERATE | LOW | COMPUTED_FALLBACK
      - live_db_misses:        list of DBs queried that didn't have the value
      - disclaimer:            human-readable explanation when tier ≥ 5
    """
    rec = {
        "value":            value,
        "tier":             tier,
        "tier_description": TIER_DESCRIPTIONS.get(tier, "?"),
        "source":           source,
        "method":           method,
        "reference":        reference,
        "confidence":       TIER_CONFIDENCE.get(tier, "LOW"),
        "live_db_misses":   list(live_db_misses),
    }
    # _computational_method is MANDATORY for EVERY tier (per project decision
    # 2026-04-30). At Tier 0 it documents the override; at Tier 1-4 it
    # documents the live DB query path; at Tier 5-7 it documents the math.
    # If the resolver didn't pass an explicit string, auto-build one from
    # source + method so the field is never empty.
    if computational_method:
        rec["_computational_method"] = computational_method
    else:
        # Auto-build per tier so the field is always populated
        if tier == 0:
            rec["_computational_method"] = (
                f"Tier 0 — Researcher-provided override. "
                f"Source: {source}. Action: {method}.")
        elif tier in (1, 2):
            rec["_computational_method"] = (
                f"Tier {tier} — Live primary database query. "
                f"Source: {source}. Query path: {method}. "
                f"Reference: {reference}.")
        elif tier in (3, 4):
            rec["_computational_method"] = (
                f"Tier {tier} — Live cheminformatics/bioinformatics computation. "
                f"Tool: {source}. Computation: {method}. "
                f"Reference: {reference}.")
        elif tier >= 5:
            rec["_computational_method"] = (
                f"Tier {tier} — First-principles or library-correlation computation. "
                f"[Auto-derived from method] {method}. "
                f"Reference: {reference}. "
                f"NOTE: this resolver should provide an explicit computational_method "
                f"argument with step-by-step math for full reproducibility.")
    if tier >= 5:
        misses_str = ", ".join(live_db_misses) if live_db_misses else "all queried"
        rec["disclaimer"] = (
            f"Value NOT FOUND in live databases ({misses_str}). "
            f"Computed via: {method}. "
            f"This is a first-principles or library-correlation calculation "
            f"performed by the resolver itself — the actual mathematical steps "
            f"are recorded in the `_computational_method` field. "
            f"If the researcher locates a published experimental value, "
            f"it should be entered as a researcher_override in the input Excel."
        )
    if extra:
        rec.update(extra)
    return rec


# ──────────────────────────────────────────────────────────────────────────
# HTTP helper — used by all live DB tier-1/2/4 resolvers
# ──────────────────────────────────────────────────────────────────────────
def _safe_get(url: str, timeout: int = 8,
                accept: str = "application/json",
                headers_extra: dict | None = None) -> Any | None:
    if not _HAS_REQUESTS:
        return None
    try:
        h = {"User-Agent": "CEREBRO-X/22.1", "Accept": accept}
        if headers_extra:
            h.update(headers_extra)
        r = requests.get(url, timeout=timeout, headers=h)
        if r.status_code != 200:
            return None
        if "json" in accept.lower():
            return r.json()
        return r.text
    except Exception as e:
        log.debug(f"[GET] {url[:90]}: {e}")
        return None


def _safe_post(url: str, data=None, json=None, timeout: int = 8,
                 accept: str = "application/json") -> Any | None:
    if not _HAS_REQUESTS: return None
    try:
        h = {"User-Agent": "CEREBRO-X/22.1", "Accept": accept}
        r = requests.post(url, data=data, json=json, timeout=timeout, headers=h)
        if r.status_code != 200: return None
        if "json" in accept.lower(): return r.json()
        return r.text
    except Exception as e:
        log.debug(f"[POST] {url[:90]}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────
# Category Registry — populated by categories/*.py at import time
# ──────────────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Callable] = {}


def register(category: str):
    """Decorator: register a resolver function under the given category key."""
    def deco(fn: Callable) -> Callable:
        if category in _REGISTRY:
            log.warning(f"[REGISTRY] Re-registering category {category!r} "
                         f"(was {_REGISTRY[category].__module__})")
        _REGISTRY[category] = fn
        return fn
    return deco


def resolve_value(category: str, **context) -> dict:
    """Public API. Dispatch to the right resolver by category name.

    Categories are registered via the @register("name") decorator in
    categories/*.py modules. If category is unknown, returns a tier-7
    error-record so the caller never gets None.

    Implementation note: callers may pass a "fat" context dict containing
    keys not all resolvers accept (e.g. drug_ + material_ + physics_ keys
    all in one). We filter the context to only the parameter names that
    the target resolver actually declares, to avoid spurious TypeErrors.
    """
    if category not in _REGISTRY:
        return _resolved(
            value=None, tier=7,
            source="cerebro_value_resolver:unknown_category",
            method="No resolver registered for this category",
            reference="—",
            live_db_misses=[],
            extra={"confidence": "FAILED",
                    "warning": f"Unknown category {category!r}. "
                                f"Registered: {sorted(_REGISTRY.keys())}"})
    fn = _REGISTRY[category]
    # Filter kwargs to only those the resolver function accepts
    try:
        import inspect
        sig = inspect.signature(fn)
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD
                              for p in sig.parameters.values())
        if accepts_kwargs:
            filtered = context
        else:
            allowed = set(sig.parameters.keys())
            filtered = {k: v for k, v in context.items() if k in allowed}
    except (ValueError, TypeError):
        filtered = context
    try:
        return fn(**filtered)
    except Exception as e:
        log.exception(f"[RESOLVER] {category}({filtered}): {e}")
        return _resolved(
            value=None, tier=7,
            source="cerebro_value_resolver:exception",
            method=f"Resolver crashed: {type(e).__name__}: {e}",
            reference="—",
            live_db_misses=[],
            extra={"confidence": "FAILED"})


def list_categories() -> list[str]:
    """Public: list all registered categories."""
    return sorted(_REGISTRY.keys())


# ──────────────────────────────────────────────────────────────────────────
# LRU cache for live HTTP requests (keyed on URL+identifier)
# ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=4096)
def cached_safe_get(url: str, timeout: int = 8,
                      accept: str = "application/json") -> str | None:
    """Cached GET. Returns raw text (not parsed JSON) so it's hashable.
    For JSON, callers should json.loads(text)."""
    if not _HAS_REQUESTS: return None
    try:
        r = requests.get(url, timeout=timeout,
                          headers={"User-Agent": "CEREBRO-X/22.1",
                                    "Accept": accept})
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None
