"""
================================================================================
CEREBRO-X | cerebro_value_resolver — Universal Value Resolver Package
================================================================================
Public API:
    from cerebro_value_resolver import resolve_value, list_categories

    r = resolve_value("drug_logp", smiles="CCN(C)C(=O)Oc1cccc(c1)C(C)N(C)C")
    print(r["value"], r["tier"], r["source"], r["confidence"])

The package auto-loads all category modules at import-time so the @register
decorators populate the dispatch table.
================================================================================
"""
from ._core import _LIB_STATUS, _resolved, list_categories, resolve_value

# Auto-import all category modules so @register decorators fire
from .categories import (
    bbb_perm,
    drug_admet,
    drug_descriptors,
    drug_identifiers,
    drug_pka,
    drug_target_and_mfg,
    material_lipid,
    material_polymer,
    material_surface,
    physics_dlvo,
    physics_transport,
    pk_clinical,
    quantum_atomic,
    type_detection,
)

__all__ = ["_LIB_STATUS", "list_categories", "resolve_value"]
