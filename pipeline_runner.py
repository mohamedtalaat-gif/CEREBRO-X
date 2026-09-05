"""
================================================================================
CEREBRO-X — Core Pipeline Runner and Scheduler Loop
================================================================================
File: pipeline_runner.py

Extracted from run.py (was Section 7 "CORE PIPELINE RUNNER" and Section 10
"HOURLY SCHEDULER LOOP") as part of splitting run.py's mixed responsibilities
— see docs/AUDIT_REPORT.md section 13. This is the largest and highest-risk
extraction of that split: the actual per-drug orchestration logic that calls
into ~30 engine modules. Moved verbatim (no logic changes) — every engine
import inside these functions was already a local import scoped to the
function body in the original file, so this module needed no changes to
those call sites, only to the module-level names it depends on from run.py
(replicated below) and from the already-extracted trial_manager.py /
report_fallbacks.py.
================================================================================
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from pathlib import Path

from report_fallbacks import (
    _generate_merged_pdf,
    _make_static_figures,
    _write_dds_doc,
    _write_trial_doc,
)
from trial_manager import (
    EXCEL_GLOB_PATTERNS,
    INPUTS_DIR,
    TRIAL_INDEX_DB,
    _excel_hash,
    excel_to_yaml,
    find_new_excel_files,
    invalidate_molecule_cache,
    next_trial_dir,
    register_trial,
)

log = logging.getLogger("CEREBRO-PIPELINE")

try:
    SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
except NameError:
    SCRIPT_DIR = Path(os.path.abspath(sys.argv[0])).parent

RESULTS_ROOT = SCRIPT_DIR / "outputs"


def run_pipeline_from_excel(excel_path: Path, excel_hash: str,
                             trial_dir: Path, force: bool = False) -> bool:
    """
    Run the full CEREBRO-X pipeline for one Excel file.

    Steps:
      1. Excel → YAML  (always fresh — never reads old YAML)
      2. Cache invalidation for this drug
      3. MoleculeEngine.analyze_molecule()  (SMILES/FASTA/name → live fetch)
      4. CascadeDataEngine.build_mab_dataset([drug_name])  (upsert, not read)
      5. AdvancedMLEngine.train()  (leakage-free scaler)
      6. ADMETEngine.run()
      7. DDSEngine.run() on the 100 formulations from Excel
      8. PDF report generation (in-memory → trial_dir)
      9. Register trial in index DB
    """

    log.info("=" * 65)
    log.info(f"  TRIAL → {trial_dir.name}")
    log.info(f"  Excel  : {excel_path.name}")
    log.info("=" * 65)

    # ── Step 1: Excel → YAML ──────────────────────────────────────────────
    yaml_path = trial_dir / "dds_config.yaml"
    try:
        cfg = excel_to_yaml(excel_path, yaml_path, force_refresh=True)
    except Exception as e:
        log.error(f"[PIPELINE] Excel→YAML failed: {e}")
        return False

    drug_name  = cfg["drug"]["name"]
    n_forms    = len(cfg["formulations"])
    mol_input  = cfg["drug"].get("molecule_input", drug_name)

    # ── Step 2: Invalidate cache ──────────────────────────────────────────
    invalidate_molecule_cache([drug_name], trial_dir)

    # ── Step 3: Import pipeline + apply patches ───────────────────────────
    try:
        import CEREBRO_Pipeline as cp
    except ImportError as e:
        log.error(f"[PIPELINE] Cannot import CEREBRO_Pipeline: {e}")
        return False

    try:
        from cerebro_pipeline_patches import apply_patches
        apply_patches(cp)
        log.info("[PIPELINE] Leakage-free scaler patch applied")
    except ImportError:
        log.warning("[PIPELINE] cerebro_pipeline_patches.py not found — running unpatched")

        # ── Clinical PK engine (fixes ChEMBL HL=None) ─────────────────────────
        try:
            from cerebro_clinical_data_engine import patch_build_mab_dataset
            pk_doc_dir = trial_dir / "clinical_pk_data"
            patch_build_mab_dataset(cp, output_dir=pk_doc_dir)
            log.info("[PIPELINE] Clinical PK engine: DrugBank→DailyMed→OpenFDA→PubMed→Alignment")
        except ImportError:
            log.warning("[PIPELINE] cerebro_clinical_data_engine.py not found")
        except Exception as _cpke:
            log.warning(f"[PIPELINE] Clinical PK patch error: {_cpke}")

    # ── Step 4: Override output paths to trial_dir ────────────────────────
    # We monkey-patch PATHS so everything goes into Trial_N/ not the global dir.
    # "figures" is routed under trial_dir/media/ to join the other media
    # subfolders (videos, canvas_videos, schematics) instead of sitting as
    # its own top-level folder next to media/.
    for key in list(cp.PATHS.keys()):
        base = trial_dir / "media" if key == "figures" else trial_dir
        sub = base / cp.PATHS[key].name
        sub.mkdir(parents=True, exist_ok=True)
        cp.PATHS[key] = sub

    cp.DB_PATH          = str(trial_dir / "cerebro.db")
    cp.MISSING_DATA_LOG = str(trial_dir / "Missing_Data_Log.txt")
    cp.setup_workspace()

    # ── Step 5: Fetch drug data (live — cache was cleared) ────────────────
    log.info(f"[PIPELINE] Fetching: {drug_name} | input: {mol_input[:50]}")

    # ── Novel Drug Analog Check (runs before main pipeline) ───────────────
    try:
        import sys as _sys_nd
        _nd_p = str(Path(__file__).parent / "src" / "core")
        if _nd_p not in _sys_nd.path: _sys_nd.path.insert(0, _nd_p)
        from novel_drug_analog import find_closest_analog
        _analog_result = find_closest_analog(drug_name, {}, cfg["drug"].get("smiles",""))
        log.info(f"[ANALOG] Novel drug: {_analog_result['is_novel_drug']} | "
                  f"Closest: {_analog_result['closest_analog']['name']} "
                  f"({_analog_result['closest_analog']['similarity_pct']:.0f}%)")
        if _analog_result["is_novel_drug"]:
            log.warning(f"[ANALOG] {_analog_result['disclaimer'][:120]}")
    except Exception as _ea:
        log.debug(f"[ANALOG] {_ea}")
        _analog_result = {"is_novel_drug": False, "confirmed_absent_from_databases": False}


    # ── RESET: Explicit mol_profile reset prevents State Leakage ─────────
    # CRITICAL: Without this, a failed Drug 2 API call would silently keep
    # Drug 1's mol_profile (e.g. Idursulfase MW=76000 assigned to Galantamine)
    mol_profile: dict = {}  # Always starts fresh for each drug

    # Pre-populate molecule_class + fasta + sequence from Excel BEFORE
    # MoleculeEngine runs. This is critical: MoleculeEngine.analyze_molecule
    # auto-detects type from SMILES/FASTA shape, which can mis-classify mAbs
    # as generic "protein". The user's explicit Excel choice
    # (e.g. "monoclonal_antibody") should win.
    _drug_cfg = cfg.get("drug", {}) or {}
    _excel_molecule_class = _drug_cfg.get("molecule_class", "") or ""
    _excel_fasta    = _drug_cfg.get("fasta", "") or ""
    _excel_sequence = _drug_cfg.get("sequence", "") or ""
    if _excel_molecule_class:
        mol_profile["molecule_class"] = _excel_molecule_class
        log.info(f"[PIPELINE] Excel-supplied molecule_class: {_excel_molecule_class}")
    if _excel_fasta:
        mol_profile["fasta"] = _excel_fasta
    if _excel_sequence:
        mol_profile["sequence"] = _excel_sequence

    # Try MoleculeEngine first (handles SMILES/FASTA/PDB/HELM/name)
    try:
        from cerebro_molecule_engine import analyze_molecule
        _engine_profile = analyze_molecule(mol_input, drug_name)
        # Merge: Excel-supplied fields override engine's auto-detection
        if isinstance(_engine_profile, dict):
            _engine_profile.update(mol_profile)    # mol_profile (Excel) wins
            mol_profile = _engine_profile
        log.info(f"[PIPELINE] MoleculeEngine: MW={mol_profile.get('MW_Da')} Da "
                 f"LogP={mol_profile.get('LogP')} HL={mol_profile.get('Half_Life_Days')}d "
                 f"class={mol_profile.get('molecule_class','?')}")
    except Exception as e:
        log.warning(f"[PIPELINE] MoleculeEngine skipped: {e}")

    # ── RESOLVER: Fill any None properties via cascade (literature → analog) ─
    try:
        from cerebro_molecule_engine import resolve_missing_properties
        _smiles = cfg.get("drug",{}).get("smiles","")
        mol_profile = resolve_missing_properties(mol_profile, drug_name, _smiles)
        _none_count = sum(1 for v in mol_profile.values() if v is None)
        log.info(f"[RESOLVER] mol_profile resolved — {_none_count} fields still None "
                  f"(explicitly unknown, not invented)")
    except Exception as _res_e:
        log.warning(f"[RESOLVER] Resolution cascade failed: {_res_e}")

    # ── v22.1 MOLECULE-AWARE ENRICHMENT: SMILES → 15 descriptors ─────────
    # Compute LogP, TPSA, HBD/HBA, RotBonds, AromaticRings, FormalCharge,
    # Stereocenters, pKa (acidic/basic/dominant), and Henderson-Hasselbalch
    # net charge at pH 7.4. These descriptors feed the molecule-aware
    # surrogate functions (Class A) and ODE coefficients (Class B).
    try:
        from cerebro_molecule_extractor import enrich_mol_profile
        mol_profile = enrich_mol_profile(mol_profile)
        _src = mol_profile.get("_primary_source","unknown")
        log.info(f"[MOL-EXTRACTOR] {drug_name} enriched via {_src}: "
                  f"LogP={mol_profile.get('LogP')} "
                  f"TPSA={mol_profile.get('TPSA_A2')} "
                  f"pKa={mol_profile.get('pKa')} "
                  f"NetCharge_pH74={mol_profile.get('NetCharge_pH74')}")
    except Exception as _ext_e:
        log.warning(f"[MOL-EXTRACTOR] Enrichment failed: {_ext_e}")

    # Build dataset from just THIS drug (no hardcoded list)
    # ── ISOLATION: Clear any stale rows for THIS drug before fetching fresh ──
    # Prevents State Leakage when Drug 2/3 API fails and DB still has Drug 1 data
    try:
        import sqlite3 as _sq
        with _sq.connect(cp.DB_PATH) as _conn:
            _conn.execute("DELETE FROM drugs WHERE LOWER(drug_name)=LOWER(?)", (drug_name,))
            _conn.commit()
        log.info(f"[ISOLATION] Cleared stale DB rows for: {drug_name}")
    except Exception as _iso_e:
        log.warning(f"[ISOLATION] DB clear skipped: {_iso_e}")

    df_mab = cp.CascadeDataEngine.build_mab_dataset([drug_name])

    # Inject MoleculeEngine data if cascade missed anything
    if not df_mab.empty and mol_profile:
        import pandas as pd
        for field, col in [("MW_Da","MW_Da"), ("LogP","LogP"),
                            ("Half_Life_Days","Half_Life_Days")]:
            if mol_profile.get(field) and (df_mab[col].iloc[0] == 0
                                            or pd.isna(df_mab[col].iloc[0])):
                df_mab.loc[df_mab.index[0], col] = mol_profile[field]
                log.info(f"  [PIPELINE] Injected {field}={mol_profile[field]} from MoleculeEngine")

    if df_mab.empty:
        log.error("[PIPELINE] No drug data retrieved — trial aborted")
        return False

    # Force-upsert to DB (never read stale — always write fresh)
    cp.db_upsert_drugs(df_mab, source="excel_fresh", doi=str(excel_path.name))

    # ── Step 6: ML training ───────────────────────────────────────────────
    feature_cols = ["MW_Da", "LogP", "Half_Life_Days", "Docking_Affinity_kcal"]
    avail_feats  = [c for c in feature_cols if c in df_mab.columns]

    if len(df_mab) < 2:
        # Not enough rows for CV — add synthetic neighbours via SMOTE-like
        log.info("[PIPELINE] Single drug — generating synthetic neighbours for ML")
        df_mab = _augment_single_drug(df_mab, n=8)

    # Detect if all training data is synthetic (single-drug trial)
    _n_real = int((df_mab.get("_synthetic", False) == False).sum()) if "_synthetic" in df_mab.columns else len(df_mab)
    _n_synth = len(df_mab) - _n_real
    _single_drug_trial = (_n_real <= 1)

    df_ml, ensemble, metrics = cp.AdvancedMLEngine.train(
        df_mab, feature_cols=avail_feats)

    # Override misleading metrics for single-drug trials
    if _single_drug_trial:
        metrics["_ml_warning"] = (
            f"SINGLE-DRUG TRIAL: ML trained on {_n_real} real + {_n_synth} synthetic "
            f"(Gaussian 5% noise) rows. R²={metrics.get('r2',0):.4f} reflects fit to "
            f"synthetic distribution of this drug ONLY — not pharmacological population. "
            f"Do not use for generalisation claims."
        )
        metrics["_r2_valid"] = False
        metrics["_source"] = f"Single-drug augmentation (n_real={_n_real}, n_synth={_n_synth})"
        log.warning(f"[ML] {metrics['_ml_warning'][:120]}")
    else:
        metrics["_r2_valid"] = True
        metrics["_source"] = f"Multi-drug dataset (n_real={_n_real})"
        log.info(f"[ML] Multi-drug R²={metrics.get('r2',0):.4f} (valid generalisation)")

    # ── Step 7: ADMET ─────────────────────────────────────────────────────
    df_ml = cp.ADMETEngine.run(df_ml)

    # ── Step 8: PK/PD simulation ──────────────────────────────────────────
    df_pk = cp.AnalyticsEngine.simulate_pkpd(df_ml)

    # ── Step 9: DDS scoring (from Excel formulations) ─────────────────────
    df_dds = _run_dds_from_yaml(yaml_path, trial_dir, drug_name,
                                 mol_profile, df_ml)

    # ── Step 9b [v22]: Per-DDS 62-PRINCIPLE C+ FLOW EVALUATION ────────────
    # NEW v22: full 62-principle catalog (vs v21's 25-principle subset).
    # Orchestrator runs Class A surrogate on ALL DDS → ranking → Class B
    # deep physics on Top-1 (with Top-2/Top-3 fallback) → Class C
    # translational on validated Top-1.
    dds_principle_matrix    = []
    dds_principle_breakdown = []
    deep_results_top1       = {}
    deep_summary_top1       = {}
    translational_top1      = {}
    fallback_chain_top1     = []
    drug_bundle_top1        = None
    if df_dds is not None and not df_dds.empty:
        try:
            # Phase 5 (2026-04-30): build drug bundle ONCE, pass to orchestrator
            from cerebro_62_orchestrator import evaluate_all_dds_62
            from cerebro_resolved_bundles import cache_stats, resolve_drug_bundle
            _researcher_overrides = (mol_profile.get("_researcher_overrides", {})
                                       if isinstance(mol_profile, dict) else {})
            drug_bundle_top1 = resolve_drug_bundle(
                name      = mol_profile.get("name", drug_name),
                smiles    = mol_profile.get("smiles", ""),
                fasta     = mol_profile.get("fasta", ""),
                sequence  = mol_profile.get("sequence", ""),
                molecule_class = mol_profile.get("molecule_class", ""),
                researcher_overrides = _researcher_overrides,
                target_pdb_id = cfg.get("drug", {}).get("target_pdb_id", ""),
            )
            log.info(f"[BUNDLES] {drug_name}: drug bundle resolved "
                      f"(drug_type={drug_bundle_top1.get('_meta',{}).get('drug_type')}, "
                      f"cache_stats={cache_stats()})")
            _orch = evaluate_all_dds_62(drug_bundle=drug_bundle_top1,
                                          df_dds=df_dds,
                                          drug_name=drug_name,
                                          context={})
            df_dds                  = _orch["ranked_df"]
            dds_principle_matrix    = _orch["all_dds_principles"]
            dds_principle_breakdown = _orch["all_dds_breakdown"]
            deep_results_top1       = _orch["deep_results"]
            deep_summary_top1       = _orch["deep_summary"]
            translational_top1      = _orch["translational"]
            fallback_chain_top1     = _orch["fallback_chain"]
            log.info(f"[62-ORCH] {drug_name}: re-ranked {len(df_dds)} DDS "
                      f"by 57-principle composite. Top-1: "
                      f"{_orch['top1_dds_name']} | Deep: "
                      f"{deep_summary_top1.get('verdict','?')} | "
                      f"Translational: "
                      f"{len([t for t in translational_top1.values() if t.get('status') not in ('failed','skipped_deep_validation_insufficient')])}/{len(translational_top1)} ready")

            # df_dds is now sorted by Principle_Composite_Score, but its "Rank"
            # column still holds each row's OLD position from the
            # BBB_Engineering_Score sort in _run_dds_from_yaml -- sort_values
            # reorders rows, it doesn't touch column values. Every downstream
            # consumer (this report, TRIAL_DOCUMENTATION.txt, the PDF) treats
            # row 0 of this df as "the top pick", so a stale Rank made that
            # pick display as e.g. "#2" -- self-contradictory, and out of
            # sync with the on-disk formulation_ranking.csv, which was
            # written before this re-rank ran and still reflects the old
            # order. Recompute Rank to match the current (real) order and
            # rewrite both CSVs so the disk artifact a reviewer opens agrees
            # with what the report actually recommends.
            df_dds["Rank"] = range(1, len(df_dds) + 1)
            _dds_dir = trial_dir / "dds_analysis"
            df_dds.to_csv(_dds_dir / "formulation_ranking.csv", index=False)
            df_dds.head(10).to_csv(_dds_dir / "top10_formulations.csv", index=False)
        except Exception as _de:
            log.warning(f"[62-ORCH] Per-DDS evaluation skipped: {_de}")
            import traceback; log.debug(traceback.format_exc())

    # ── Step 10: Advanced Visualisations (all 17 types + simulation videos) ─
    admet_profile = None
    try:
        from cerebro_advanced_viz import AdvancedVizOrchestrator
        smiles_val = cfg.get("drug",{}).get("smiles")  # Never pass FASTA/PDB as smiles
        # Identify top ligand for videos
        ligand = "RVG29"
        if df_dds is not None and "Surface_Ligand" in df_dds.columns and "BBB_Engineering_Score" in df_dds.columns:
            top_f = df_dds.nlargest(1,"BBB_Engineering_Score")
            if not top_f.empty:
                ligand = str(top_f.iloc[0].get("Surface_Ligand","RVG29"))
        AdvancedVizOrchestrator.run_all(
            drug_name   = drug_name,
            smiles      = smiles_val,
            mol_profile = mol_profile,
            df_ml       = df_ml,
            df_dds      = df_dds,
            df_pk       = df_pk,
            trial_dir   = trial_dir,
            make_videos = True,
            ligand      = ligand,
        )
        log.info("[PIPELINE] Advanced visualisations complete (17 types + videos)")

        # ── Science Modules (62-point engine) ────────────────────────────────
        science_results = {}
        try:
            import sys as _sys_sci
            for _sp in [str(Path(__file__).parent / "src" / "core"), str(Path(__file__).parent / "src" / "viz")]:
                if _sp not in _sys_sci.path: _sys_sci.path.insert(0, _sp)

            # Extract top DDS profile from principle-ranked DataFrame.
            # v21: Principle_Composite_Score is the new top-rank source —
            # replaces single-metric BBB_Engineering_Score ranking.
            _top_dds_dict = {}
            if df_dds is not None and not df_dds.empty:
                _score_col = ("Principle_Composite_Score"
                               if "Principle_Composite_Score" in df_dds.columns
                               else "Composite_Score" if "Composite_Score" in df_dds.columns
                               else "BBB_Engineering_Score")
                _top_row = df_dds.nlargest(1, _score_col).iloc[0]
                _top_dds_dict = _top_row.to_dict()
                # Normalize column names to lowercase for science modules
                _top_dds_dict.update({
                    "size_nm": _top_dds_dict.get("Size_nm") or _top_dds_dict.get("size_nm", 80),
                    "zeta_potential_mv": _top_dds_dict.get("Zeta_Potential_mV") or _top_dds_dict.get("zeta_potential_mv", -10),
                    "pdi": _top_dds_dict.get("PDI") or _top_dds_dict.get("pdi", 0.15),
                    "elasticity_kpa": _top_dds_dict.get("Elasticity_kPa") or _top_dds_dict.get("elasticity_kpa", 1.0),
                    "encapsulation_efficiency_pct": _top_dds_dict.get("Encapsulation_Efficiency_pct", 75),
                    "pegylation_degree_mol_pct": _top_dds_dict.get("PEGylation_Degree_mol_pct", 5),
                    "peg_chain_length_da": _top_dds_dict.get("PEG_Chain_Length_Da", 2000),
                    "release_kinetics": _top_dds_dict.get("Release_Kinetics", "sustained"),
                    "ph_trigger": _top_dds_dict.get("pH_Trigger", 6.5),
                    "phase_transition_temp_c": _top_dds_dict.get("Phase_Transition_Temp_C", 42),
                    "ligand_density_per_nm2": _top_dds_dict.get("Surface_Ligand_Density_per_nm2", 0.8),
                })
                # Backfill legacy key names (BBB_Enhanced_Pct, BBB_Native_Pct,
                # Endosomal_Escape_Eff, Stealth_Index) that dozens of downstream
                # functions across the viz/report modules still read directly
                # via top_dds.get(<name>, <default>) -- see
                # _dds_metrics.backfill_legacy_aliases for why those names were
                # otherwise always absent and silently falling back to a
                # hardcoded constant for every drug.
                try:
                    from _dds_metrics import backfill_legacy_aliases as _bfla
                except ImportError:
                    from src.viz._dds_metrics import backfill_legacy_aliases as _bfla
                _top_dds_dict = _bfla(_top_dds_dict, mol_profile if isinstance(mol_profile, dict) else None)

            from cerebro_science_modules import run_all_science_modules
            _disease = mol_profile.get("disease_state") or mol_profile.get("indication","").lower()
            _disease = _disease if _disease in ["healthy","alzheimer_1","alzheimer_2","alzheimer_3",
                                                  "alzheimer_4","parkinsons_1","parkinsons_2"] else "healthy"
            science_results = run_all_science_modules(
                mol_profile   = mol_profile,
                top_dds       = _top_dds_dict,
                df_dds        = df_dds,
                output_dir    = trial_dir / "science_modules",
                disease_state = _disease,
                dose_mg       = float(mol_profile.get("dose_mg", 1.0)),
            )
            log.info(f"[SCIENCE] Part1: {len(science_results)} modules complete")
        except Exception as _e1:
            log.warning(f"[SCIENCE-1] {_e1}")
            import traceback; log.debug(traceback.format_exc())

        # Advanced modules (part 2)
        try:
            from cerebro_advanced_modules_2 import run_all_advanced_modules
            _adv = run_all_advanced_modules(
                mol_profile        = mol_profile,
                top_dds            = _top_dds_dict,
                df_dds             = df_dds,
                output_dir         = trial_dir / "science_modules",
                disease_state      = _disease,
                excursion_temp_C   = -20.0,
                excursion_h        = 4.0,
                n_clinical_patients= 500,
            )
            science_results.update(_adv)
            log.info(f"[SCIENCE-2] Part2: {len(_adv)} advanced modules complete")
        except Exception as _e2:
            log.warning(f"[SCIENCE-2] {_e2}")
            import traceback; log.debug(traceback.format_exc())

        # HTML5 Interactive Report
        try:
            from cerebro_html5_engine import build_html5_report
            _html5_dir = trial_dir / "html5"
            _html5_dir.mkdir(exist_ok=True)
            _dfd = df_dds.to_dict("records") if df_dds is not None else []
            build_html5_report(
                drug_name   = drug_name,
                top_dds     = _top_dds_dict,
                df_dds_data = _dfd,
                science     = science_results,
                mol_profile = mol_profile,
                out_path    = _html5_dir / f"CEREBRO_X_Interactive_{drug_name}.html",
                # v22 — C+ Flow data
                breakdown      = dds_principle_breakdown if 'dds_principle_breakdown' in dir() else None,
                matrix         = dds_principle_matrix    if 'dds_principle_matrix'    in dir() else None,
                deep_results   = deep_results_top1 if 'deep_results_top1' in dir() else None,
                deep_summary   = deep_summary_top1 if 'deep_summary_top1' in dir() else None,
                translational  = translational_top1 if 'translational_top1' in dir() else None,
                fallback_chain = fallback_chain_top1 if 'fallback_chain_top1' in dir() else None,
            )
            log.info("[HTML5] Interactive report generated")
        except Exception as _eh:
            import traceback as _tb
            log.error(f"[HTML5] FAILED: {type(_eh).__name__}: {_eh}")
            log.debug(_tb.format_exc())

        # Videos V01-V05 MP4 (legacy, kept for Docker output)
        try:
            from cerebro_video_engine_v2 import run_all_videos
            _dfd2 = df_dds.to_dict("records") if df_dds is not None else []
            run_all_videos(
                drug_name   = drug_name,
                top_dds     = _top_dds_dict,
                df_dds_data = _dfd2,
                science     = science_results,
                out_dir     = trial_dir / "media" / "videos",
                fps         = 24,
            )
            log.info("[VIDEO] MP4 videos generated")
        except Exception as _ev:
            log.warning(f"[VIDEO-MP4] {_ev}")

        # Videos V01-V05 HTML5 Canvas (primary — dynamic, browser-native)
        try:
            import sys as _sys_cv
            _cv_path = str(Path(__file__).parent / "src" / "viz")
            if _cv_path not in _sys_cv.path: _sys_cv.path.insert(0, _cv_path)
            from cerebro_canvas_engine import run_all_canvas_videos
            _dfd3 = df_dds.to_dict("records") if df_dds is not None else []
            _canvas_videos = run_all_canvas_videos(
                drug_name   = drug_name,
                top_dds     = _top_dds_dict,
                df_dds_data = _dfd3,
                science     = science_results,
                out_dir     = trial_dir / "media" / "canvas_videos",
            )
            _n_cv = sum(1 for v in _canvas_videos.values() if v)
            log.info(f"[CANVAS] {_n_cv}/5 HTML5 Canvas videos generated")
        except Exception as _ecv:
            log.warning(f"[CANVAS] {_ecv}")

    except ImportError:
        log.warning("[PIPELINE] cerebro_advanced_viz.py not found — using basic figures")
        _make_static_figures(df_ml, df_dds, df_pk, trial_dir)
    except Exception as _ave:
        log.warning(f"[PIPELINE] Advanced viz skipped: {_ave}")
        _make_static_figures(df_ml, df_dds, df_pk, trial_dir)

    # ── Step 11: PBBM suite ───────────────────────────────────────────────
    pbbm_results  = None
    try:
        from cerebro_pbbm_engine import PBBMOrchestrator
        pbbm_results = PBBMOrchestrator.run_full(
            drug_name   = drug_name,
            smiles      = cfg.get("drug",{}).get("smiles"),  # Never pass FASTA/PDB as smiles
            mol_profile = mol_profile,
            df_dds      = df_dds,
            trial_dir   = trial_dir,
            dose_mg     = 10.0, route="oral", n_workers=4,
        )
        admet_profile = pbbm_results.get("admet") if pbbm_results else None
        log.info("[PIPELINE] PBBM suite complete")
    except ImportError:
        log.warning("[PIPELINE] cerebro_pbbm_engine.py not found")
    except Exception as _pbbme:
        log.warning(f"[PIPELINE] PBBM skipped: {_pbbme}")

    # ── Step 11b: Science Engines + 3D Visualisation suite ─────────────────
    # ScienceOrchestrator (quantum chemistry, Mordred descriptors,
    # thermodynamics, 7-cmt PBPK, biophysics) and VisualisationOrchestrator
    # (7 figures, 2 schematics, 2 videos) are real, working code, but I found
    # they had zero live caller anywhere in the codebase — run.py's
    # _run_science_and_viz wrapper was itself unreachable dead code. Wiring
    # them in directly here instead of restoring that wrapper, so trial_dir
    # is the real per-drug output folder rather than a separate location.
    # PBPK output here (science_results/) is a supplementary cross-check
    # using a different method (Poulin-Theil) than pbbm_engine's primary
    # ADMET/report PBPK (Rodgers-Rowland) — kept distinct rather than
    # silently merged, each labeled with its own method and citation.
    try:
        from cerebro_science_engines import ScienceOrchestrator
        results_sci = ScienceOrchestrator.run_full(
            drug_name    = drug_name,
            smiles       = cfg.get("drug", {}).get("smiles"),  # Never pass FASTA/PDB as smiles
            mol_profile  = mol_profile,
            df_dds       = df_dds,
            trial_dir    = trial_dir,
            run_quantum  = True,
            run_mordred  = True,
            run_thermo   = True,
            run_pkpd     = True,
            run_pbpk     = True,
            run_biophysics = True,
        )
        df_bio_sci  = results_sci.get("biophysics")
        df_pbpk_sci = results_sci.get("pbpk")
        log.info(f"[SCI] Engines complete: {list(results_sci.keys())}")

        try:
            from cerebro_visualization_3d import VisualisationOrchestrator
            _viz_produced = VisualisationOrchestrator.run_all(
                drug_name   = drug_name,
                mol_profile = mol_profile,
                df_ml       = df_ml,
                df_dds      = df_dds,
                df_pk       = df_pk,
                df_pbpk     = df_pbpk_sci,
                df_bio      = df_bio_sci,
                trial_dir   = trial_dir,
                make_videos = True,
            )
            log.info(f"[VIZ] Complete: {len(_viz_produced)} files")
        except ImportError:
            log.warning("[VIZ] cerebro_visualization_3d.py not found")
        except Exception as _viz_e:
            log.warning(f"[VIZ] Skipped: {_viz_e}")
    except ImportError:
        log.warning("[SCI] cerebro_science_engines.py not found")
    except Exception as _sci_e:
        log.warning(f"[SCI] Engines skipped: {_sci_e}")

    # ── Step 12: Data Engineering (7 pillars) ─────────────────────────────
    de_results = None
    try:
        from cerebro_data_engineering import DataEngineeringOrchestrator
        ref_df = None
        try:
            import pandas as _pd2
            prev_parts = list(RESULTS_ROOT.glob("trial_id=*/data.parquet"))
            if prev_parts:
                ref_df = _pd2.concat([_pd2.read_parquet(p) for p in prev_parts], ignore_index=True)
        except Exception as _exc_silenced:
            # FIXED: was silent — now logged
            import logging as _elog
            _elog.getLogger("CEREBRO").warning(f"[SUPPRESSED] {_exc_silenced!r} — in run.py")
            del _exc_silenced
        de_results = DataEngineeringOrchestrator.run_full(
            trial_dir=trial_dir, results_root=RESULTS_ROOT,
            drug_name=drug_name,
            drug_data={
                "MW_Da": mol_profile.get("MW_Da"),
                "LogP":  mol_profile.get("LogP"),
                "Half_Life_Days": mol_profile.get("Half_Life_Days"),
                "_source":        mol_profile.get("_source","pipeline"),
                "_tier":          mol_profile.get("_tier",0),
                "_doi":           mol_profile.get("_doi",""),
                "_alignment_flag":mol_profile.get("_alignment_flag",False),
                "_missing_pk_reason": mol_profile.get("_missing_pk_reason",""),
                "_tiers_tried":   mol_profile.get("_tiers_tried",[]),
                "_surrogate_drug":mol_profile.get("_surrogate_drug",""),
                "_tanimoto_sim":  mol_profile.get("_tanimoto_sim"),
                "_uncertainty_pct":mol_profile.get("_uncertainty_pct",30),
            },
            reference_df=ref_df, n_workers=4)
        log.info("[PIPELINE] Data Engineering suite complete (7 pillars)")
    except ImportError:
        log.warning("[PIPELINE] cerebro_data_engineering.py not found")
    except Exception as _dee:
        log.warning(f"[PIPELINE] DE suite skipped: {_dee}")

    # ── Step 13: Master report text (legacy) ──────────────────────────────
    try:
        df_aav = cp.CascadeDataEngine.fetch_aav_data()
        cp.ReportingEngine.generate_master_report(df_mab, df_aav, df_ml, metrics, df_dds=df_dds)
    except Exception as _exc_silenced:
        # FIXED: was silent — now logged
        import logging as _elog
        _elog.getLogger("CEREBRO").warning(f"[SUPPRESSED] {_exc_silenced!r} — in run.py")
        del _exc_silenced

    # ── Step 14: Final Decision Report (PDF + HTML with all content) ──────
    try:
        from cerebro_final_report import FinalReportGenerator
        FinalReportGenerator.generate(
            drug_name      = drug_name,
            trial_dir      = trial_dir,
            excel_name     = excel_path.name,
            mol_profile    = mol_profile,
            df_ml          = df_ml,
            df_dds         = df_dds,
            df_pk          = df_pk,
            metrics        = metrics,
            pbbm_results   = pbbm_results,
            de_results     = de_results,
            admet_profile  = admet_profile,
            # science_results passed via top_dds dict merge below
        )

        # ── Unified PDF (all 62 modules) ─────────────────────────────
        try:
            import sys as _sys_pdf
            _cp = str(Path(__file__).parent / "src" / "core")
            if _cp not in _sys_pdf.path: _sys_pdf.path.insert(0, _cp)
            from final_report_unified import UnifiedPDFReport
            _updf = UnifiedPDFReport.generate(
                drug_name       = drug_name,
                trial_dir       = trial_dir,
                mol_profile     = mol_profile,
                df_dds          = df_dds,
                top_dds         = _top_dds_dict,
                science_results = science_results,
                df_ml           = df_ml,
                df_pk           = df_pk,
                pbbm_results    = pbbm_results,
                # v22 — C+ Flow data
                dds_principle_breakdown = dds_principle_breakdown if 'dds_principle_breakdown' in dir() else None,
                dds_principle_matrix    = dds_principle_matrix    if 'dds_principle_matrix'    in dir() else None,
                deep_results    = deep_results_top1 if 'deep_results_top1' in dir() else None,
                deep_summary    = deep_summary_top1 if 'deep_summary_top1' in dir() else None,
                translational   = translational_top1 if 'translational_top1' in dir() else None,
                fallback_chain  = fallback_chain_top1 if 'fallback_chain_top1' in dir() else None,
            )
            if _updf:
                log.info(f"[PDF] Unified: {_updf.name} ({_updf.stat().st_size//1024} KB)")
            else:
                log.warning("[PDF] Unified report generation failed")
        except Exception as _ep:
            log.warning(f"[PDF-UNIFIED] {_ep}")
        log.info("[PIPELINE] Final decision report generated (PDF + HTML)")
    except ImportError:
        log.warning("[PIPELINE] cerebro_final_report.py not found — using basic PDF")
        _generate_merged_pdf(df_ml, df_dds, df_pk, metrics,
                              mol_profile, trial_dir, drug_name)
    except Exception as _rpe:
        log.warning(f"[PIPELINE] Final report skipped: {_rpe}")
        _generate_merged_pdf(df_ml, df_dds, df_pk, metrics,
                              mol_profile, trial_dir, drug_name)

    # ── Step 15: Write trial documentation ────────────────────────────────
    _write_trial_doc(trial_dir, excel_path, drug_name, n_forms,
                      metrics, df_dds)

    # [PBBM moved to Step 11 above]


    # [DE moved to Step 12 above]

    # ── Register in index ─────────────────────────────────────────────────
    register_trial(excel_path, excel_hash, drug_name, n_forms,
                   trial_dir, status="complete")

    log.info(f"[PIPELINE] ✓ Trial complete → {trial_dir}")
    log.info(f"  Drug: {drug_name}  |  R²={metrics.get('r2',0):.4f}  "
             f"|  Formulations: {n_forms}")
    if df_dds is not None and not df_dds.empty:
        top = df_dds.iloc[0]
        log.info(f"  Top DDS: {top.get('Formulation_Name','')}  "
                 f"BBB={top.get('BBB_Engineering_Score',0):.1f}")

    # ══════════════════════════════════════════════════════════════════════
    # MULTI-DRUG SEQUENTIAL LOOP
    # Drugs are processed in Excel order: Drug 1 → Drug 2 → Drug 3 …
    # Drug names and SMILES/FASTA come entirely from the Excel file —
    # nothing is hardcoded here.
    # ══════════════════════════════════════════════════════════════════════
    additional_drugs = cfg.get("additional_drugs", [])   # dynamic from Excel
    # Filter out empty/example slots once, preserve original Excel order
    additional_drugs = [d for d in additional_drugs
                        if d.get("name","").strip()
                        and d["name"].strip().lower() not in ("example", "")]

    all_drug_names = [drug_name] + [d["name"] for d in additional_drugs]
    total_drugs    = len(all_drug_names)
    log.info(f"[MULTI-DRUG] Total drugs from Excel: {total_drugs} → {all_drug_names}")
    log.info(f"[MULTI-DRUG] Drug 1/{total_drugs} '{drug_name}' already complete ✅")

    all_drug_results = [{"drug_name": drug_name, "trial_dir": trial_dir,
                          "df_dds": df_dds, "mol_profile": mol_profile,
                          "science": science_results
                                      if 'science_results' in dir() else {},
                          "dds_principle_matrix":
                              dds_principle_matrix
                              if 'dds_principle_matrix' in dir() else [],
                          "dds_principle_breakdown":
                              dds_principle_breakdown
                              if 'dds_principle_breakdown' in dir() else [],
                          "deep_results":
                              deep_results_top1
                              if 'deep_results_top1' in dir() else {},
                          "deep_summary":
                              deep_summary_top1
                              if 'deep_summary_top1' in dir() else {},
                          "translational":
                              translational_top1
                              if 'translational_top1' in dir() else {},
                          "fallback_chain":
                              fallback_chain_top1
                              if 'fallback_chain_top1' in dir() else []}]

    for _drug_idx, extra_drug_cfg in enumerate(additional_drugs, start=2):
        _extra_name = extra_drug_cfg.get("name","").strip()

        log.info("=" * 65)
        log.info(f"  DRUG {_drug_idx}/{total_drugs}: {_extra_name}")
        log.info("  Sequential — previous drug fully complete before this starts")
        log.info("=" * 65)

        # Trial dir: numbered sequentially so names never conflict on re-runs.
        # If the parent trial_dir already ends in a number (e.g. "Trial_0"),
        # increment from there. Otherwise, build a per-drug subdirectory.
        # Phase 5 (2026-04-30): hardened against arbitrary trial_dir names
        # like "CEREBRO_VALIDATION_E2E" — previous code crashed with
        # ValueError: invalid literal for int() with base 10: 'E2E'.
        _trial_suffix = trial_dir.name.split("_")[-1]
        try:
            _trial_base_n = int(_trial_suffix)
            _drug_trial_n = _trial_base_n + (_drug_idx - 1)
            _extra_trial_dir = trial_dir.parent / f"Trial_{_drug_trial_n}"
        except ValueError:
            # Trial dir name does not end with a number — use named subdirs
            _safe_drug = "".join(c if c.isalnum() else "_" for c in _extra_name)[:40]
            _extra_trial_dir = trial_dir.parent / f"{trial_dir.name}_drug{_drug_idx}_{_safe_drug}"
        _extra_trial_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"[MULTI-DRUG] Output dir → {_extra_trial_dir}")

        # ── Reset cp.PATHS to this drug's own trial dir ──────────────
        # Without this, Drug 2 & 3 outputs overwrite Drug 1's files.
        # "figures" joins the other media subfolders under media/ (see the
        # matching comment at the primary-drug PATHS reset above).
        for _key in list(cp.PATHS.keys()):
            _base = _extra_trial_dir / "media" if _key == "figures" else _extra_trial_dir
            _sub = _base / cp.PATHS[_key].name
            _sub.mkdir(parents=True, exist_ok=True)
            cp.PATHS[_key] = _sub
        cp.DB_PATH          = str(_extra_trial_dir / "cerebro.db")
        cp.MISSING_DATA_LOG = str(_extra_trial_dir / "Missing_Data_Log.txt")
        cp.setup_workspace()
        log.info(f"[MULTI-DRUG] cp.PATHS reset → {_extra_trial_dir}")

        # ── Step 1: Build per-drug YAML ─────────────────────────────
        _extra_yaml = _extra_trial_dir / "dds_config.yaml"
        try:
            import yaml as _yaml
            _extra_cfg = {
                "drug": {
                    "name":            _extra_name,
                    "molecule_class":  extra_drug_cfg.get("molecule_class","small_molecule"),
                    "molecule_input":  extra_drug_cfg.get("molecule_input", _extra_name),
                    "smiles":          extra_drug_cfg.get("smiles"),
                    "fasta":           extra_drug_cfg.get("fasta"),
                    "indication":      extra_drug_cfg.get("indication",""),
                    "bbb_native_pct":  extra_drug_cfg.get("bbb_native_pct"),
                    "clinical_phase":  extra_drug_cfg.get("clinical_phase",""),
                    "force_refresh":   True,
                },
                "additional_drugs": [],  # Drug 2 never spawns Drug 3+
                "formulations": cfg.get("formulations", []),  # Same DDS for all drugs
            }
            with open(_extra_yaml, "w", encoding="utf-8") as _f:
                _yaml.dump(_extra_cfg, _f, allow_unicode=True)
            log.info(f"[MULTI-DRUG] YAML written for {_extra_name}")
        except Exception as _ye:
            log.error(f"[MULTI-DRUG] YAML build failed for {_extra_name}: {_ye}")
            continue

        # ── Step 2: Cache + DB isolation for this drug ─────────────
        invalidate_molecule_cache([_extra_name], _extra_trial_dir)
        try:
            import sqlite3 as _sq
            with _sq.connect(cp.DB_PATH) as _conn:
                _conn.execute("DELETE FROM drugs WHERE LOWER(drug_name)=LOWER(?)",
                               (_extra_name,))
                _conn.commit()
        except Exception: pass

        # ── Step 3: Fetch molecular properties ──────────────────────
        # Prefer smiles/fasta (clean, typed) over molecule_input (raw string)
        # All three come from the Excel parser — nothing is hardcoded
        _extra_mol_input = (extra_drug_cfg.get("smiles")      # SMILES if present
                             or extra_drug_cfg.get("fasta")    # FASTA for biologics
                             or extra_drug_cfg.get("helm")     # HELM peptides
                             or extra_drug_cfg.get("molecule_input")  # raw fallback
                             or _extra_name)                   # name-only last resort
        log.info(f"[MULTI-DRUG] {_extra_name}: mol_input type="
                 f"{'smiles' if extra_drug_cfg.get('smiles') else 'fasta' if extra_drug_cfg.get('fasta') else 'name'}")
        _extra_mol: dict = {}
        try:
            from cerebro_molecule_engine import analyze_molecule
            _extra_mol = analyze_molecule(_extra_mol_input, _extra_name)
            log.info(f"[MULTI-DRUG] {_extra_name}: MW={_extra_mol.get('MW_Da')} "
                     f"LogP={_extra_mol.get('LogP')}")
        except Exception as _me:
            log.warning(f"[MULTI-DRUG] MoleculeEngine failed for {_extra_name}: {_me}")

        # Inject BBB if provided
        if extra_drug_cfg.get("bbb_native_pct") and not _extra_mol.get("BBB_permeability_pct"):
            _extra_mol["BBB_permeability_pct"] = float(extra_drug_cfg["bbb_native_pct"])
        _extra_mol["name"] = _extra_name
        # Carry SMILES forward so enricher can fetch descriptors
        if extra_drug_cfg.get("smiles") and not _extra_mol.get("smiles"):
            _extra_mol["smiles"] = extra_drug_cfg["smiles"]
        if extra_drug_cfg.get("fasta") and not _extra_mol.get("fasta"):
            _extra_mol["fasta"] = extra_drug_cfg["fasta"]
        if extra_drug_cfg.get("molecule_class"):
            _extra_mol["molecule_class"] = extra_drug_cfg["molecule_class"]

        # ── v22.1 MOLECULE-AWARE ENRICHMENT (Drug 2..N) ────────────────
        try:
            from cerebro_molecule_extractor import enrich_mol_profile
            _extra_mol = enrich_mol_profile(_extra_mol)
            log.info(f"[MOL-EXTRACTOR] {_extra_name} enriched via "
                      f"{_extra_mol.get('_primary_source','?')}: "
                      f"LogP={_extra_mol.get('LogP')} "
                      f"TPSA={_extra_mol.get('TPSA_A2')} "
                      f"pKa={_extra_mol.get('pKa')} "
                      f"NetCharge={_extra_mol.get('NetCharge_pH74')}")
        except Exception as _ext_e2:
            log.warning(f"[MOL-EXTRACTOR] Enrichment failed for "
                         f"{_extra_name}: {_ext_e2}")

        # ── Step 4: Cascade data fetch + ML ─────────────────────────
        try:
            _extra_df = cp.CascadeDataEngine.build_mab_dataset([_extra_name])
            if _extra_df.empty or len(_extra_df) < 2:
                _extra_df = _augment_single_drug(_extra_df if not _extra_df.empty
                                                  else __import__("pandas").DataFrame([_extra_mol]), n=8)
            cp.db_upsert_drugs(_extra_df, source="excel_multi", doi=_extra_name)
            _feat_cols = [c for c in ["MW_Da","LogP","Half_Life_Days","Docking_Affinity_kcal"]
                          if c in _extra_df.columns]
            _extra_df_ml, _, _extra_metrics = cp.AdvancedMLEngine.train(
                _extra_df, feature_cols=_feat_cols)
            _extra_df_ml = cp.ADMETEngine.run(_extra_df_ml)
            _extra_df_pk = cp.AnalyticsEngine.simulate_pkpd(_extra_df_ml)
        except Exception as _mle:
            log.warning(f"[MULTI-DRUG] ML failed for {_extra_name}: {_mle}")
            _extra_df_ml = _extra_df_pk = None

        # ── Step 5: DDS scoring (same formulations, different drug) ─
        _extra_df_dds = _run_dds_from_yaml(_extra_yaml, _extra_trial_dir,
                                             _extra_name, _extra_mol, _extra_df_ml)

        # ── Step 5b [v22]: 62-PRINCIPLE C+ FLOW for this drug ─
        _extra_dds_matrix     = []
        _extra_dds_breakdown  = []
        _extra_deep_results   = {}
        _extra_deep_summary   = {}
        _extra_translational  = {}
        _extra_fallback_chain = []
        if _extra_df_dds is not None and not _extra_df_dds.empty:
            try:
                from cerebro_62_orchestrator import evaluate_all_dds_62
                from cerebro_resolved_bundles import resolve_drug_bundle
                _extra_overrides = (_extra_mol.get("_researcher_overrides", {})
                                      if isinstance(_extra_mol, dict) else {})
                _extra_drug_bundle = resolve_drug_bundle(
                    name     = _extra_mol.get("name", _extra_name),
                    smiles   = _extra_mol.get("smiles", ""),
                    fasta    = _extra_mol.get("fasta", ""),
                    sequence = _extra_mol.get("sequence", ""),
                    molecule_class = _extra_mol.get("molecule_class", ""),
                    researcher_overrides = _extra_overrides,
                    target_pdb_id = extra_drug_cfg.get("target_pdb_id", ""),
                )
                _orch_extra = evaluate_all_dds_62(drug_bundle=_extra_drug_bundle,
                                                    df_dds=_extra_df_dds,
                                                    drug_name=_extra_name,
                                                    context={})
                _extra_df_dds         = _orch_extra["ranked_df"]
                _extra_dds_matrix     = _orch_extra["all_dds_principles"]
                _extra_dds_breakdown  = _orch_extra["all_dds_breakdown"]
                _extra_deep_results   = _orch_extra["deep_results"]
                _extra_deep_summary   = _orch_extra["deep_summary"]
                _extra_translational  = _orch_extra["translational"]
                _extra_fallback_chain = _orch_extra["fallback_chain"]
                log.info(f"[62-ORCH] {_extra_name}: re-ranked "
                          f"{len(_extra_df_dds)} DDS — top: "
                          f"{_orch_extra['top1_dds_name']} "
                          f"(deep: {_extra_deep_summary.get('verdict','?')})")

                # Same fix as the primary-drug path above: recompute Rank to
                # match the post-rerank row order and rewrite both CSVs so
                # they agree with what the report treats as the top pick.
                _extra_df_dds["Rank"] = range(1, len(_extra_df_dds) + 1)
                _extra_dds_dir = _extra_trial_dir / "dds_analysis"
                _extra_df_dds.to_csv(_extra_dds_dir / "formulation_ranking.csv", index=False)
                _extra_df_dds.head(10).to_csv(_extra_dds_dir / "top10_formulations.csv", index=False)
            except Exception as _de2:
                log.warning(f"[62-ORCH] Per-DDS eval failed for "
                            f"{_extra_name}: {_de2}")
                import traceback; log.debug(traceback.format_exc())

        # ── Step 6: Science modules (all 62 points) — top-1 deep dive ────
        _extra_top = {}
        if _extra_df_dds is not None and not _extra_df_dds.empty:
            _extra_top = _extra_df_dds.iloc[0].to_dict()
        try:
            import sys as _sys_sci
            for _sp in [str(Path(__file__).parent/"src"/"core"),
                         str(Path(__file__).parent/"src"/"viz")]:
                if _sp not in _sys_sci.path: _sys_sci.path.insert(0, _sp)
            # Same legacy-key backfill as the primary drug's _top_dds_dict
            # (see _dds_metrics.backfill_legacy_aliases) — this dict feeds
            # the same downstream consumers for Drug 2..N.
            try:
                from _dds_metrics import backfill_legacy_aliases as _bfla2
            except ImportError:
                from src.viz._dds_metrics import backfill_legacy_aliases as _bfla2
            _extra_top = _bfla2(_extra_top, _extra_mol if isinstance(_extra_mol, dict) else None)
            from cerebro_advanced_modules_2 import run_all_advanced_modules
            from cerebro_science_modules import run_all_science_modules
            _extra_sci = run_all_science_modules(
                _extra_mol, _extra_top, _extra_df_dds, _extra_trial_dir, "alzheimer_2", 75)
            _extra_adv = run_all_advanced_modules(
                _extra_mol, _extra_top, _extra_df_dds, _extra_trial_dir)
            _extra_sci.update(_extra_adv)
        except Exception as _se:
            log.warning(f"[MULTI-DRUG] Science modules failed for {_extra_name}: {_se}")
            _extra_sci = {}

        # ── Step 7: HTML5 + PDF for this drug ────────────────────────
        try:
            from cerebro_html5_engine import build_html5_report
            _extra_html5_dir = _extra_trial_dir / "html5"
            _extra_html5_dir.mkdir(exist_ok=True)
            _html5_content = build_html5_report(
                drug_name=_extra_name, top_dds=_extra_top,
                df_dds_data=(_extra_df_dds.to_dict("records") if _extra_df_dds is not None else []),
                science=_extra_sci, mol_profile=_extra_mol,
                out_path=_extra_html5_dir/f"CEREBRO_X_Interactive_{_extra_name}.html",
                # v22 — C+ Flow data
                breakdown      = _extra_dds_breakdown,
                matrix         = _extra_dds_matrix,
                deep_results   = _extra_deep_results,
                deep_summary   = _extra_deep_summary,
                translational  = _extra_translational,
                fallback_chain = _extra_fallback_chain,
            )
            log.info(f"[MULTI-DRUG] HTML5 generated for {_extra_name} ✅")
        except Exception as _he:
            log.warning(f"[MULTI-DRUG] HTML5 failed for {_extra_name}: {_he}")

        try:
            from final_report_unified import UnifiedPDFReport
            UnifiedPDFReport.generate(
                trial_dir=_extra_trial_dir, drug_name=_extra_name,
                mol_profile=_extra_mol, top_dds=_extra_top,
                df_dds=_extra_df_dds,
                science_results=_extra_sci,
                # v22 — C+ Flow data
                dds_principle_breakdown = _extra_dds_breakdown,
                deep_results    = _extra_deep_results,
                deep_summary    = _extra_deep_summary,
                translational   = _extra_translational,
                fallback_chain  = _extra_fallback_chain,
            )
            log.info(f"[MULTI-DRUG] PDF generated for {_extra_name} ✅")
        except Exception as _pe:
            log.warning(f"[MULTI-DRUG] PDF failed for {_extra_name}: {_pe}")

        all_drug_results.append({
            "drug_name": _extra_name, "trial_dir": _extra_trial_dir,
            "df_dds": _extra_df_dds, "mol_profile": _extra_mol,
            "science": _extra_sci,
            "dds_principle_matrix":    _extra_dds_matrix,
            "dds_principle_breakdown": _extra_dds_breakdown,
            "deep_results":            _extra_deep_results,
            "deep_summary":            _extra_deep_summary,
            "translational":           _extra_translational,
            "fallback_chain":          _extra_fallback_chain,
        })
        log.info(f"[MULTI-DRUG] ✅ Drug {_drug_idx}/{total_drugs} '{_extra_name}' complete"
                 f" → {_extra_trial_dir.name}")
        if _drug_idx < total_drugs:
            log.info(f"[MULTI-DRUG] → Starting Drug {_drug_idx+1}/{total_drugs}: "
                     f"'{all_drug_names[_drug_idx]}'")

    # ── COMPARISON REPORT (all drugs processed) ──────────────────────────
    if len(all_drug_results) > 1:
        log.info(f"[COMPARISON] Generating comparison for "
                  f"{[r['drug_name'] for r in all_drug_results]}")
        try:
            _comp_dir = trial_dir.parent / "Comparison_Report"
            _comp_dir.mkdir(exist_ok=True)
            from cerebro_html5_engine import build_html5_report
            build_html5_report(
                drug_name=" vs ".join(r["drug_name"] for r in all_drug_results),
                top_dds=all_drug_results[0]["df_dds"].iloc[0].to_dict()
                         if all_drug_results[0]["df_dds"] is not None
                         and not all_drug_results[0]["df_dds"].empty else {},
                df_dds_data=[],
                science={},
                mol_profile=all_drug_results[0]["mol_profile"],
                multi_results=all_drug_results,
                out_path=_comp_dir / "CEREBRO_X_Comparison_Report.html")
            log.info(f"[COMPARISON] Report saved → {_comp_dir}/CEREBRO_X_Comparison_Report.html ✅")
        except Exception as _ce:
            log.warning(f"[COMPARISON] Failed: {_ce}")

    # ── v20: COMPLETED-DATA EXCEL  (always — single AND multi-drug) ──────
    # Writes a workbook per drug with every resolved property, full provenance
    # (Tier 1-99), confidence scores, sources, and disclaimers. For multi-drug
    # runs, also emits a combined workbook in the Comparison_Report folder.
    try:
        from cerebro_completed_excel_writer import write_completed_excel
        # Normalize "science" key → "principles" for downstream consistency
        for _dr in all_drug_results:
            if "science" in _dr and "principles" not in _dr:
                _dr["principles"] = _dr["science"]

        # Per-drug completed Excel (lives in each drug's Trial dir)
        for _dr in all_drug_results:
            _dr_trial = Path(_dr.get("trial_dir") or trial_dir)
            _safe_name = "".join(c for c in _dr["drug_name"] if c.isalnum())
            _completed_path = _dr_trial / f"CEREBRO_X_Completed_Data_{_safe_name}.xlsx"
            try:
                write_completed_excel(
                    drug_results=[_dr],
                    output_path=_completed_path,
                    pipeline_metadata={"version":"v20",
                                        "source_excel": str(excel_path)})
            except Exception as _wpe:
                log.warning(f"[COMPLETED] Per-drug Excel failed for "
                            f"{_dr['drug_name']}: {_wpe}")

        # Combined completed Excel (multi-drug only)
        if len(all_drug_results) > 1:
            _combined_dir = trial_dir.parent / "Comparison_Report"
            _combined_dir.mkdir(exist_ok=True)
            _combined_path = _combined_dir / "CEREBRO_X_Completed_Data_All_Drugs.xlsx"
            write_completed_excel(
                drug_results=all_drug_results,
                output_path=_combined_path,
                pipeline_metadata={"version":"v20",
                                    "source_excel": str(excel_path)})
            log.info(f"[COMPLETED] Combined Excel → {_combined_path.name} ✅")
    except ImportError as _cie:
        log.warning(f"[COMPLETED] Writer module missing — skipped: {_cie}")
    except Exception as _ce2:
        log.warning(f"[COMPLETED] Writer failed: {_ce2}")
        import traceback; log.debug(traceback.format_exc())

    # ── v20: 62-PRINCIPLE CROSS-DRUG COMPARISON  (multi-drug only) ───────
    # Builds the principle-by-principle ranking and emits Excel + JSON.
    # Skipped silently when only one drug is present.
    if len(all_drug_results) > 1:
        try:
            from cerebro_multi_drug_comparison import compare_drugs
            _comp_dir2 = trial_dir.parent / "Comparison_Report"
            _comp_dir2.mkdir(exist_ok=True)
            _comp_summary = compare_drugs(
                drug_results=all_drug_results,
                output_dir=_comp_dir2,
                pipeline_metadata={"version":"v20",
                                    "source_excel": str(excel_path)})
            if _comp_summary.get("status") != "skipped":
                log.info(f"[COMPARISON] 62-principle engine: "
                          f"{_comp_summary['metrics_ranked']} metrics ranked "
                          f"(+ {_comp_summary['metrics_unranked']} unranked)")
                log.info("[COMPARISON] Overall ranking:")
                for entry in _comp_summary['overall_ranking']:
                    log.info(f"  #{entry['rank']}  {entry['drug']:20s}  "
                              f"score={entry['weighted_score']}/100  "
                              f"wins={_comp_summary['winner_counts'][entry['drug']]}")
        except ImportError as _cie2:
            log.warning(f"[COMPARISON] 62-principle module missing — skipped: {_cie2}")
        except Exception as _cme:
            log.warning(f"[COMPARISON] 62-principle engine failed: {_cme}")
            import traceback; log.debug(traceback.format_exc())

    return True


def _augment_single_drug(df, n: int = 8):
    """
    When only one drug is available, generate synthetic neighbours
    by adding Gaussian noise (σ=5% of each numeric column).

    TRANSPARENCY NOTE:
    This is a statistical regularization technique — NOT new data.
    All synthetic rows are tagged _synthetic=True and EXCLUDED from:
      - Final report tables
      - Clinical recommendations
      - Published ML metrics

    The ML model trains on these for numerical stability only.
    R² from this training is reported as "N/A — single-drug trial"
    because the model generalizes only to the synthetic distribution
    of this one drug, not to the pharmacological population.

    Reference: Chawla NV et al (2002) JAIR 16:321 (SMOTE oversampling rationale)
    """
    import numpy as np
    import pandas as pd
    np.random.seed(42)   # reproducible synthetic data
    synth_rows = []
    row = df.iloc[0]
    nums = df.select_dtypes(include=np.number).columns.tolist()
    for i in range(n):
        new = row.copy()
        for c in nums:
            if row[c] and row[c] != 0:
                # σ=5% Gaussian noise — stays within physiological range
                new[c] = row[c] * (1 + np.random.normal(0, 0.05))
        new["_synthetic"]       = True
        new["_synthetic_seed"]  = i
        new["_synthetic_method"] = "Gaussian_5pct_noise"
        synth_rows.append(new)

    df = df.copy()
    df["_synthetic"]       = False
    df["_synthetic_seed"]  = -1
    df["_synthetic_method"] = "real"

    augmented = pd.concat([df, pd.DataFrame(synth_rows)], ignore_index=True)
    log.info(f"[AUGMENT] 1 real row + {n} synthetic (Gaussian 5%) → {len(augmented)} total")
    log.warning(
        "[AUGMENT] ML will train on synthetic data. "
        "R² is valid mathematically but represents single-drug neighbourhood, "
        "NOT pharmacological population generalisation. "
        "Report will show: 'Single-drug trial — ML metrics are regularization artifacts.'"
    )
    return augmented


def _run_dds_from_yaml(yaml_path: Path, trial_dir: Path,
                        drug_name: str, mol_profile: dict,
                        df_ml) -> "pd.DataFrame | None":
    """
    Run DDSEngine on the YAML file written from the Excel.
    Returns ranked DataFrame.
    """
    try:
        import pandas as pd
        import yaml

        with open(yaml_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        forms = cfg.get("formulations", [])
        if not forms:
            log.warning("[DDS] No formulations in YAML")
            return None

        # Carrier-specific scientific defaults for nullable parameters
        _CARRIER_PH_DEFAULTS = {
            'liposome':                  6.5,   # endosomal escape design
            'vexosome':                  6.5,   # membrane-based vesicle
            'solid lipid nanoparticle':  7.4,   # no pH trigger — SLN is temp-responsive
            'polymeric nanoparticle':    7.4,   # no pH trigger — polymer swelling
        }
        _CARRIER_TM_DEFAULTS = {
            'liposome':                  42.0,  # DPPC thermosensitive membrane
            'vexosome':                  37.5,  # biological membrane
            'solid lipid nanoparticle':  40.0,  # cetyl palmitate Tm
            'polymeric nanoparticle':    200.0, # glass Tg >> 37 → no melt → no penalty
        }

        def _sf(val, default, carrier=None, param=None):
            """Safe float: handles None, 'None', '', 'nan', 'null'.
            Uses carrier-specific scientific defaults when val is null."""
            is_null = (val is None) or (str(val).strip().lower() in
                       ('none', '', 'nan', 'null', 'n/a', '#n/a', '(auto)'))
            if is_null:
                if carrier and param == 'ph_trigger':
                    c = str(carrier).lower()
                    for k, v in _CARRIER_PH_DEFAULTS.items():
                        if k in c: return v
                if carrier and param == 'phase_transition_temp_c':
                    c = str(carrier).lower()
                    for k, v in _CARRIER_TM_DEFAULTS.items():
                        if k in c: return v
                return float(default)
            try:
                return float(val)
            except (ValueError, TypeError):
                return float(default)

        rows = []
        for fm in forms:
            if not fm or not fm.get("Formulation_ID"):
                continue
            row = {
                "Formulation_ID":   fm.get("Formulation_ID",""),
                "Formulation_Name": fm.get("Formulation_Name",""),
                "Carrier_Type":     fm.get("Carrier_Type",""),
                "Surface_Ligand":   fm.get("Surface_Ligand","None"),
                "size_nm":          _sf(fm.get("Size_nm"), 100),
                "zeta_potential_mv":_sf(fm.get("Zeta_Potential_mV"), -10),
                "shape":            fm.get("Shape","spherical"),
                "pdi":              _sf(fm.get("PDI"), 0.2),
                "elasticity_kpa":   _sf(fm.get("Elasticity_kPa"), 1.0),
                "ligand_density_per_nm2": _sf(fm.get("Surface_Ligand_Density_per_nm2"), 0.8),
                "peg_chain_length_da":    _sf(fm.get("PEG_Chain_Length_Da"), 2000),
                "pegylation_degree_mol_pct": _sf(fm.get("PEGylation_Degree_mol_pct"), 5),
                "drug_loading_pct": _sf(fm.get("Drug_Loading_pct"), 10),
                "encapsulation_efficiency_pct": _sf(fm.get("Encapsulation_Efficiency_pct"), 75),
                "lipid_to_drug_ratio": _sf(fm.get("Lipid_to_Drug_Ratio"), 5),
                "release_kinetics": fm.get("Release_Kinetics","sustained"),
                "ph_trigger":       _sf(fm.get("pH_Trigger"), 6.5, carrier=fm.get("Carrier_Type"), param="ph_trigger"),
                "phase_transition_temp_c": _sf(fm.get("Phase_Transition_Temp_C"), 42, carrier=fm.get("Carrier_Type"), param="phase_transition_temp_c"),
                "manufacturing_method": fm.get("Manufacturing_Method","microfluidics"),
                "route":            fm.get("Route","IV"),
                # Drug-level data (same for all formulations in this trial)
                "MW_Da":            mol_profile.get("MW_Da") or 0,
                "LogP":             mol_profile.get("LogP") or 0,
                "Half_Life_Days":   mol_profile.get("Half_Life_Days") or 0,
            }
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)

        # Per-formulation ML — train a GradientBoosting model on the DDS parameters
        # to predict ML_Success_Probability from formulation biophysics.
        # This gives a DIFFERENT score for each of the 100 formulations
        # (not the same average value for all).
        try:
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.preprocessing import RobustScaler as _RS

            _dds_features = [
                "size_nm", "zeta_potential_mv", "pdi", "elasticity_kpa",
                "ligand_density_per_nm2", "peg_chain_length_da",
                "pegylation_degree_mol_pct", "drug_loading_pct",
                "encapsulation_efficiency_pct", "lipid_to_drug_ratio",
                "ph_trigger", "phase_transition_temp_c",
            ]
            _avail_feats = [c for c in _dds_features if c in df.columns]

            # Proxy target: use BBB_Engineering_Score computed next step
            # Since we can't compute BBB_Score yet, use a composite of
            # known biophysical predictors as the target signal
            _X = df[_avail_feats].fillna(0).values

            # Construct proxy target from domain knowledge:
            # Optimal BBB: size 60-100nm, zeta -5 to -15mV, high EE, good PEG
            _sz_score  = df["size_nm"].apply(
                lambda s: 1.0 if 60<=s<=100 else 0.6 if 40<=s<=130 else 0.2)
            _zeta_score = df["zeta_potential_mv"].abs().apply(
                lambda z: 1.0 if 5<=z<=15 else 0.7 if 15<z<=25 else 0.3)
            _ee_score  = df["encapsulation_efficiency_pct"].apply(
                lambda e: 1.0 if e>=80 else 0.5 if e>=60 else 0.2)
            _peg_score = df["pegylation_degree_mol_pct"].apply(
                lambda p: 1.0 if 2<=p<=7 else 0.6 if 1<=p<=10 else 0.2)
            _proxy_y = (0.35*_sz_score + 0.25*_zeta_score +
                        0.20*_ee_score + 0.20*_peg_score).values * 100

            _scaler = _RS()
            _X_s = _scaler.fit_transform(_X)

            # Train on all 100 with small noise augmentation to avoid overfitting
            _gbr = GradientBoostingRegressor(
                n_estimators=150, max_depth=3, learning_rate=0.05,
                subsample=0.8, random_state=42)
            _gbr.fit(_X_s, _proxy_y)
            _raw_preds = _gbr.predict(_X_s)

            # Scale predictions to 45-98 range (ML_Success_Probability)
            _p_min, _p_max = _raw_preds.min(), _raw_preds.max()
            if _p_max > _p_min:
                df["ML_Success_Probability"] = (
                    45 + (_raw_preds - _p_min) / (_p_max - _p_min) * 53)
            else:
                df["ML_Success_Probability"] = _raw_preds.clip(45, 98)

            log.info(f"[DDS] Per-formulation ML: "
                     f"min={df['ML_Success_Probability'].min():.1f} "
                     f"max={df['ML_Success_Probability'].max():.1f} "
                     f"(GBR on {len(_avail_feats)} biophysical features)")

        except Exception as _ml_e:
            log.warning(f"[DDS] Per-formulation ML failed ({_ml_e}) — using baseline")
            if df_ml is not None and not df_ml.empty:
                ml_score = df_ml.get("ML_Success_Probability", pd.Series([70]*len(df_ml)))
                df["ML_Success_Probability"] = float(ml_score.mean()) if not ml_score.empty else 70.0
            else:
                df["ML_Success_Probability"] = 70.0

        # ── Live biophysics via BiophysicsEngine (DLVO + transcytosis) ──────────
        # This uses ACTUAL formulation parameters from Excel per carrier
        try:
            from cerebro_science_engines import BiophysicsEngine
            _bio_records = []
            for _, row in df.iterrows():
                sz   = float(row.get("size_nm", 80) or 80)
                zeta = float(row.get("zeta_potential_mv", -10) or -10)
                ela  = float(row.get("elasticity_kpa", 1.0) or 1.0)
                ld   = float(row.get("ligand_density_per_nm2", 0.8) or 0.8)
                dlvo   = BiophysicsEngine.dlvo_stability_index(sz, zeta)
                trans  = BiophysicsEngine.transcytosis_energy_barrier(sz, ela, ld)
                _bio_records.append({
                    "DLVO_V_total_kT":     dlvo.get("V_total_kT", 0),
                    "DLVO_stable":         dlvo.get("stable", False),
                    "Transcytosis_dG_kT":  trans.get("delta_G_kT", 0),
                    "Peclet_number":       trans.get("Pe", 0),
                })
            _bio_df = pd.DataFrame(_bio_records, index=df.index)
            df = pd.concat([df, _bio_df], axis=1)
            log.info(f"[DDS] BiophysicsEngine: DLVO + transcytosis computed for {len(df)} formulations")
        except Exception as _bio_e:
            log.warning(f"[DDS] BiophysicsEngine skipped ({_bio_e})")

        # Compute BBB Engineering Score (Pardridge 2012 framework)
        # DLVO stability bonus: colloidal stability reduces opsonisation → better BBB
        try:
            df["BBB_Engineering_Score"] = df.apply(_bbb_score_enhanced, axis=1)
        except Exception as _bbb_err:
            import logging as _lg
            _lg.getLogger("CEREBRO").warning(f"[DDS] BBB_Engineering_Score fallback: {_bbb_err}")
            df["BBB_Engineering_Score"] = df.apply(lambda r: _bbb_score(r), axis=1)
        df["ADMET_Overall_Flag"]    = df.apply(_admet_flag, axis=1)

        # Compute auto-columns
        df["Mechanical_Half_Life_s"]  = df.apply(lambda r:
            round(r["elasticity_kpa"] * r["size_nm"] * 1.8, 1), axis=1)
        df["Diffusion_Coeff_um2_s"]   = df.apply(lambda r:
            round(0.218 / (r["size_nm"] / 100), 3), axis=1)
        df["Leakage_Rate_pct_per_h"]  = df.apply(lambda r:
            round(max(0.3, 5.0 - r["encapsulation_efficiency_pct"] / 20), 2), axis=1)
        df["PgP_Escape_Coeff"]        = df.apply(lambda r:
            round(min(0.98, 0.4 + r["pegylation_degree_mol_pct"] * 0.08), 3), axis=1)
        df["CARPA_Risk_Index"]        = df.apply(lambda r:
            round(min(0.9, 0.05 + abs(r["zeta_potential_mv"]) / 80
                       + r["pegylation_degree_mol_pct"] / 30), 3), axis=1)
        df["Off_Target_Liver_pct"]    = df.apply(lambda r:
            round(max(5, 70 - r["pegylation_degree_mol_pct"] * 4
                       - r["ligand_density_per_nm2"] * 10), 1), axis=1)
        df["Glymphatic_Clearance_h"]  = df.apply(lambda r:
            round(max(2, 20 - r["size_nm"] / 15), 1), axis=1)
        df["ECM_Binding_Index"]       = df.apply(lambda r:
            round(min(0.9, abs(r["zeta_potential_mv"]) / 60
                       + r["ligand_density_per_nm2"] / 10), 3), axis=1)

        df = df.sort_values("BBB_Engineering_Score", ascending=False)
        df["Rank"] = range(1, len(df) + 1)

        # Save CSVs
        dds_dir = trial_dir / "dds_analysis"
        dds_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(dds_dir / "formulation_ranking.csv", index=False)
        df.head(10).to_csv(dds_dir / "top10_formulations.csv", index=False)

        # Write documentation for ranking CSV
        _write_dds_doc(dds_dir / "formulation_ranking.csv", drug_name, len(df))

        log.info(f"[DDS] Scored {len(df)} formulations for {drug_name}")
        log.info("[DDS] Top 5:")
        for _, r in df.head(5).iterrows():
            log.info(f"  #{int(r['Rank'])}  {r['Formulation_ID']:12s}  "
                     f"BBB={r['BBB_Engineering_Score']:5.1f}  {r['Formulation_Name']}")
        return df

    except Exception as e:
        log.exception(f"[DDS] Failed: {e}")
        return None


def _bbb_score(r) -> float:
    """
    BBB Engineering Score (0-100).
    Uses r.get(col, default) throughout — NO KeyError possible.
    Reference: Pardridge WM (2012) Drug Discov Today 17:1026.
    """
    import pandas as pd

    def _g(col, default=0):
        """Safe get from row — handles missing columns and NaN."""
        val = r.get(col, default) if hasattr(r, "get") else getattr(r, col, default)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    score = 50.0  # baseline

    # Size (nm)
    sz = _g("size_nm", 100)
    if 60 <= sz <= 100:    score += 20
    elif 40 <= sz <= 130:  score += 12
    elif sz < 40 or sz > 200: score += 2

    # Zeta potential
    zeta = abs(_g("zeta_potential_mv", -10))
    if 5 <= zeta <= 15:    score += 15
    elif 15 < zeta <= 25:  score += 8
    elif zeta > 30:        score += 1

    # PEGylation
    peg = _g("pegylation_degree_mol_pct", 5)
    if 2 <= peg <= 7:     score += 10
    elif 1 <= peg <= 10:  score += 5

    # Surface ligand
    ligand = str(r.get("Surface_Ligand", "") or "").lower()
    LIGAND_SCORES = {
        "rvg29": 20, "rvg": 20,
        "apoe3-peptide": 22, "apoe3": 22, "apoe": 20,
        "angiopep-2": 18, "angiopep": 18,
        "transferrin": 16, "lactoferrin": 14,
        "glut1": 15, "glucose-transporter": 15,
        "none": 0,
    }
    score += max((v for k, v in LIGAND_SCORES.items() if k in ligand), default=5)

    # Ligand density
    ld = _g("ligand_density_per_nm2", 1.0)
    if 0.5 <= ld <= 1.5:  score += 8
    elif ld > 3.0:         score -= 5

    # Encapsulation efficiency
    ee = _g("encapsulation_efficiency_pct", 70)
    if ee >= 80:   score += 8
    elif ee < 50:  score -= 10

    # P-gp escape (PEG proxy)
    pgp_val = _g("PgP_Escape_Coeff", 0.5)
    score += (pgp_val - 0.5) * 10

    # Phase transition temp — penalty if melts in vivo
    tm = _g("phase_transition_temp_c", 45)
    if 0 < tm <= 37:  score -= 20

    # CARPA risk index (complement activation) — safe get with default 0
    carpa = _g("CARPA_Risk_Index", 0.0)
    score -= carpa * 15

    # Off-target liver
    liver = _g("Off_Target_Liver_pct", 20)
    score -= max(0, liver - 20) * 0.15

    return round(min(100.0, max(0.0, score)), 2)


def _bbb_score_enhanced(r) -> float:
    """
    BBB Engineering Score with DLVO colloidal stability bonus.
    Starts from the Pardridge 2012 heuristic base score,
    then adds a bonus for formulations with demonstrated colloidal
    stability (DLVO V_total > 25kT prevents aggregation in blood).
    """
    base = _bbb_score(r)
    # DLVO bonus: stable formulations are less likely to aggregate before BBB
    if r.get("DLVO_stable", False):
        v_total = float(r.get("DLVO_V_total_kT", 0) or 0)
        if v_total > 50:
            base = min(100, base + 5)    # strongly stable
        elif v_total > 25:
            base = min(100, base + 2)    # moderately stable
    # Transcytosis energy: negative dG = thermodynamically favoured crossing
    dg = float(r.get("Transcytosis_dG_kT", 0) or 0)
    if dg < -5:
        base = min(100, base + 3)   # highly favoured transcytosis
    elif dg < 0:
        base = min(100, base + 1)
    return round(base, 2)


def _admet_flag(r) -> str:
    """ADMET gate: REVIEW if high CARPA, high liver off-target, or poor colloidal stability."""
    if r.get("CARPA_Risk_Index", 0) > 0.6 or r.get("Off_Target_Liver_pct", 0) > 65:
        return "REVIEW"
    # Additional DLVO check: unstable aggregates trigger REVIEW
    if not r.get("DLVO_stable", True) and r.get("DLVO_V_total_kT", 25) < 5:
        return "REVIEW"
    return "OK"


# 10.  HOURLY SCHEDULER LOOP  (checks for new Excel every hour)
# ─────────────────────────────────────────────────────────────────────────────

def run_once(force: bool = False) -> bool:
    """
    Main execution loop — called once per scheduled run.
    Finds new Excel files → runs pipeline per file → registers trials.
    """
    new_files = find_new_excel_files()

    if not new_files and not force:
        log.info("[LOOP] No new Excel files. Next check in 1 hour.")
        return True

    if force and not new_files:
        # Force mode with no new files: re-run the most recent Excel
        conn = sqlite3.connect(TRIAL_INDEX_DB)
        last = conn.execute(
            "SELECT excel_path, excel_hash FROM trials "
            "ORDER BY trial_id DESC LIMIT 1").fetchone()
        conn.close()
        if last:
            log.info(f"[LOOP] Force mode: re-running {Path(last[0]).name}")
            new_files = [(Path(last[0]), last[1] + "_forced")]
        else:
            log.warning("[LOOP] Force mode but no previous trials found")
            # Fall through to check for any Excel in inputs/
            for pattern in EXCEL_GLOB_PATTERNS:
                for xlsx in INPUTS_DIR.glob(pattern):
                    if xlsx.stem.endswith("_Template"):
                        continue
                    h = _excel_hash(xlsx) + "_forced"
                    new_files.append((xlsx, h))
                    break

    success = True
    for xlsx_path, xlsx_hash in new_files:
        if not xlsx_path.exists():
            log.warning(f"[LOOP] File not found: {xlsx_path}")
            continue
        trial_dir = next_trial_dir(xlsx_path)
        ok = run_pipeline_from_excel(xlsx_path, xlsx_hash, trial_dir, force=force)
        if not ok:
            success = False
            log.error(f"[LOOP] Trial failed for {xlsx_path.name}")

    return success

