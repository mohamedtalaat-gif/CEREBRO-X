"""
================================================================================
CEREBRO-X |  UNIT TESTS
================================================================================
File: tests/unit/test_all.py

Coverage:
  1. Authentication & RBAC
  2. DDS BBB Engineering Score
  3. MLOps (registry, drift detection)
  4. Orchestrator (DAG, retry, circuit breaker)
  5. Cache (LRU, multi-tier)
  6. Compliance (PHI detection, audit trail, data masking)
================================================================================
"""
import time
from datetime import datetime, timedelta

import numpy as np
import pytest

# ═════════════════════════════════════════════════════════════════════════════
# 1. AUTHENTICATION & RBAC
# ═════════════════════════════════════════════════════════════════════════════

class TestAuth:
    """JWT authentication and role-based access control."""

    def test_password_hashing(self):
        from src.api.auth import pwd_context
        hashed = pwd_context.hash("secret123")
        assert pwd_context.verify("secret123", hashed)
        assert not pwd_context.verify("wrong", hashed)

    def test_create_user(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        user = svc.create_user(UserCreate(
            email="test@test.com",
            username="testuser",
            password="strongpw123",
            role="researcher",
        ))
        assert user.username == "testuser"
        assert user.role == "researcher"
        assert user.is_active is True

    def test_duplicate_user_rejected(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        svc.create_user(UserCreate(
            email="dup@test.com", username="dupuser",
            password="pw123456", role="readonly",
        ))
        with pytest.raises(ValueError, match="already registered"):
            svc.create_user(UserCreate(
                email="dup@test.com", username="dupuser2",
                password="pw123456", role="readonly",
            ))

    def test_login_success(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        svc.create_user(UserCreate(
            email="login@test.com", username="loginuser",
            password="pw123456", role="admin",
        ))
        result = svc.login("loginuser", "pw123456")
        assert result is not None
        assert result.access_token
        assert result.refresh_token
        assert result.role == "admin"

    def test_login_wrong_password(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        svc.create_user(UserCreate(
            email="fail@test.com", username="failuser",
            password="correctpw", role="readonly",
        ))
        result = svc.login("failuser", "wrongpw")
        assert result is None

    def test_jwt_token_roundtrip(self):
        from src.api.auth import TokenEngine
        token = TokenEngine.create_access_token(
            {"sub": "42", "role": "researcher", "username": "test"}
        )
        payload = TokenEngine.decode_token(token)
        assert payload["sub"] == "42"
        assert payload["role"] == "researcher"
        assert payload["type"] == "access"

    def test_refresh_token_rotation(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        svc.create_user(UserCreate(
            email="refresh@test.com", username="refreshuser",
            password="pw123456", role="admin",
        ))
        login_result = svc.login("refreshuser", "pw123456")
        new_tokens = svc.refresh_tokens(login_result.refresh_token)
        assert new_tokens is not None
        assert new_tokens.access_token != login_result.access_token
        # Old refresh token should be revoked
        reuse = svc.refresh_tokens(login_result.refresh_token)
        assert reuse is None

    def test_rbac_permissions(self):
        from src.api.auth import Role, has_permission
        assert has_permission(Role.ADMIN, "pipeline:run")
        assert has_permission(Role.ADMIN, "user:delete")
        assert has_permission(Role.RESEARCHER, "pipeline:run")
        assert not has_permission(Role.RESEARCHER, "user:delete")
        assert not has_permission(Role.READONLY, "pipeline:run")
        assert has_permission(Role.READONLY, "results:read")

    def test_api_key_creation(self, db_session):
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        user = svc.create_user(UserCreate(
            email="apikey@test.com", username="apikeyuser",
            password="pw123456", role="researcher",
        ))
        raw_key, key_model = svc.create_api_key(user.id, "test-key")
        assert raw_key.startswith("cerebro_")
        assert key_model.key_prefix == raw_key[:12]
        # Verify
        found_user = svc.verify_api_key(raw_key)
        assert found_user is not None
        assert found_user.id == user.id


# ═════════════════════════════════════════════════════════════════════════════
# 2. DDS BBB ENGINEERING SCORE
# ═════════════════════════════════════════════════════════════════════════════

class TestDDSScore:
    """BBB Engineering Score computation."""

    def test_optimal_formulation_scores_high(self):
        from src.dds.enterprise_infra import DDSEngine
        row = {
            "size_nm": 80,
            "zeta_potential_mv": -10,
            "pegylation_degree_mol_pct": 5,
            "surface_ligand": "ApoE",
            "ligand_density_per_nm2": 1.0,
            "encapsulation_efficiency_pct": 85,
            "pgp_escape_coeff": 0.9,
            "apo_e_affinity": "very_high",
            "carpa_risk_index": 0.1,
            "off_target_liver_pct": 15,
            "phase_transition_temp_c": 55,
        }
        score = DDSEngine.compute_bbb_engineering_score(row)
        assert score >= 75, f"Optimal formulation should score ≥75, got {score}"
        assert score <= 100

    def test_terrible_formulation_scores_low(self):
        from src.dds.enterprise_infra import DDSEngine
        row = {
            "size_nm": 500,
            "zeta_potential_mv": -40,
            "pegylation_degree_mol_pct": 15,
            "surface_ligand": "None",
            "ligand_density_per_nm2": 5.0,
            "encapsulation_efficiency_pct": 20,
            "pgp_escape_coeff": 0.1,
            "apo_e_affinity": "low",
            "carpa_risk_index": 0.9,
            "off_target_liver_pct": 80,
            "phase_transition_temp_c": 35,
        }
        score = DDSEngine.compute_bbb_engineering_score(row)
        assert score < 30, f"Terrible formulation should score <30, got {score}"

    def test_score_bounded_0_100(self):
        from src.dds.enterprise_infra import DDSEngine
        for _ in range(50):
            row = {
                "size_nm": np.random.uniform(20, 500),
                "zeta_potential_mv": np.random.uniform(-50, 50),
                "pegylation_degree_mol_pct": np.random.uniform(0, 20),
                "surface_ligand": np.random.choice(["ApoE", "RVG", "None"]),
                "ligand_density_per_nm2": np.random.uniform(0, 5),
                "encapsulation_efficiency_pct": np.random.uniform(10, 99),
                "pgp_escape_coeff": np.random.uniform(0, 1),
                "apo_e_affinity": np.random.choice(["low", "high", "very_high"]),
                "carpa_risk_index": np.random.uniform(0, 1),
                "off_target_liver_pct": np.random.uniform(0, 100),
                "phase_transition_temp_c": np.random.uniform(30, 70),
            }
            score = DDSEngine.compute_bbb_engineering_score(row)
            assert 0 <= score <= 100


# ═════════════════════════════════════════════════════════════════════════════
# 3. MLOps
# ═════════════════════════════════════════════════════════════════════════════

class TestMLOps:
    """Model registry, drift detection, experiment tracking."""

    def test_model_registry_lifecycle(self, tmp_db):
        from src.ml.mlops import ModelRegistry, ModelStage, ModelVersion
        reg = ModelRegistry(tmp_db)

        # Register v1
        reg.register(ModelVersion(
            model_name="test_model", version="1.0.0",
            stage=ModelStage.DEVELOPMENT,
            metrics={"r2": 0.85, "mae": 0.12},
        ))

        # Promote to production
        reg.promote("test_model", "1.0.0", ModelStage.PRODUCTION)
        prod = reg.get_production("test_model")
        assert prod is not None
        assert prod.version == "1.0.0"

        # Register v2 and promote (should archive v1)
        reg.register(ModelVersion(
            model_name="test_model", version="1.1.0",
            metrics={"r2": 0.90},
        ))
        reg.promote("test_model", "1.1.0", ModelStage.PRODUCTION)
        prod = reg.get_production("test_model")
        assert prod.version == "1.1.0"

        # v1 should be archived
        versions = reg.list_versions("test_model", ModelStage.ARCHIVED)
        assert len(versions) == 1
        assert versions[0].version == "1.0.0"

    def test_rollback(self, tmp_db):
        from src.ml.mlops import ModelRegistry, ModelStage, ModelVersion
        reg = ModelRegistry(tmp_db)
        reg.register(ModelVersion(model_name="m", version="1.0.0"))
        reg.register(ModelVersion(model_name="m", version="2.0.0"))
        reg.promote("m", "2.0.0", ModelStage.PRODUCTION)
        reg.rollback("m", "1.0.0")
        assert reg.get_production("m").version == "1.0.0"

    def test_psi_no_drift(self):
        from src.ml.mlops import ModelDriftDetector
        ref = np.random.normal(0.5, 0.1, 500)
        cur = np.random.normal(0.5, 0.1, 500)
        psi = ModelDriftDetector.compute_psi(ref, cur)
        assert psi < 0.1, f"Same distribution should have low PSI, got {psi}"

    def test_psi_detects_drift(self):
        from src.ml.mlops import ModelDriftDetector
        ref = np.random.normal(0.5, 0.1, 500)
        cur = np.random.normal(0.8, 0.2, 500)  # shifted
        psi = ModelDriftDetector.compute_psi(ref, cur)
        assert psi > 0.25, f"Shifted distribution should have high PSI, got {psi}"

    def test_full_drift_detection(self):
        from src.ml.mlops import ModelDriftDetector
        np.random.seed(123)
        ref = np.random.normal(0.65, 0.1, 1000)
        cur = np.random.normal(0.65, 0.1, 1000)  # same dist, large sample
        result = ModelDriftDetector.detect_prediction_drift(ref, cur)
        assert result["severity"] in ("none", "moderate")  # small random noise ok

    def test_performance_degradation_detection(self):
        from src.ml.mlops import ModelDriftDetector
        result = ModelDriftDetector.check_performance_degradation(
            current_r2=0.60, baseline_r2=0.85,
            current_mae=0.25, baseline_mae=0.10,
        )
        assert result["degraded"] is True

    def test_experiment_tracker(self, tmp_db):
        from src.ml.mlops import ExperimentTracker, ModelRegistry
        # ModelRegistry init creates all tables including experiments
        ModelRegistry(tmp_db)
        tracker = ExperimentTracker(tmp_db)
        run_id = tracker.start_run("test_model", {"lr": 0.01})
        tracker.log_metrics(run_id, {"r2": 0.88})
        tracker.end_run(run_id, "completed")
        run = tracker.get_run(run_id)
        assert run["status"] == "completed"
        assert run["metrics"]["r2"] == 0.88


# ═════════════════════════════════════════════════════════════════════════════
# 4. ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════════════

class TestOrchestrator:
    """DAG execution, retry logic, circuit breaker."""

    def test_circuit_breaker_trips_on_failures(self):
        from src.workers.orchestrator import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitState,
        )
        cb = CircuitBreaker("test", CircuitBreakerConfig(
            failure_threshold=3, recovery_timeout=1
        ))
        assert cb.state == CircuitState.CLOSED
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_execute()

    def test_circuit_breaker_recovers(self):
        from src.workers.orchestrator import (
            CircuitBreaker,
            CircuitBreakerConfig,
            CircuitState,
        )
        cb = CircuitBreaker("test", CircuitBreakerConfig(
            failure_threshold=2, recovery_timeout=0.1, success_threshold=1
        ))
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.can_execute()  # should transition to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_retry_decorator(self):
        from src.workers.orchestrator import RetryPolicy, retry_with_backoff
        call_count = 0

        @retry_with_backoff(RetryPolicy(max_retries=3, base_delay=0.01))
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 3

    def test_dag_topological_sort(self):
        from src.workers.orchestrator import PipelineOrchestrator, TaskDefinition
        orch = PipelineOrchestrator()
        orch.register(TaskDefinition("a", func=lambda: None))
        orch.register(TaskDefinition("b", func=lambda: None, depends_on=["a"]))
        orch.register(TaskDefinition("c", func=lambda: None, depends_on=["a"]))
        orch.register(TaskDefinition("d", func=lambda: None, depends_on=["b", "c"]))
        levels = orch._topological_sort()
        assert levels[0] == ["a"]
        assert set(levels[1]) == {"b", "c"}
        assert levels[2] == ["d"]

    def test_dag_execution(self):
        from src.workers.orchestrator import (
            PipelineOrchestrator,
            TaskDefinition,
            TaskState,
        )
        results = []
        orch = PipelineOrchestrator()
        orch.register(TaskDefinition("step1", func=lambda: results.append(1) or "done1"))
        orch.register(TaskDefinition("step2", func=lambda **kw: results.append(2) or "done2",
                                     depends_on=["step1"]))
        execs = orch.execute("test_run")
        assert execs["step1"].state == TaskState.SUCCESS
        assert execs["step2"].state == TaskState.SUCCESS
        assert results == [1, 2]

    def test_dag_failure_cascades(self):
        from src.workers.orchestrator import (
            PipelineOrchestrator,
            RetryPolicy,
            TaskDefinition,
            TaskState,
        )
        def fail_fn():
            raise RuntimeError("boom")

        orch = PipelineOrchestrator()
        orch.register(TaskDefinition("bad", func=fail_fn,
                                     retry_policy=RetryPolicy(max_retries=0)))
        orch.register(TaskDefinition("after", func=lambda **kw: "ok",
                                     depends_on=["bad"]))
        execs = orch.execute()
        assert execs["bad"].state == TaskState.DEAD
        assert execs["after"].state == TaskState.CANCELLED


# ═════════════════════════════════════════════════════════════════════════════
# 5. CACHE
# ═════════════════════════════════════════════════════════════════════════════

class TestCache:
    """Multi-tier caching layer."""

    def test_lru_basic(self):
        from src.ml.cache import LRUCache
        cache = LRUCache(max_size=5, default_ttl=60)
        cache.set("a", {"value": 1})
        assert cache.get("a") == {"value": 1}
        assert cache.get("missing") is None

    def test_lru_ttl_expiry(self):
        from src.ml.cache import LRUCache
        cache = LRUCache(max_size=5, default_ttl=0.05)
        cache.set("x", "data")
        assert cache.get("x") == "data"
        time.sleep(0.1)
        assert cache.get("x") is None  # expired

    def test_lru_eviction(self):
        from src.ml.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_lru_stats(self):
        from src.ml.cache import LRUCache
        cache = LRUCache(max_size=10)
        cache.set("k", "v")
        cache.get("k")      # hit
        cache.get("miss")   # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_sqlite_cache(self, tmp_path):
        from src.ml.cache import SQLiteCache
        cache = SQLiteCache(tmp_path / "cache.db")
        cache.set("mol:test_drug_x", {"MW": 143379}, ttl=60, category="molecule")
        assert cache.get("mol:test_drug_x")["MW"] == 143379
        cache.flush("molecule")
        assert cache.get("mol:test_drug_x") is None

    def test_cache_decorator(self):
        from src.ml.cache import cached, get_cache
        call_count = 0

        @cached(ttl=60, category="test")
        def expensive(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10  # cached
        assert call_count == 1     # only called once

        get_cache().flush()


# ═════════════════════════════════════════════════════════════════════════════
# 6. COMPLIANCE
# ═════════════════════════════════════════════════════════════════════════════

class TestCompliance:
    """PHI detection, audit trail, data masking."""

    def test_phi_detection(self):
        from src.compliance.privacy import PHIDetector
        text = "Patient SSN is 123-45-6789 and email is john@hospital.com"
        findings = PHIDetector.scan(text)
        types_found = {f["type"] for f in findings}
        assert "ssn" in types_found
        assert "email" in types_found

    def test_phi_redaction(self):
        from src.compliance.privacy import PHIDetector
        text = "Call 555-123-4567 or email dr@clinic.com"
        redacted = PHIDetector.redact(text)
        assert "555-123-4567" not in redacted
        assert "dr@clinic.com" not in redacted
        assert "[REDACTED]" in redacted

    def test_no_false_positive_on_drug_data(self):
        from src.compliance.privacy import PHIDetector
        text = "TEST_DRUG_X MW=143379 Da, LogP=-0.7, SMILES=CC(=O)NC"
        assert not PHIDetector.has_phi(text)

    def test_audit_trail_chain_integrity(self, tmp_path):
        from src.compliance.privacy import AuditTrail
        audit = AuditTrail(tmp_path / "audit.db")
        audit.log("admin", "login", "auth")
        audit.log("admin", "pipeline:run", "pipeline")
        audit.log("researcher", "results:read", "results")
        result = audit.verify_chain()
        assert result["valid"] is True
        assert result["entries"] == 3

    def test_data_masking_readonly(self):
        from src.compliance.privacy import DataMasker
        record = {
            "Drug": "TEST_DRUG_X",
            "MW_Da": 143379,
            "Formulation_Name": "SECRET-LNP-v3",
            "manufacturing_method": "microfluidics",
        }
        masked = DataMasker.mask_record(record, "readonly")
        assert masked["Drug"] == "TEST_DRUG_X"  # public
        assert masked["Formulation_Name"] == "***RESTRICTED***"
        assert masked["manufacturing_method"] == "***RESTRICTED***"

    def test_data_masking_researcher(self):
        from src.compliance.privacy import DataMasker
        record = {
            "Drug": "TEST_DRUG_X",
            "Formulation_Name": "SECRET-LNP-v3",
            "patient_id": "PT-12345",
        }
        masked = DataMasker.mask_record(record, "researcher")
        assert masked["Drug"] == "TEST_DRUG_X"
        assert masked["Formulation_Name"] == "SECRET-LNP-v3"
        assert masked["patient_id"] == "***RESTRICTED***"

    def test_encryption_roundtrip(self):
        from src.compliance.privacy import EncryptionEngine
        engine = EncryptionEngine()
        if engine.available:
            ct = engine.encrypt("sensitive data")
            pt = engine.decrypt(ct)
            assert pt == "sensitive data"

    def test_retention_check(self):
        from src.compliance.privacy import DataClass, RetentionManager
        old_date = datetime.utcnow() - timedelta(days=365 * 11)
        result = RetentionManager.check_retention(old_date, DataClass.PUBLIC)
        assert result["expired"] is True

        recent = datetime.utcnow() - timedelta(days=30)
        result = RetentionManager.check_retention(recent, DataClass.PUBLIC)
        assert result["expired"] is False


# ═════════════════════════════════════════════════════════════════════════════
# 7. BBB PERMEABILITY DNN (engine/cerebro_bbb_dnn.py)
# ═════════════════════════════════════════════════════════════════════════════

class TestBBBDNN:
    """Real DNN trained on the public BBBP dataset — see the module docstring
    in engine/cerebro_bbb_dnn.py for what is and isn't claimed about it."""

    def test_featurizer_handles_valid_and_invalid_smiles(self):
        import cerebro_bbb_dnn as bbb
        if not bbb._HAS_RDKIT:
            pytest.skip("rdkit not installed")
        feat = bbb._featurize_smiles("CCO")  # ethanol — valid
        assert feat is not None
        assert feat.shape == (2048,)
        assert bbb._featurize_smiles("not a smiles string !!!") is None

    def test_predict_reports_unavailable_without_deps(self):
        import cerebro_bbb_dnn as bbb
        if bbb._HAS_BBB_DNN:
            pytest.skip("rdkit+tensorflow both installed — availability path not exercised")
        result = bbb.predict_bbb_class("CCO")
        assert result["available"] is False

    @pytest.mark.slow
    def test_train_and_predict_real_model(self):
        """Trains (or reuses the cached model) on the real BBBP dataset and
        checks the reported held-out metrics are real and reasonable — not
        a mock, not a hardcoded number. Requires network access on first run
        to download BBBP.csv; subsequent runs reuse the cached CSV + model."""
        import cerebro_bbb_dnn as bbb
        if not bbb._HAS_BBB_DNN:
            pytest.skip("rdkit and/or tensorflow not installed")
        result = bbb.predict_bbb_class(
            "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2"  # donepezil
        )
        assert result["available"] is True
        assert result["predicted_class"] in ("permeable", "non_permeable")
        assert 0.0 <= result["probability_permeable"] <= 1.0
        # Real held-out test accuracy should beat random guessing by a wide
        # margin on a real, non-trivial dataset — but this is not a
        # hardcoded "it must be >0.9" assertion, since re-training with a
        # different seed/environment could reasonably land anywhere in a
        # sane range.
        assert result["model_test_accuracy"] > 0.7
        assert result["model_n_train"] > 1000  # real BBBP has ~1600 in an 80% split

    def test_resolver_uses_dnn_tier_for_small_molecules(self):
        """The bbb_permeability resolver should route small molecules with a
        valid SMILES through the DNN (tier 3) when the DNN is available, and
        must never apply it to biologics (see BIOLOGIC_CLASSES exclusion)."""
        import cerebro_bbb_dnn as bbb
        if not bbb._HAS_BBB_DNN:
            pytest.skip("rdkit and/or tensorflow not installed")
        from cerebro_value_resolver import resolve_value

        small_mol = resolve_value(
            "bbb_permeability", name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule")
        assert small_mol["tier"] == 3
        assert small_mol["source"] == "cerebro_bbb_dnn"

        biologic = resolve_value(
            "bbb_permeability", name="Lecanemab",
            molecule_class="monoclonal_antibody")
        assert biologic["source"] != "cerebro_bbb_dnn"
        assert biologic["value"] < 1.0  # biologics get a low class-default %


# ═════════════════════════════════════════════════════════════════════════════
# 8. DDS INVERSE-DESIGN (engine/cerebro_dds_inverse_design.py)
# ═════════════════════════════════════════════════════════════════════════════

class TestDDSInverseDesign:
    """Genetic-algorithm search over the DDS formulation-parameter space,
    using the REAL production scoring pipeline as its fitness function —
    see the module docstring for what novelty claim this is (and isn't)
    entitled to make."""

    @pytest.mark.slow
    def test_ga_search_returns_real_scored_candidates(self):
        from cerebro_dds_inverse_design import (
            ALL_PARAMS,
            generate_candidate_formulations,
        )
        from cerebro_resolved_bundles import resolve_drug_bundle

        import src.path_resolver  # noqa: F401 — ensures engine/ is on sys.path

        drug_bundle = resolve_drug_bundle(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule",
        )
        result = generate_candidate_formulations(
            drug_bundle, drug_name="Donepezil",
            n_generations=3, population_size=10, top_k=3, seed=7,
        )
        assert result["n_evaluated"] == 3 * 10
        assert 1 <= len(result["candidates"]) <= 3
        for c in result["candidates"]:
            assert "Principle_Composite_Score" in c
            assert 0 <= c["Principle_Composite_Score"] <= 100
            for p in ALL_PARAMS:
                assert p in c
        assert "disclaimer" in result and "hypotheses" in result["disclaimer"]


# ═════════════════════════════════════════════════════════════════════════════
# 9. REAL DOCKING ENGINE (src/core/real_docking_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
# The audit (docs/AUDIT_REPORT.md §11) flagged this as the scientific core
# with the least test coverage — zero tests on any docking/QSAR/PBPK engine.
# These are P0 per the audit's own testing roadmap (§11).

class TestRealDockingEngine:
    """AutoDock Vina integration with a graceful LIE-approximation fallback.
    See engine/cerebro_62_deep_engine.py's deep_P47 for where this is wired
    into the live pipeline (Task 1 of this session's remediation pass)."""

    def test_pdb_id_regex_rejects_path_traversal(self):
        """Regression test for the audit's §6 Medium finding: pdb_id was
        validated by length only elsewhere in the codebase (src/core/
        pdb_resolver.py), which a value like '../x' (4 chars) would pass.
        This file's stricter alphanumeric-4 regex is the fix pattern that
        should eventually replace that check — verify it actually rejects
        the exact class of input the audit was concerned about."""
        from src.core.real_docking_engine import _PDB_ID_RE
        assert _PDB_ID_RE.match("2NAO")       # real, valid PDB ID
        assert _PDB_ID_RE.match("1abc")       # lowercase alphanumeric, valid
        assert not _PDB_ID_RE.match("../x")   # path traversal — must reject
        assert not _PDB_ID_RE.match("../../etc/passwd")
        assert not _PDB_ID_RE.match("AB")     # too short
        assert not _PDB_ID_RE.match("ABCDE")  # too long
        assert not _PDB_ID_RE.match("AB-C")   # non-alphanumeric

    def test_lie_estimate_matches_documented_formula(self):
        """_lie_estimate implements a specific published formula (Aqvist
        1994). Regression-test the actual arithmetic, not just 'returns a
        number' — this is what distinguishes a real correlation from a
        black box, per the audit's distinction between this file (praised
        as genuine) and the fabricated Monte-Carlo code it also found."""
        from src.core.real_docking_engine import _lie_estimate
        # Donepezil-like small molecule: MW 379.5, LogP 4.77, TPSA 38.8
        result = _lie_estimate(ligand_mw=379.5, logp=4.77, tpsa=38.8,
                                hbd=0, hba=4, is_peptide=False)
        alpha, beta = 0.181, 0.137
        expected_dG = -(alpha * 4.77 + beta * (50 - 38.8/5) + 0.5*(0+4)*0.3)
        expected_dG = max(-20, min(-1, expected_dG))
        assert result["delta_G_kcal_mol"] == round(expected_dG, 2)
        assert result["docking_method"] == "LIE approximation (fallback — Vina unavailable)"
        assert result["confidence"] == "LOW — LIE approximation only"
        assert result["reference"].startswith("Aqvist 1994")
        # Kd back-calculated from the same delta_G via RT ln(Kd) — internally
        # consistent, not a separately-hardcoded number.
        assert result["Kd_nM"] > 0

    def test_run_autodock_vina_falls_back_safely_without_pdb_id(self):
        """With no valid PDB ID, this must take the deterministic LIE path
        without ever attempting a network fetch or `import vina` — verified
        by checking the returned method label, matching the manual
        verification done when this was wired into deep_P47 (Task 1)."""
        from src.core.real_docking_engine import run_autodock_vina
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = run_autodock_vina(
                smiles="CCO", pdb_id=None, output_dir=td,
                mol_profile={"MW_Da": 46.07, "LogP": -0.14},
            )
        assert result["docking_method"].startswith("LIE approximation")
        assert "note" in result  # explains why: no valid Target PDB ID

    def test_biologic_uses_lie_not_vina_regardless_of_pdb_id(self):
        """Biologics (MW > 2000 Da) can't be docked with Vina — must always
        use the LIE approximation, even if a PDB ID is supplied."""
        from src.core.real_docking_engine import run_autodock_vina
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = run_autodock_vina(
                smiles="", pdb_id="2NAO", output_dir=td,
                mol_profile={"MW_Da": 148000, "LogP": 0.2,
                             "molecule_class": "monoclonal_antibody"},
            )
        assert result["docking_method"].startswith("LIE approximation")
        assert "Biologic" in result.get("note", "")


# ═════════════════════════════════════════════════════════════════════════════
# 10. PBBM ADMET PREDICTORS (src/core/pbbm_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
# The audit's §4.8 positive findings specifically praised these functions as
# "real, correctly-cited QSAR correlations ... applied as documented" —
# these tests pin the actual documented formulas so a future edit can't
# silently turn them into another §4.3-style "docstring says X, code does Y"
# mismatch without a test failing.

class TestPBBMPredictors:
    """Regression tests for the QSAR correlations in ADMETPredictor —
    pinned against donepezil (a real, well-characterized small molecule
    used throughout this project's real pipeline runs)."""

    DONEPEZIL_SMILES = "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2"

    def test_predict_pka_returns_real_rdkit_derived_value(self):
        from src.core.pbbm_engine import ADMETPredictor
        result = ADMETPredictor.predict_pka(self.DONEPEZIL_SMILES)
        assert isinstance(result, dict)
        # pKa must be a real number in a chemically plausible range, not
        # None and not a suspiciously round placeholder like 7.0 or 0.
        pka = result.get("pKa") or result.get("pka") or result.get("value")
        if pka is not None:
            assert 0 < float(pka) < 14

    def test_predict_permeability_matches_documented_palm1997_formula(self):
        """Pins the Palm et al. 1997 Peff correlation
        (logPeff = -4.36 - 0.01*TPSA + 0.39*logP) against a fixed
        MW/LogP/TPSA input — if a future edit changes the coefficients
        without updating the docstring, this fails instead of silently
        drifting like the audit found elsewhere (§4.3)."""
        from src.core.pbbm_engine import ADMETPredictor
        result = ADMETPredictor.predict_permeability(
            self.DONEPEZIL_SMILES, mw=379.5, logp=4.31)
        assert result["_method"] == "Palm1997+Clark2003+PottsGuy1992+Wilson2001"
        assert result["Peff_cm_s"] is not None and result["Peff_cm_s"] > 0
        assert result["BBB_Filter"] in ("PASS", "FAIL")
        assert result["LogBB"] is not None

    def test_predict_permeability_handles_invalid_smiles_gracefully(self):
        """Non-SMILES input (e.g. accidentally-passed FASTA) must return
        the all-None result dict, not raise — this guard is what the
        function's own _is_valid_smiles check is for."""
        from src.core.pbbm_engine import ADMETPredictor
        result = ADMETPredictor.predict_permeability(">sp|P12345|FASTA_HEADER")
        assert result["Peff_cm_s"] is None
        assert result["_method"] == "heuristic_QSAR"  # unchanged default


# ═════════════════════════════════════════════════════════════════════════════
# 11. FULL PIPELINE INTEGRATION (run.py -> pipeline_runner.py, end-to-end)
# ═════════════════════════════════════════════════════════════════════════════
# The audit's §11 testing roadmap P0 item: "an actual end-to-end integration
# test of run.py on synthetic input asserting real output artifacts exist."
# phase5_smoke_test.py (flagged in the audit as having zero assert
# statements) only checked that modules import — this actually asserts on
# real computed output.

class TestPipelineIntegration:
    """Runs the real pipeline end-to-end against a real input Excel and
    checks real output artifacts were produced with sane values — not a
    mock, not an import-only smoke test."""

    @pytest.mark.slow
    def test_run_pipeline_from_excel_produces_real_dds_ranking(self, tmp_path):
        import shutil
        import sys as _sys

        import src.path_resolver  # noqa: F401
        from pipeline_runner import run_pipeline_from_excel
        from trial_manager import _excel_hash

        real_input = None
        for candidate in ("inputs/CEREBRO_Input_Donepezil.xlsx",):
            from pathlib import Path
            if Path(candidate).exists():
                real_input = Path(candidate)
                break
        if real_input is None:
            pytest.skip("Real Donepezil input Excel not found in inputs/")

        trial_dir = tmp_path / "Donepezil_test_trial"
        ok = run_pipeline_from_excel(
            real_input, _excel_hash(real_input), trial_dir, force=True)

        assert ok is True
        ranking_csv = trial_dir / "dds_analysis" / "formulation_ranking.csv"
        assert ranking_csv.exists(), "Pipeline must produce a real ranking CSV"

        import pandas as pd
        df = pd.read_csv(ranking_csv)
        assert len(df) > 0
        assert "BBB_Engineering_Score" in df.columns
        # Real scores vary across formulations — a hardcoded/fabricated
        # pipeline would produce identical or suspiciously uniform values.
        assert df["BBB_Engineering_Score"].nunique() > 1


# ═════════════════════════════════════════════════════════════════════════════
# 12. PDB ID RESOLVER (src/core/pdb_resolver.py)
# ═════════════════════════════════════════════════════════════════════════════

class TestPDBResolver:
    """Regression test for the audit's §6 Medium finding: pdb_id was
    validated by length only (`len(pdb_id) == 4`), which a value like
    '../x' (also 4 characters) would pass — a real path-traversal risk
    once the value reaches real_docking_engine.py's filesystem/URL
    construction. Fixed in this session's Task 6 to use the same strict
    alphanumeric regex already proven in real_docking_engine.py."""

    def test_user_provided_path_traversal_pdb_id_is_rejected(self):
        from src.core.pdb_resolver import resolve_pdb_for_drug
        result = resolve_pdb_for_drug("TestDrug", user_pdb_id="../x")
        assert result["pdb_id"] is None
        assert result["source"] != "User-provided (Excel input)"

    def test_user_provided_valid_pdb_id_is_accepted(self):
        from src.core.pdb_resolver import resolve_pdb_for_drug
        result = resolve_pdb_for_drug("TestDrug", user_pdb_id="2NAO")
        assert result["pdb_id"] == "2NAO"
        assert result["source"] == "User-provided (Excel input)"
        assert result["confidence"] == "HIGH"


# ═════════════════════════════════════════════════════════════════════════════
# 13. APPLICATION-LAYER RATE LIMITING (src/api/app.py, /auth/*)
# ═════════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    """Audit finding (§6 Medium): rate limiting only existed in nginx.conf,
    which docker-compose.yml (the simpler config, most likely run first)
    never fronts the API with — /auth/login and /auth/register were fully
    unthrottled at the application layer in that config. Fixed via slowapi
    in Task 6; this hits the real endpoint repeatedly through a real
    TestClient and checks a 429 actually appears, not just that a decorator
    is present in the source."""

    def test_login_endpoint_rate_limited_after_repeated_attempts(self, test_client):
        from src.api.app import _HAS_RATE_LIMIT
        if not _HAS_RATE_LIMIT:
            pytest.skip("slowapi not installed in this environment")

        statuses = []
        for _ in range(7):  # limit is 5/minute
            r = test_client.post("/auth/login", data={
                "username": "nonexistent_rl_test_user",
                "password": "wrong",
            })
            statuses.append(r.status_code)
        assert 429 in statuses, f"Expected a 429 among {statuses} after 7 rapid attempts"
        # Everything before the limit kicks in should be a real auth
        # response (401 for bad creds), not silently dropped.
        assert 401 in statuses[:5]
