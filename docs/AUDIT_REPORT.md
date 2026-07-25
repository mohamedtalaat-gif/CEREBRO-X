# CEREBRO-X — Full Engineering & Scientific Integrity Audit

**Date:** 2026-07-25
**Scope:** `/Volumes/Data/CEREBRO-X [Full Engine]/CEREBRO_X` (local "Full Engine" checkout — not the public GitHub repo, which contains only static HTML/PDF demos)
**Method:** Read-only static review (no execution, no network calls, no Docker). ~57,000+ lines across `src/` (33,736 lines) and root-level `cerebro_*.py` files (12,588+ lines) plus supporting config/docs.
**Reviewers:** 4 parallel focused passes (security/API, architecture/dependencies, code-quality/logic/scientific-claims, testing/docs/CI) + orchestrating cross-check.

---

## Executive Summary

CEREBRO-X contains **real, competent engineering in places** (AutoDock Vina docking integration, several correctly-cited QSAR/PK correlations, a genuinely good RBAC/audit-log/circuit-breaker/DAG-orchestration infrastructure layer with real test coverage) sitting alongside **systemic scientific-integrity problems** and **a codebase that has never been run end-to-end as currently configured** (production Docker entrypoint crashes on import; CI pipeline references files that don't exist; three READMEs describe three different architectures).

The single most urgent issue is not a code-quality issue — it is that **specific, falsifiable claims already sent to real professors and companies are not reproducible from this codebase**:
- "75% accuracy on FDA-approved CNS drugs" — no such computation exists anywhere in the code. The nearest metric is a circular pass-through (see §4.6).
- "GNN-based BBB permeability prediction validated against 19,520 Enamine library compounds" — no dataset, no validation run, and the GNN implementation itself has **target leakage** (trains on a feature that is also the label) and fabricated graph structure (identical node features, fully-connected fake topology).
- The repo's own only self-reported validation benchmark (3 drugs) shows **0/3 clean passes** (2 MARGINAL, 1 FAILED→reformulate) — directly undercutting "production-ready" framing used in outreach.

Below is the full 15-section audit as requested.

---

## 1. Architecture Review

**Structure**: `src/` (proper package: `core/`, `api/`, `ml/`, `workers/`, `compliance/`, `viz/`, `monitoring/`, `dds/`) coexists with ~30 loose top-level `cerebro_*.py` files and a separate `cerebro_value_resolver/` package. This is a **partial migration**, held together by `src/path_resolver.py`, which registers ~18 legacy flat names into `sys.modules` at import time so old-style imports keep resolving.

| Category | Examples | Reality |
|---|---|---|
| A. Pure alias, no file on disk | `cerebro_auth`, `cerebro_mlops`, `cerebro_orchestrator`, `cerebro_science_engines`, `cerebro_pbbm_engine` | Only resolve if `path_resolver` ran first |
| B. Root shim forwarding to `src/` | `CEREBRO_Pipeline.py`, `cerebro_pipeline_patches.py`, `cerebro_enterprise_infra.py` | Thin (22–61 line) fallback files |
| C. Genuine flat implementation, never migrated | `cerebro_62_*.py` (5 files), `cerebro_cinematic_*.py`, `cerebro_brand.py`, `cerebro_completed_excel_writer.py`, `cerebro_dds_principle_evaluator.py`, `cerebro_molecule_extractor.py`, etc. | Real code lives only at project root |

**[CRITICAL] Production entrypoint is broken.** `docker-compose.prod.yml` runs `python -m uvicorn src.api.app:app` directly. `src/api/app.py` imports `from cerebro_auth import ...` (and 4 similar flat imports) relying on `path_resolver` having already run — but nothing in the `uvicorn src.api.app:app` import chain (`src/__init__.py`, `src/api/__init__.py`, both checked directly) ever imports `path_resolver`. **This container crashes on first import with `ModuleNotFoundError: No module named 'cerebro_auth'` every time.** It only "works" today because `run.py` (the dev entrypoint) imports `path_resolver` before starting uvicorn in-process — masking the bug in the one path that's actually been exercised.
*Fix:* add `import src.path_resolver` as the first line of `src/api/app.py`, or better, rewrite its imports to proper dotted `from src.api.auth import ...` form and stop relying on the alias registry for internal `src`→`src` imports.

**[HIGH] Duplicated/competing implementations of the same responsibility**, several fully dead:
- `src/core/real_docking_engine.py` vs `src/core/universal_docking_engine.py` — both implement AutoDock Vina docking with near-identical helpers. **Neither is imported anywhere.** The actually-used docking value (`cerebro_62_deep_engine.py`) computes a hardcoded/heuristic `dg_vina` instead of calling either engine.
- `src/core/dds_drug_engine.py` (890 lines) — fully orphaned, zero imports anywhere.
- `cerebro_property_bundles.py` vs `cerebro_resolved_bundles.py` — near-identical "3-layer cache" designs; `property_bundles` is 100% dead (zero external callers), `resolved_bundles` is the one actually wired into `run.py` and all `cerebro_62_*` engines.
- Four independent PBPK implementations exist across the codebase (`science_engines.PBPKEngine` 7-compartment, `pbbm_engine.PBBMEngine` 8-compartment, `science_engines.MultiCompartmentPKEngine` 2-compartment, `quantum_pbpk_engine.py`), with the *same* `Kp = 10^(slope·logP)` structure attributed to *different* citations in different files — evidence the citations are decorative, not derived.

**[HIGH] `run.py` (3,072 lines) is a "god script"**: CLI entrypoint, Excel-to-YAML converter, trial-versioning/hash-cache, pipeline runner, figure/PDF generator, DB layer, autostart/scheduler, and dependency installer (`install_missing()`) all in one file. `cerebro_advanced_modules_2.py` (2,628 lines) and `src/viz/cerebro_html5_engine.py` (2,555 lines) are similarly oversized with low def-density (large average function bodies).

**[MEDIUM] `src/core/pipeline.py` (1,758 lines) mixes 5 distinct responsibilities** (GNN training, `CascadeDataEngine`, `AdvancedMLEngine`, `ADMETEngine`, `AnalyticsEngine`, `ReportingEngine`) that should be separate modules.

**[LOW] Three inconsistent module-resolution mechanisms** (pure alias / shim file / flat file) for what should be one layout — confusing for any future contributor.

*18 files exceed 1,000 lines* — full list in the architecture agent's raw findings; worst offenders by def-density: `cerebro_advanced_modules_2.py`, `src/viz/cerebro_html5_engine.py`.

---

## 2. Dependency Review

**[HIGH] Advertised core features are disabled by default.** `pennylane`, `torch`, `torch-geometric`/`torch-scatter`/`torch-sparse` are all **commented out** in `requirements.txt`/`requirements-ml.txt` as "optional." This means the "quantum PBPK" module and GNN-based knowledge graph/BBB prediction **do not run in a standard `pip install -r requirements.txt`** — they silently fall back (code correctly guards with `_HAS_GNN` flags), but this contradicts marketing language describing them as available capabilities.

**[MEDIUM] `vina` and `meeko` are missing entirely** from both requirements files despite being hard imports in the (dead) docking engines — moot today since those engines are unused, but a landmine if revived.

**[MEDIUM] Version-range drift between `requirements.txt` and `requirements-ml.txt`** for 4 packages (xgboost, shap, rdkit, biopython) — one file caps versions, the other doesn't, so the two can silently diverge over time.
*Fix:* make `requirements-ml.txt` purely additive (`-r requirements.txt` + only genuinely new packages).

No dependency conflicts or circular package dependencies found. Pin ranges otherwise look actively maintained (dated header, real compatibility matrix).

---

## 3. Code Review (dead code, duplication, complexity, patterns)

**[HIGH] Confirmed dead code**, safe to delete:
- `src/core/real_docking_engine.py`, `src/core/universal_docking_engine.py` (or: wire one in and delete the other — see §13)
- `src/core/dds_drug_engine.py` (890 lines)
- `cerebro_property_bundles.py` (400 lines)
- Most of `cerebro_dds_principle_evaluator.py` (923 lines) — only 2 constants (`PRINCIPLE_DOCS`, `PRINCIPLE_WEIGHTS`) are still used; the rest (`evaluate_all_dds`, superseded by the v62 orchestrator per its own in-code comment) is dead.

**[MEDIUM] Duplicated report generators**: `src/core/final_report.py` (864 lines) and `src/core/final_report_unified.py` (1,132 lines) both run on every trial with overlapping section content — any schema change must be applied twice.

**[MEDIUM] Silent runtime package installation**: `science_engines.py`'s `try_install()` shells out to `pip install --break-system-packages` at runtime — not currently wired into a visible path, but a live foot-gun if it is.

**[LOW] Unsourced heuristic constants embedded inside otherwise-real cited models**: e.g. `Vd_L_kg = 0.07 + mw_da/200_000` and `logp_boost = max(0.001, min(0.5, (logp+2)/10))` inside a correctly-cited Rowland & Tozer ODE PK model, undisclosed as heuristic in the function's own `_doc()` output.

**[LOW] Mislabeled algorithm**: `oversample_hits()` is named/documented as SMOTE but is actually simple row duplication + Gaussian noise (no neighbor interpolation).

No race conditions, memory leaks, or concurrency bugs were identified in the reviewed subset (the codebase is largely synchronous/CPU-bound; Celery task queue usage looked conventional). This should not be read as a clean bill of health for concurrency — async/Celery-specific paths were not exhaustively traced.

---

## 4. Logic Validation — Scientific Claims vs. Actual Computation

This is the most consequential section. Files reviewed at high scrutiny: `science_engines.py`, `pbbm_engine.py`, `pipeline.py`, the five `cerebro_62_*.py` engines, plus the previously-reviewed `real_docking_engine.py` (genuinely solid) and `quantum_pbpk_engine.py` (pseudoscience, previously flagged).

### 4.1 [CRITICAL] Fabricated "Monte-Carlo simulation"
`pipeline.py::AnalyticsEngine.simulate_vexosome_encapsulation()`:
```python
"EE_Percent": 85 + np.log(np.linspace(1,20,20))*3 + np.random.normal(0,1,20),
```
A fixed formula plus noise, **disconnected from any actual drug/formulation input**, whose baseline constant (85) appears reverse-engineered to land inside a cited literature range (Kim et al. 2020, 80–95%), then presented as a Monte-Carlo simulation.

### 4.2 [CRITICAL] GNN with target leakage and fabricated molecular graphs
`pipeline.py::GNNEngine._build_graphs()`: every "molecule graph" node gets an **identical** feature vector; edges connect every node to every other node (not real bond topology); node count is `f(molecular weight)`, not atom count. Worse: the training feature set includes the docking/binding affinity column, and the **same value is the training target** — textbook target leakage. Any reported accuracy/loss from this model is meaningless. This is the component most directly relevant to the "GNN-based BBB permeability prediction, validated against 19,520 Enamine library compounds" claim made in outreach emails — **no such validated model exists in this codebase.**

### 4.3 [HIGH] Cited papers don't match implemented method
- `pbbm_engine.py::predict_pka()` — docstring cites Settimo 2014 / Shelley 2007 (real ML pKa papers) and labels itself `"heuristic+ML"`. Actual code: `smiles.count("C(=O)O")` substring counting + a linear formula. **Zero ML present.**
- `pbbm_engine.py::predict_logp_logd()` — docstring claims "ANN ensemble + Moriguchi MlogP." Actual code: real RDKit Crippen LogP, then `MlogP = logP * 0.95 - 0.1` — a linear rescaling, not the real multi-parameter Moriguchi (1992) equation. No ANN exists.
- `cerebro_62_surrogate_engine.py` — multiple lookup tables (e.g. gamma-irradiation sterilization survival by carrier type) attribute precise numbers to a single 1995 paper that could not plausibly cover several carrier classes that postdate common usage in 1995 (nanogel, dendrimer, modern PLGA formulations).

### 4.4 [HIGH] Synthetic ML targets with no ground truth
`pipeline.py::AdvancedMLEngine.train()` — when no real target is supplied, trains an RF/GBR/SVR/XGBoost ensemble against an **arbitrary in-house composite** (`abs(affinity)*0.6 + half_life*0.4`), then reports K-Fold R² against literature benchmark ranges as if it were validated predictive accuracy. It measures how well the ensemble reproduces its own synthetic label — not real-world skill.

### 4.5 [HIGH — scientific framing] The "62-Principle validation framework" is self-invented, not externally validated
`cerebro_62_principles_catalog.py` traces its own source-of-truth to "`/mnt/project/62_Principles.md (project knowledge)`" and "the C+ Flow Muhammad approved on 2026-04-28" — i.e., the author's internal working document, not a regulatory guideline or peer-reviewed framework. The 62 items mix legitimate pharmaceutics concepts with entries like **"Quantum Coherence Transport Model," "BBB Quantum Breaker (Trojan-Horse Design)," "DNA Logic Gates & Bio-computing," "Swarm Nanorobotics Intelligence," "4D Shape-Shifting Carriers,"** each carrying a real citation and a numeric weight, presented with equal formal rigor as the legitimate entries. P04 cites a real quantum-biology paper (Cao et al. 2020, about photosynthesis/enzyme catalysis) to justify whole-molecule quantum tunneling across the BBB — not an accepted pharmacological mechanism. **Recommendation: stop calling this a "framework"; it is CEREBRO-X's internal scoring rubric, and should be labeled as such everywhere it's referenced (README, outreach, reports).**

### 4.6 [CRITICAL] "Deep validation" pass rate is majority circular
`cerebro_62_deep_engine.py`: of 28 Class-B "deep physics" principles, only **7 run genuine independent computation**. The other **21 (75%)** are routed through `_enhanced_surrogate()`, which takes the *same* Class-A heuristic/lookup-table score and re-labels it "deep-validated" if it scores ≥60 — with an in-code comment admitting *"full deep simulation requires external HPC run... targeted for v23."* This is the direct source of the "PASSED (75%)" figures appearing in `CHANGELOG_v22.md` and report narratives. **This is very likely the actual origin of any "75%" figure being cited externally** — and it is not an accuracy metric against ground truth; it's an internal, majority-circular self-consistency check.

### 4.7 [HIGH] No "75% accuracy on FDA-approved CNS drugs" claim exists anywhere in the code
Exhaustive grep across `src/`, all root `cerebro_*.py`, and all `.md`/`.txt` docs for "accuracy," "75%," "FDA-approved CNS" found **zero** instance of this specific claim or any train/test split, confusion matrix, or ROC computation against labeled real-world outcomes. The closest artifact is §4.6's circular pass-rate. **The repo's own only real validation snapshot** (README's 3-drug benchmark: Lecanemab, Temozolomide, Nusinersen) reports **MARGINAL / MARGINAL / FAILED→reformulate** — the opposite of supporting evidence for a 75% accuracy claim.

### 4.8 Positive findings (real, correctly-implemented science)
- `real_docking_engine.py`: genuine AutoDock Vina + RDKit + meeko integration, honest LOW/HIGH confidence labeling, correct references (Trott & Olson 2010, Eberhardt 2021) — currently dead code (§1) but sound if wired in.
- `pbbm_engine.py::predict_permeability/predict_transport/predict_pk_parameters`: real, correctly-cited QSAR correlations (Palm 1997, Clark 2003, Potts-Guy 1992, Seelig 1998, Lobell 2003, Oie-Tozer 1979, Austin 2002) applied as documented.
- `cerebro_62_deep_engine.py`'s 7 genuine deep functions (e.g. allometric scaling, 3-compartment PBPK via `scipy.integrate.odeint`) are reasonably implemented and correctly cited.
- SAEM/PSO-LCI optimizers in `pbbm_engine.py` are legitimate, seeded for reproducibility.
- `cerebro_62_orchestrator.py`'s drug-modality × carrier-type compatibility table is transparent, expert-encoded domain knowledge, honestly presented as a decision table (minor: "FDA-validated table" phrasing overstates it slightly).

---

## 5. Feature Consistency

**[HIGH] Three READMEs describe three different architectures.** `README.md` (v22.1, "C+ Flow," `cerebro_62_*.py` files) vs `README_RESEARCHER.md`/`README_DEVELOPER.md` (v13, `CEREBRO_WORK_V10/`, different module split, `run.py` cited as "3,935 lines" vs actual 3,072). A reader moving between them would reasonably conclude they're different products.

**[MEDIUM] "Production-ready" claim directly contradicted by the document's own evidence directly beneath it** (3-drug benchmark: 2 MARGINAL + 1 FAILED).

**[MEDIUM] README_RESEARCHER.md references files/paths that don't exist in this checkout** (`CEREBRO_Input_FINAL_Template.xlsx`, `CEREBRO_WORK_V10/` directory) — would confuse a new user following it literally.

**[LOW] "62-Principle" module counts are described inconsistently** across the three READMEs (57+7+7 vs 10+40+novel-drug split).

No backward-compatibility framework exists (no version negotiation for the API, no data-migration path — see §8) — reasonable for a pre-1.0 research tool, but inconsistent with "production-ready"/"enterprise" framing used externally.

---

## 6. Security Audit

### Critical
- **Unauthenticated privilege escalation via `/auth/register`** (`src/api/app.py:296-303`, `src/api/auth.py:246-251,347-367`): `role` is a free-text field accepted from an anonymous POST body with zero server-side restriction. Any caller can register as `role: "admin"`. The docstring even says *"Admin-only in production"* — nothing enforces it.
- **Production entrypoint crashes on boot** — see §1 (`ModuleNotFoundError: cerebro_auth`), functionally a Critical availability/security issue since it means the "production" deployment path has never run.
- **Hardcoded/weak default credentials in version-controlled files**: `admin_pw` fallback `"cerebro_admin_2024"` (`auth.py:663`); `POSTGRES_PASSWORD: cerebro_secure_2024` hardcoded (not overridable) in `docker-compose.yml`; multiple `:-change_me...` defaults in `docker-compose.prod.yml` that will silently be used if unset.

### High
- **JWT secret is random-per-process when unset** (`auth.py:91`), breaking multi-worker auth (prod runs `--workers 2`) — tokens intermittently fail cross-worker, and every restart invalidates all sessions.
- **DB init and Prometheus config silently skipped**: `docker-compose.prod.yml` bind-mounts `./configs/init.sql` and `./monitoring/prometheus.yml` — actual paths are `config/init.sql` and `monitoring_config/prometheus.yml`. Postgres schema bootstrap never runs. Hard evidence the "prod" compose file was never actually executed.
- **Permissive CORS + credentials by default**: `allow_origins="*"` + `allow_credentials=True` + `allow_methods/headers="*"`, and `.env.example`/`docker-compose.prod.yml` both default `CORS_ORIGINS=*`.
- **Audit trail hash-chain has no secret key (not HMAC)** — anyone with DB write access can forge valid-looking chained hashes, undercutting the file's own claimed tamper-detection guarantee.
- **"Encryption" is a silent no-op when `ENCRYPTION_KEY` is unset** — returns plaintext unchanged, logs only a warning; nothing fails closed.

### Medium
- **`pdb_id` insufficiently validated** (length-only check) before use in both a download URL and a local filesystem path — real path-traversal gap, SSRF blast radius limited by hardcoded host.
- **No in-application rate limiting** — only exists in `nginx.conf`, which the simpler `docker-compose.yml` (the one most likely to be run first) never uses; `/auth/login`/`/auth/register` are unthrottled in that config.
- **Dead auth code with landmine defaults**: an unused second `get_current_user`/`auth_router` with `db: Session = None` typed defaults — would NPE immediately if ever wired in by a future edit.
- **Weak-hash password fallback** (plain `sha256(salt+password)`, no work factor) if `passlib` isn't installed — degrades silently, just a warning log.

### Low
- `.env` file permissions are world/group-readable (644) — recommend `chmod 600`.
- Raw exception text leaked to callers in several 500 responses.
- Redundant, inconsistently-styled authorization double-checks (decorator + manual re-check) in several handlers — sign of unreconciled patches across sessions.

### REST API design
No versioning (`/v1` prefix absent despite `version="2.0.0"` in app metadata); RPC-style verb-in-path naming rather than resource-oriented; inconsistent/absent pagination on list endpoints; no idempotency keys (retried pipeline-run POSTs double-submit expensive jobs); mixed error contracts (some `HTTPException`, some `200` with embedded `{"status":"error"}`); `/docs`/`/redoc`/`/openapi.json` public by default. Bright spot: `/healthz`/`/readyz`/`/health/deep` split follows k8s conventions correctly.

---

## 7. Performance Audit

Not executed under load (out of scope for a static review), but structurally notable:
- `run.py`'s dependency-install-at-runtime pattern (`install_missing()`) and `try_install()` in `science_engines.py` are blocking, network-dependent operations that could stall pipeline runs unpredictably.
- No caching layer is used for the (currently non-functional) production DB init or for repeated RCSB PDB downloads beyond simple file-existence checks in `real_docking_engine.py` (itself dead code).
- `src/ml/cache.py` (LRU + SQLite backing) is real and tested — a genuine positive for the infrastructure layer.
- The GNN complete-graph construction in `pipeline.py` (§4.2) is O(n²) edges for no scientific benefit — wasted computation even setting aside the correctness issues.
- No profiling/benchmark artifacts exist to substantiate the README's "Full pipeline ~140s" performance table.

---

## 8. Database Review

- SQLAlchemy models exist (`src/api/auth.py`), Postgres targeted in production, but **zero migration tooling** — no `alembic/` directory, no migration scripts found anywhere (`find` confirmed). Schema is `create_all()`'d directly (seen in `conftest.py`). **[MEDIUM-HIGH]** any future schema change on a running instance has no managed upgrade path.
- `config/init.sql` (schema DDL) is never actually mounted in the working `docker-compose.prod.yml` due to the path mismatch noted in §6 — so even the DDL that exists doesn't currently run.
- No query-optimization or indexing review was possible without a running DB; `config/init.sql` was noted as containing DDL only, not reviewed line-by-line for indexing strategy in this pass.

---

## 9. API Review

Covered in §6 (REST API design subsection). Summary: functional FastAPI app with real RBAC/JWT/API-key auth and a well-designed health-check surface, but not currently REST-conventional, unversioned, missing pagination/idempotency, and — critically — cannot currently boot via its documented production entrypoint (§1, §6).

---

## 10. Frontend Review

**Not applicable in the traditional sense** — CEREBRO-X has no JS/React/Vue frontend. User-facing output is generated HTML reports (`src/viz/cerebro_html5_engine.py`, 2,555 lines; `cerebro_cinematic_engine.py`, 1,451 lines) and PDF/Excel artifacts. These were not deep-reviewed for accessibility/responsiveness in this pass (out of the agents' assigned scope) — flagged as a gap in this audit's coverage, not a clean bill of health. If these HTML reports are shared externally (as the GitHub repo's interactive demos already are), they should get the same "does the presentation honestly reflect the underlying computation" scrutiny applied in §4.

---

## 11. Testing Review

**Coverage: well under 5% of the functional/scientific surface.** 44 total test functions (39 unit + 5 integration) exercise exactly 5-6 infrastructure modules (`auth.py`, `mlops.py`, `cache.py`, `orchestrator.py`, `privacy.py`, one function in `enterprise_infra.py`) — genuinely good, non-tautological tests, but **zero coverage of any file in `src/core/`** (the actual scientific engines: docking, QSAR, PBPK, pipeline, molecule engine) and **zero coverage of any `cerebro_62_*.py` engine** — i.e., the entire scoring system that produces every headline number has no automated test at all.

`phase5_smoke_test.py` has **zero `assert` statements** — it only checks that modules import and the orchestrator runs without throwing, never that outputs are correct. This is precisely why the issues in §4 (target leakage, fabricated Monte Carlo, mislabeled methods) exist undetected — nothing in the test suite touches those code paths.

**Testing roadmap (P0 → P2):**
- P0: unit tests for `real_docking_engine.py`/`real_qsar_engine.py`/`pbbm_engine.py` (mass-balance/regression checks); an actual end-to-end integration test of `run.py` on synthetic input asserting real output artifacts exist.
- P1: unit tests for `cerebro_value_resolver/` (the most-marketed "7-tier provenance" component, currently untested), the `cerebro_62_*` engines, adversarial/negative auth tests, a regression test for the CHANGELOG_v19 Excel-parser bug.
- P2: golden-file tests for Excel/PDF report generation, HTML report smoke tests, audit-trail tamper-detection tests, full Docker-Compose E2E smoke test in CI.

---

## 12. Documentation Review

Covered in depth in §5. Summary of the sharpest issues: three mutually-inconsistent READMEs; a "production-ready" claim contradicted by the document's own validation table; a quantum-PBPK feature advertised as available while its dependency is commented out in requirements; a citation URL (`github.com/cerebro-x/cerebro-x`) that doesn't correspond to any git history in this checkout; `.env.example` is well-commented internally but never referenced by any README's quick-start instructions, so new users following the docs literally will run on default/placeholder secrets. `QUICK_START_PROFESSIONAL.md` and `DEPLOYMENT_GUIDE.md`, if referenced elsewhere, do not exist in this tree at all.

---

## 13. Refactoring Plan — Prioritized Roadmap

### Critical (block any external claims until resolved)
| Issue | Impact | Risk | Recommended solution | Effort |
|---|---|---|---|---|
| Production entrypoint crashes on import | App cannot run as documented | Reputational (anyone testing the "production" path fails immediately) | Add `import src.path_resolver` to `src/api/app.py`, or convert to dotted imports | 1-2 hrs |
| `/auth/register` privilege escalation | Any user can self-grant admin | Full auth bypass | Strip `role` from public payload; force `READONLY` default server-side | 1 hr |
| GNN target leakage + fake graphs | Any GNN-derived claim is invalid | Direct exposure risk given it's already cited in outreach to professors | Either rebuild with real molecular graphs (RDKit bond graph) and leakage-free features, or remove the GNN claim from all outreach/docs until rebuilt | 1-2 weeks (rebuild) / 1 hr (remove claim) |
| Fabricated Monte-Carlo output | Invalidates any DDS/encapsulation report number | Scientific-integrity/reputational | Replace with a real stochastic model tied to actual formulation parameters, or remove the "Monte-Carlo" framing and mark as illustrative placeholder | 3-5 days |
| "75%/deep-validation" circularity | Headline metric is majority self-referential | Directly relevant to any accuracy claim made externally | Either implement real independent Class-B computation for the 21 deferred principles (large effort, matches the code's own "v23" plan), or clearly relabel current output as "surrogate-consistency check," not "deep validation" | Relabel: 1 day / Real implementation: months |
| Hardcoded default secrets (admin password, Postgres password, JWT fallback) | Full compromise if defaults ever reach a real deployment | High | Fail-hard at startup if any of these equal known defaults or are unset | 1 day |

### High
- Delete or wire in the 4 confirmed-dead modules (`real_docking_engine.py`/`universal_docking_engine.py` — pick one; `dds_drug_engine.py`; `cerebro_property_bundles.py`). *2-3 days.*
- Reconcile the two "deep physics"/PBPK families into one, with one set of citations. *1-2 weeks.*
- Fix `docker-compose.prod.yml` path mismatches (`configs/init.sql`→`config/init.sql`, `monitoring/`→`monitoring_config/`) so DB schema and Prometheus actually initialize. *2 hrs.*
- Fix CI: `Dockerfile.api` doesn't exist (build job fails), mypy targets 3 nonexistent files (silently masked by `continue-on-error`), `--timeout=120` likely missing its plugin dependency. *1 day.*
- Rewrite `cerebro_62_principles_catalog.py`'s external framing from "framework" to "internal scoring rubric" everywhere it appears (README, outreach materials, reports). *1 day of writing, needs author sign-off on tone.*
- Reconcile the three READMEs into one accurate current-state document; archive the v13 docs explicitly as historical. *2-3 days.*
- Split `run.py` (3,072 lines) into CLI + trial-manager + report-orchestrator + installer modules. *1 week.*

### Medium
- Add `alembic` migrations for the Postgres schema. *2-3 days.*
- Fix CORS defaults (no wildcard + credentials in any shipped config). *2 hrs.*
- HMAC the audit-trail hash chain with a key not stored in the same DB. *1 day.*
- Fail closed (don't silently no-op) when `ENCRYPTION_KEY` is unset, if any field is genuinely relied upon to be encrypted. *1 day.*
- Validate `pdb_id` with a strict `[A-Za-z0-9]{4}` regex before filesystem/URL use. *1 hr.*
- Add rate limiting at the application layer (not just nginx, which isn't used in the simpler compose file). *1-2 days.*
- Deduplicate `requirements.txt`/`requirements-ml.txt` version ranges (`-r requirements.txt` include). *1 hr.*
- Add tests for `cerebro_value_resolver/` and the `cerebro_62_*` engines. *1-2 weeks.*

### Low
- `chmod 600 .env`; stop echoing raw exception text to API callers; remove dead/duplicate auth-router code; register and actually use the `slow`/`integration` pytest markers; scope `--cov` to `src/` only.

---

## 14. Final Cleanup

**Remove:**
- `cerebro_property_bundles.py`, `src/core/dds_drug_engine.py` (fully dead)
- One of `real_docking_engine.py` / `universal_docking_engine.py` (after picking + wiring the survivor)
- Dead unused `auth_router`/`get_current_user` block in `src/api/auth.py`
- The "Monte-Carlo" label on `simulate_vexosome_encapsulation()` until it's genuinely input-driven

**Simplify:**
- `run.py` → split into 4 focused modules
- Merge `final_report.py` + `final_report_unified.py` into one generator with a detail-level flag
- Collapse 4 parallel PBPK implementations into 1

**Merge:**
- `requirements.txt` + `requirements-ml.txt` → base + additive-only ML file
- Three READMEs → one current-state doc + one archived historical doc

**Rename:**
- "62-Principle validation framework" → "CEREBRO-X internal 62-criterion scoring rubric" (everywhere, including outreach)
- "Deep validation PASSED (75%)" → something that doesn't imply independent physics for the 21/28 pass-through principles until that's actually true

**Reorganize:**
- Finish the `src/` migration (move all category-C flat files into `src/`) and retire the alias system, or explicitly commit to and document the hybrid pattern — not leave it two-thirds done.

---

## 15. Final Verification

**Would I confidently approve this codebase for production at a large technology company?**

**No.**

Reasons this fails a production bar today, independent of the scientific-integrity issues:
1. The documented production entrypoint does not boot (§1, §6).
2. Unauthenticated privilege escalation exists in the auth system (§6).
3. The CI pipeline has never successfully run end-to-end and currently contains 3 concrete breakages (§2 of the testing report: missing `Dockerfile.api`, mypy targeting deleted files, likely-missing pytest plugin).
4. Core documentation (3 READMEs) is internally contradictory about what the current architecture even is.
5. Test coverage of the actual product logic (the scientific engines) is effectively zero; the one smoke test that exists asserts nothing about correctness.
6. There is no version control at all (`no .git`) — nothing here has been through review, branching, or a PR process, which is itself disqualifying for a "production" claim regardless of code quality.

Beyond the engineering bar, there is a **scientific-integrity bar that also fails**, and this is the part most urgent for the user specifically because of active academic/industry outreach already in flight: the GNN and "19,520 Enamine compound validation" claims made to real professors are not reproducible from this code (target leakage, fabricated graphs, no dataset present locally); the "75% accuracy" figure traces to a majority-circular internal metric, not ground-truth validation; and the formal "62-Principle" catalog embeds physically unfounded mechanisms (whole-molecule quantum tunneling) as a weighted, equal-standing component alongside legitimate pharmaceutics principles.

**What's genuinely salvageable and worth keeping:** the AutoDock Vina integration, several correctly-cited QSAR/PK correlations, the RBAC/audit/circuit-breaker/DAG infrastructure layer (well-tested), the health-check design, and the honest confidence-labeling pattern (`LOW`/`HIGH`, `_failed()` on exception) used inconsistently but well where it appears. These are a legitimate foundation. The path forward is not "start over" — it's: stop external claims that outrun the code, fix the entrypoint/auth/CI breakages, delete or clearly quarantine the pseudoscience and circular-metric components, and build real test coverage on the scientific core before making any further "validated"/"production-ready" statements to third parties.
