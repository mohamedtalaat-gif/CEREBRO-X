# -*- coding: utf-8 -*-
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
from ._core import resolve_value, list_categories, _resolved
from ._core import _LIB_STATUS

# Auto-import all category modules so @register decorators fire
from .categories import (
    type_detection,
    drug_identifiers,
    drug_descriptors,
    drug_pka,
    drug_admet,
    drug_target_and_mfg,
    pk_clinical,
    bbb_perm,
    material_polymer,
    material_lipid,
    material_surface,
    physics_transport,
    physics_dlvo,
    quantum_atomic,
)

__all__ = ["resolve_value", "list_categories", "_LIB_STATUS"]
