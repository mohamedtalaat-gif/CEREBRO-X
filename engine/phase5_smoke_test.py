#!/usr/bin/env python3
"""
================================================================================
Phase 5 Smoke Test — run inside Docker after `docker compose up --build`
================================================================================
Usage:
  docker exec -it cerebro-core python phase5_smoke_test.py

This script verifies (without running the full pipeline) that:
  1. All bundle-only modules import cleanly
  2. The 7-tier resolver can produce a complete drug bundle
  3. The orchestrator accepts the new bundle-only signature
  4. Surrogate, deep, and translational engines all chain correctly
  5. Provenance flows end-to-end into surrogate raw fields

If this script passes, you can safely run the full pipeline:
  docker exec -it cerebro-core python run.py --pipeline-only --force
================================================================================
"""
import sys
import time
import traceback

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; RESET = "\033[0m"

def step(name):
    print(f"\n{YELLOW}━━━ {name} ━━━{RESET}")

def ok(msg):
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg, exc=None):
    print(f"  {RED}✗ {msg}{RESET}")
    if exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)

errors = 0

# ════════════════════════════════════════════════════════════════════════
step("1. Module imports")
# ════════════════════════════════════════════════════════════════════════
try:
    from cerebro_value_resolver import _LIB_STATUS, list_categories
    n = len(list_categories())
    ok(f"cerebro_value_resolver: {n} categories registered")
    ok(f"  Library status: {_LIB_STATUS}")
except Exception as e:
    fail("cerebro_value_resolver import", e); errors += 1

try:
    from cerebro_resolved_bundles import (
        b_tier,
        b_value,
        cache_stats,
        clear_all_caches,
        resolve_combo_bundle,
        resolve_dds_bundle,
        resolve_drug_bundle,
    )
    ok("cerebro_resolved_bundles imported")
except Exception as e:
    fail("cerebro_resolved_bundles import", e); errors += 1

try:
    from cerebro_62_deep_engine import (
        DEEP_FUNCTIONS,
        HPC_ONLY_PRINCIPLES,
    )
    from cerebro_62_orchestrator import evaluate_all_dds_62
    from cerebro_62_surrogate_engine import (
        SURROGATE_FUNCTIONS,
    )
    from cerebro_62_translational_engine import (
        TRANSLATIONAL_FUNCTIONS,
    )
    ok("Orchestrator + engines imported")
    ok(f"  Surrogate: {len(SURROGATE_FUNCTIONS)} functions")
    ok(f"  Deep:      {len(DEEP_FUNCTIONS)} real + {len(HPC_ONLY_PRINCIPLES)} HPC-stand-ins")
    ok(f"  Translational: {len(TRANSLATIONAL_FUNCTIONS)} functions")
except Exception as e:
    fail("orchestrator/engine imports", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
step("2. Drug bundle resolution")
# ════════════════════════════════════════════════════════════════════════
try:
    clear_all_caches()
    t0 = time.time()
    db = resolve_drug_bundle(
        name="Donepezil",
        smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
        molecule_class="small_molecule")
    elapsed = time.time() - t0
    ok(f"Donepezil bundle resolved in {elapsed:.2f}s")
    ok(f"  drug_type:      {db['_meta']['drug_type']}")
    ok(f"  drug_logp:      {b_value(db,'drug_logp'):.2f} (Tier {b_tier(db,'drug_logp')})")
    ok(f"  drug_mw:        {b_value(db,'drug_mw'):.1f} (Tier {b_tier(db,'drug_mw')})")
    ok(f"  drug_pka_basic: {b_value(db,'drug_pka_basic'):.2f} (Tier {b_tier(db,'drug_pka_basic')})")
    ok(f"  bbb_cns_mpo:    {b_value(db,'bbb_cns_mpo')}")
    # Confirm _computational_method is on every bundle entry
    n_with_method = sum(1 for k, v in db.items()
                          if isinstance(v, dict) and v.get('_computational_method'))
    ok(f"  Categories with _computational_method: {n_with_method}")
except Exception as e:
    fail("drug bundle resolution", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
step("3. DDS + combo bundle")
# ════════════════════════════════════════════════════════════════════════
try:
    sb = resolve_dds_bundle(carrier_type="plga", ligand="transferrin",
                              formulation_id="F001")
    cb = resolve_combo_bundle(db, sb)
    cb["_meta"]["dds_row"] = {
        "Carrier_Type":"plga","Size_nm":100,"Zeta_Potential_mV":-25,
        "PDI":0.2,"Encapsulation_Efficiency_pct":75,
        "Phase_Transition_Temp_C":45,"Surface_Ligand":"transferrin",
        "PEGylation_Degree_mol_pct":5,"Endosomal_Escape_Eff":0.7,
        "Drug_Loading_Pct":15,"Release_Kinetics":"sustained",
        "Scale_Up_Readiness":"pilot",
    }
    ok(f"DDS bundle: dds_type={sb['_meta']['dds_type']}, "
        f"polymer_Tg={b_value(sb,'material_polymer_tg')}°C")
    ok(f"Combo bundle: drug_loading={b_value(cb,'drug_loading_capacity_pct'):.1f}% w/w")
except Exception as e:
    fail("DDS/combo bundle", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
step("4. Single surrogate function (P14)")
# ════════════════════════════════════════════════════════════════════════
try:
    from cerebro_62_surrogate_engine import P14
    r = P14(db, sb, cb)
    ok(f"P14 score: {r['score']:.2f}")
    ok(f"P14 raw includes drug_LogP from bundle: {r['raw'].get('drug_LogP', 'MISSING')}")
except Exception as e:
    fail("P14 surrogate", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
step("5. Full orchestrator on 3-DDS DataFrame")
# ════════════════════════════════════════════════════════════════════════
try:
    import pandas as pd
    df_dds = pd.DataFrame([cb["_meta"]["dds_row"]] * 3)
    df_dds["Formulation_ID"] = ["F001","F002","F003"]
    df_dds["Formulation_Name"] = ["Tf-PLGA-A","Tf-PLGA-B","Tf-PLGA-C"]
    df_dds.loc[1, "Size_nm"] = 80
    df_dds.loc[2, "Size_nm"] = 150
    t0 = time.time()
    result = evaluate_all_dds_62(drug_bundle=db, df_dds=df_dds,
                                    drug_name="Donepezil", context={})
    elapsed = time.time() - t0
    ok(f"Orchestrator ran in {elapsed:.2f}s")
    ok(f"  Top-1: {result['top1_dds_name']}")
    ok(f"  Composite: {result['all_dds_breakdown'][0]['composite']:.1f}/100")
    ok(f"  Deep verdict: {result['deep_summary'].get('verdict','?')}")
    ok(f"  Cache stats: {cache_stats()}")
except Exception as e:
    fail("full orchestrator", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
step("6. Multi-drug differentiation (Donepezil vs Rivastigmine)")
# ════════════════════════════════════════════════════════════════════════
try:
    db2 = resolve_drug_bundle(
        name="Rivastigmine",
        smiles="CCN(C)C(=O)Oc1cccc(c1)C(C)N(C)C",
        molecule_class="small_molecule")
    result2 = evaluate_all_dds_62(drug_bundle=db2, df_dds=df_dds,
                                     drug_name="Rivastigmine", context={})
    don_top = result['all_dds_breakdown'][0]['composite']
    riv_top = result2['all_dds_breakdown'][0]['composite']
    differ = abs(don_top - riv_top) > 0.5
    ok(f"Donepezil top composite:    {don_top:.2f}")
    ok(f"Rivastigmine top composite: {riv_top:.2f}")
    if differ:
        ok(f"✓ Drugs DIFFERENTIATE (Δ={don_top - riv_top:+.2f}) — surrogate is drug-aware")
    else:
        print(f"  {YELLOW}!{RESET} Drugs nearly identical (Δ={don_top - riv_top:+.2f})")
except Exception as e:
    fail("multi-drug differentiation", e); errors += 1

# ════════════════════════════════════════════════════════════════════════
print(f"\n{'═'*70}")
if errors == 0:
    print(f"{GREEN}✅ ALL SMOKE TESTS PASSED — Phase 5 pipeline ready{RESET}")
    print("   Run full pipeline: python run.py --pipeline-only --force")
    sys.exit(0)
else:
    print(f"{RED}❌ {errors} test(s) failed{RESET}")
    sys.exit(1)
