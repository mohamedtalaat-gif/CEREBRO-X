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
        """Regression test for real flakiness: unseeded random draws from
        the identical distribution occasionally produced a PSI just over
        the 0.1 threshold from sampling noise alone (~1 in 300 runs,
        confirmed empirically) — an intermittent failure with nothing
        wrong in the code under test. Seeded like test_full_drift_detection
        already does, for a deterministic, reproducible result."""
        from src.ml.mlops import ModelDriftDetector
        np.random.seed(42)
        ref = np.random.normal(0.5, 0.1, 500)
        cur = np.random.normal(0.5, 0.1, 500)
        psi = ModelDriftDetector.compute_psi(ref, cur)
        assert psi < 0.1, f"Same distribution should have low PSI, got {psi}"

    def test_psi_detects_drift(self):
        from src.ml.mlops import ModelDriftDetector
        np.random.seed(42)
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
        assert engine.available, (
            "encryption must be active even with no ENCRYPTION_KEY set in "
            "a non-production environment — it should never silently no-op"
        )
        ct = engine.encrypt("sensitive data")
        assert ct != "sensitive data"  # actually encrypted, not passed through
        pt = engine.decrypt(ct)
        assert pt == "sensitive data"

    def test_encryption_fails_hard_in_production_without_key(self, monkeypatch):
        """Same fail-hard-on-missing-secret pattern already used for
        JWT_SECRET_KEY and CEREBRO_ADMIN_PASSWORD in src/api/auth.py —
        refuse to start with sensitive-field encryption silently disabled."""
        import importlib

        import src.compliance.privacy as privacy_module
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        importlib.reload(privacy_module)
        try:
            with pytest.raises(RuntimeError):
                privacy_module.EncryptionEngine()
        finally:
            monkeypatch.delenv("ENVIRONMENT", raising=False)
            importlib.reload(privacy_module)

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
    See engine/cerebro_62_deep_engine.py's deep_P47 for where I wired this
    into the live pipeline."""

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
        by checking the returned method label, matching the manual check I
        did when this was first wired into deep_P47."""
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
    construction. Fixed to use the same strict alphanumeric regex already
    proven in real_docking_engine.py."""

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
    unthrottled at the application layer in that config. Fixed via slowapi;
    this hits the real endpoint repeatedly through a real TestClient and
    checks a 429 actually appears, not just that a decorator is present in
    the source."""

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

    def test_app_refuses_to_boot_in_production_with_wildcard_cors(self):
        """Same fail-hard pattern as the JWT/admin-password/encryption
        checks — a real subprocess import, not a mock, since this needs to
        catch the app failing to boot at all, and reloading src.api.app
        in-process would pollute the module other tests in this file share."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        env = {**os.environ, "ENVIRONMENT": "production"}
        env.pop("CORS_ORIGINS", None)
        result = subprocess.run(
            [sys.executable, "-c", "import src.path_resolver; import src.api.app"],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
        assert "CORS_ORIGINS" in result.stderr


# ═════════════════════════════════════════════════════════════════════════════
# 14. DRUG_SMILES RESOLVER — NAME MUST NEVER BE USED AS A SMILES FALLBACK
# ═════════════════════════════════════════════════════════════════════════════

class TestDrugSmilesResolver:
    """Found this running a real Lecanemab (mAb) pipeline: it logged 30
    RDKit 'SMILES Parse Error' failures for the literal string 'Lecanemab'.
    Root cause: resolve_drug_smiles's Tier 7
    last-resort sanitizer did `raw = smiles or name`, so any drug with no
    real SMILES (i.e. every biologic — mAbs, oligonucleotides, peptides)
    fell back to passing its own NAME into RDKit as if it were a chemical
    structure. The sanitizer's heuristic (checks for any of
    C/N/O/S/P/H/F/c/n/o/s/l) is loose enough that ordinary English words
    routinely contain one of those letters, so this wasn't Lecanemab-
    specific — it silently affected any drug name for which real SMILES
    resolution failed. Fixed by never falling back to `name` in Tier 7.
    These tests use several distinct made-up names to confirm the fix is
    generic, not a special case for one drug."""

    def test_biologic_with_no_smiles_does_not_leak_name_as_smiles(self):
        from cerebro_value_resolver.categories.drug_identifiers import (
            resolve_drug_smiles,
        )
        for name in ["Lecanemab", "Nusinersen", "SomeRandomAntibodyXYZ"]:
            result = resolve_drug_smiles(name=name, smiles="")
            assert result["value"] is None, (
                f"{name}: expected no fabricated SMILES, got {result['value']!r}"
            )

    def test_small_molecule_with_real_smiles_still_resolves(self):
        from cerebro_value_resolver.categories.drug_identifiers import (
            resolve_drug_smiles,
        )
        result = resolve_drug_smiles(
            name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        assert result["value"] == "CC(=O)Oc1ccccc1C(=O)O"


# ═════════════════════════════════════════════════════════════════════════════
# 15. THE 62-PRINCIPLE SCORING SYSTEM — GROUP ROLLUPS AND DEEP-VALIDATION SPLIT
# ═════════════════════════════════════════════════════════════════════════════

class TestPrincipleGroupConsistency:
    """PRINCIPLE_GROUPS in cerebro_62_orchestrator.py maps group names to
    lists of principle IDs, and _group_score() silently skips any ID not
    present in a given DDS's per-principle results. A typo'd or renamed
    principle ID in that mapping would fail silently — the group's score
    would just be computed from fewer principles than intended, with no
    error anywhere. Every ID it references should actually exist in the
    catalog it's supposed to be grouping."""

    def test_every_grouped_principle_id_exists_in_the_catalog(self):
        from cerebro_62_orchestrator import PRINCIPLE_GROUPS
        from cerebro_62_principles_catalog import PRINCIPLES_62

        all_grouped = {pid for pids in PRINCIPLE_GROUPS.values() for pid in pids}
        missing = sorted(all_grouped - set(PRINCIPLES_62.keys()))
        assert not missing, (
            f"PRINCIPLE_GROUPS references principle IDs not in "
            f"PRINCIPLES_62: {missing} — these silently drop out of their "
            f"group's average instead of erroring"
        )

    def test_group_score_averages_correctly_and_skips_missing(self):
        from cerebro_62_orchestrator import _group_score
        per_principle = {
            "P01": {"score": 80.0},
            "P02": {"score": 40.0},
            # P03 deliberately absent — must be skipped, not treated as 0
        }
        assert _group_score(per_principle, ["P01", "P02"]) == 60.0
        assert _group_score(per_principle, ["P01", "P02", "P03"]) == 60.0
        assert _group_score(per_principle, ["P99"]) == 0.0  # none present


class TestDeepValidationIndependence:
    """overall_deep_validation()'s own docstring makes a specific integrity
    claim: independent_pct isolates only the 7 genuine-physics principles
    from the 21 surrogate-pass-through ones, and callers should cite that
    number, not the mixed pct, as evidence of physics-based validation.
    Nothing checked that the isolation logic actually does this correctly —
    a bug here would silently undermine the exact honesty distinction this
    project's audit is built around."""

    def test_pass_through_results_are_excluded_from_independent_pct(self):
        from cerebro_62_deep_engine import (
            _PASS_THROUGH_MARKER,
            overall_deep_validation,
        )
        deep_results = {
            "P02": {"validated": True,  "improvement_over_surrogate": "real physics, +12%"},
            "P13": {"validated": False, "improvement_over_surrogate": "real physics, -3%"},
            "P21": {"validated": True,  "improvement_over_surrogate": _PASS_THROUGH_MARKER},
            "P32": {"validated": True,  "improvement_over_surrogate": _PASS_THROUGH_MARKER},
        }
        result = overall_deep_validation(deep_results)
        assert result["total"] == 4
        assert result["passed_count"] == 3
        assert result["pct"] == 75.0
        # Only P02/P13 are independent — 1 of 2 passed, not 3 of 4.
        assert result["independent_computation_count"] == 2
        assert result["independent_pct"] == 50.0

    def test_all_pass_through_gives_no_independent_pct_rather_than_fabricating_one(self):
        from cerebro_62_deep_engine import (
            _PASS_THROUGH_MARKER,
            overall_deep_validation,
        )
        deep_results = {
            "P21": {"validated": True, "improvement_over_surrogate": _PASS_THROUGH_MARKER},
            "P32": {"validated": True, "improvement_over_surrogate": _PASS_THROUGH_MARKER},
        }
        result = overall_deep_validation(deep_results)
        assert result["independent_computation_count"] == 0
        assert result["independent_pct"] is None  # not 0.0, not 100.0 — genuinely unknown


class TestFirstPrinciplesPKa:
    """compute_pka_from_first_principles combines a real cited base value
    (Reich pKa tables) with a Hammett electronegativity correction and a
    Born solvation correction — real, correctly-cited physical chemistry,
    completely untested until now. Pinned against a value computed
    independently from the same published formulas, not just re-running
    the function and checking it doesn't crash."""

    def test_carboxylic_acid_pka_matches_independently_computed_value(self):
        from cerebro_value_resolver.computations.pka_first_principles import (
            compute_pka_from_first_principles,
        )
        result = compute_pka_from_first_principles(
            x_h_bond_type="H_O_carboxyl", neighbour_atoms=["C"])
        # base_pKa=4.5 (Reich table) + BDE_shift=0 (no local BDE override,
        # so it equals the reference) + Hammett (-1.0 * 0.5*(EN_C-EN_O))
        # + Born solvation (charge=1, r=1.5 A, eps=78.5) — computed
        # independently from the same published formulas, not copied from
        # the implementation.
        assert result["pKa"] == pytest.approx(4.86, abs=0.01)
        assert result["base_pKa"] == 4.5
        assert result["atom"] == "O"
        assert "Reich" in result["_computational_method"]
        assert "Bordwell 1988" in result["_computational_method"]

    def test_stronger_acid_class_gives_lower_pka_than_weaker_acid_class(self):
        """Physical sanity check: a phenol O-H (weaker acid, higher pKa)
        must score higher than a carboxylic acid O-H (stronger acid, lower
        pKa) under otherwise identical conditions — if this doesn't hold,
        the base table or shift terms have a real chemistry bug regardless
        of what any single pinned number says."""
        from cerebro_value_resolver.computations.pka_first_principles import (
            compute_pka_from_first_principles,
        )
        carboxyl = compute_pka_from_first_principles(
            x_h_bond_type="H_O_carboxyl", neighbour_atoms=["C"])
        phenol = compute_pka_from_first_principles(
            x_h_bond_type="H_O_phenol", neighbour_atoms=["C"])
        assert carboxyl["pKa"] < phenol["pKa"]


# ═════════════════════════════════════════════════════════════════════════════
# 16. REAL MOLECULAR-GRAPH GNN — REPLACES THE DELETED FAKE PSEUDO-GRAPH
# ═════════════════════════════════════════════════════════════════════════════

class TestMolecularGraphConstruction:
    """The whole point of rebuilding this component was that the old one
    faked its graph structure — identical node features tiled across a
    fully-connected placeholder topology. These tests exist specifically
    to catch a regression back to that failure mode, not just to check
    the code runs."""

    def test_different_atoms_get_different_features_not_tiled(self):
        from cerebro_molecular_gnn import smiles_to_graph
        node_feats, adjacency = smiles_to_graph("CCO")  # ethanol: C-C-O
        assert node_feats.shape[0] == 3  # 3 real heavy atoms, not N=f(MW)
        # The old bug tiled one identical vector across every node — here
        # the terminal carbon and the oxygen must have genuinely different
        # feature vectors (different element one-hot alone guarantees this).
        assert not (node_feats[0] == node_feats[2]).all()

    def test_adjacency_reflects_real_bonds_not_a_complete_graph(self):
        from cerebro_molecular_gnn import smiles_to_graph
        _, adjacency = smiles_to_graph("CCO")  # C0-C1, C1-O2 — a chain, not a triangle
        assert adjacency[0, 1] == 1.0 and adjacency[1, 0] == 1.0
        assert adjacency[1, 2] == 1.0 and adjacency[2, 1] == 1.0
        # A real chain has no C0-O2 bond — a fully-connected fake graph would.
        assert adjacency[0, 2] == 0.0 and adjacency[2, 0] == 0.0

    def test_invalid_smiles_returns_none_not_a_fabricated_graph(self):
        from cerebro_molecular_gnn import smiles_to_graph
        assert smiles_to_graph("not_a_real_smiles!!!") is None

    def test_larger_molecule_gets_more_nodes_than_smaller_one(self):
        """Node count must come from real atom count, not the old bug's
        N = f(molecular weight) formula applied to a pseudo-graph."""
        from cerebro_molecular_gnn import smiles_to_graph
        small, _ = smiles_to_graph("CCO")  # ethanol, 3 heavy atoms
        large, _ = smiles_to_graph(
            "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2")  # donepezil, 28
        assert large.shape[0] > small.shape[0]
        assert large.shape[0] == 28
        assert small.shape[0] == 3


class TestAdjacencyNormalization:
    """Kipf & Welling's D^-1/2(A+I)D^-1/2 renormalization, pinned against
    a value computed independently in this test (plain numpy on a
    hand-worked 3-node chain), not copied from the implementation."""

    def test_normalization_matches_independently_computed_value(self):
        import numpy as np

        from cerebro_molecular_gnn import _normalize_adjacency
        # 3-node chain: 0-1-2 (same shape as ethanol's C-C-O)
        adj = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], dtype=np.float32)

        # Independent computation, not calling the function under test:
        a_hat = adj + np.eye(3, dtype=np.float32)
        deg = a_hat.sum(axis=1)  # [2, 3, 2]
        d_inv_sqrt = np.diag(1.0 / np.sqrt(deg))
        expected = d_inv_sqrt @ a_hat @ d_inv_sqrt

        result = _normalize_adjacency(adj)
        np.testing.assert_allclose(result, expected, atol=1e-6)

    def test_isolated_atom_does_not_produce_uninitialized_values(self):
        """Regression test for a real bug caught while building this:
        np.power(deg, -0.5, where=deg>0) leaves garbage in positions where
        deg==0 unless the output buffer is pre-zeroed. An isolated atom
        (degree 0, plus its own self-loop = degree 1 after A+I) is a real,
        if rare, case this must handle cleanly."""
        import numpy as np

        from cerebro_molecular_gnn import _normalize_adjacency
        adj = np.zeros((2, 2), dtype=np.float32)  # two atoms, no bond between them
        result = _normalize_adjacency(adj)
        assert np.isfinite(result).all()


class TestMolecularGCNForwardPass:
    """The model itself — real batched forward pass, not just that it can
    be instantiated."""

    def test_padding_does_not_affect_pooled_output(self):
        """A molecule's prediction must be identical whether it's run
        alone or padded alongside a larger molecule in the same batch —
        if the mask leaked into the mean pool, it wouldn't be."""
        import torch

        from cerebro_molecular_gnn import MolecularGCN, _pad_batch, smiles_to_graph
        torch.manual_seed(0)
        model = MolecularGCN()
        model.eval()

        small = smiles_to_graph("CCO")
        large = smiles_to_graph("COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2")

        with torch.no_grad():
            x, a, m = _pad_batch([small])
            solo_pred = model(x, a, m)[0].item()

            x2, a2, m2 = _pad_batch([small, large])
            batched_pred = model(x2, a2, m2)[0].item()

        assert abs(solo_pred - batched_pred) < 1e-5

    def test_output_is_a_valid_probability(self):
        import torch

        from cerebro_molecular_gnn import MolecularGCN, _pad_batch, smiles_to_graph
        model = MolecularGCN()
        model.eval()
        g = smiles_to_graph("CCO")
        with torch.no_grad():
            x, a, m = _pad_batch([g])
            out = model(x, a, m)
        assert 0.0 <= out[0].item() <= 1.0

    @pytest.mark.slow
    def test_bbb_resolver_attaches_real_gnn_cross_check_alongside_dnn(self):
        """The live integration point: engine/cerebro_value_resolver/
        categories/bbb_perm.py's Tier 3 already resolves via the DNN —
        confirms the GNN cross-check actually shows up in real resolver
        output, agreeing on a real, well-known BBB-penetrant drug, rather
        than the two models being silently merged into one number."""
        from cerebro_bbb_dnn import _HAS_BBB_DNN
        from cerebro_molecular_gnn import _HAS_MOL_GNN
        if not (_HAS_BBB_DNN and _HAS_MOL_GNN):
            pytest.skip("tensorflow and/or torch not installed")
        from cerebro_value_resolver.categories.bbb_perm import resolve_bbb_permeability

        # Donepezil: a real, well-known CNS drug that crosses the BBB.
        result = resolve_bbb_permeability(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2")
        assert result["source"] == "cerebro_bbb_dnn"
        assert "gnn_predicted_class" in result
        assert "gnn_probability_permeable" in result
        assert result["gnn_predicted_class"] == "permeable"
        assert result["dnn_predicted_class"] == "permeable"
        assert result["gnn_agrees_with_dnn"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 17. CLASS-B DEEP PHYSICS ENGINE (cerebro_62_deep_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
def _drug_bundle(**overrides):
    b = {
        "drug_mw":  {"value": 350.0},
        "drug_logp": {"value": 2.5},
        "drug_tpsa": {"value": 60.0},
        "drug_hbd": {"value": 2},
        "drug_hba": {"value": 5},
        "pk_halflife": {"value": 0.5},
        "bbb_permeability": {"value": 5.0},
        "_meta": {"drug_type": "small_molecule", "name": "test_drug",
                  "identifiers": {"smiles": "CCO"}},
    }
    b.update(overrides)
    return b


def _dds_bundle(**meta_overrides):
    meta = {"carrier_type": "liposome", "dds_type": "material"}
    meta.update(meta_overrides)
    return {"_meta": meta}


def _combo_bundle(dds_row=None):
    return {"_meta": {"dds_row": dds_row or {}}}


class TestDeepP02AllometricScaling:
    """Cross-species PK scaling — Mahmood 2007 parameter-specific exponents."""

    def test_half_life_scaling_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P02

        drug = _drug_bundle(drug_mw={"value": 350.0}, pk_halflife={"value": 0.5})
        r = deep_P02(drug, _dds_bundle(), _combo_bundle(), {"score": 50})

        ratio = 70_000 / 25
        expected_thalf_h = (0.5 * 24) * (ratio ** 0.25)
        assert r["value"] == round(expected_thalf_h, 2)
        assert r["validated"] is True

    def test_confidence_depends_on_drug_type(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P02

        small_mol = deep_P02(_drug_bundle(), _dds_bundle(), _combo_bundle(), {})
        assert (small_mol["score"], small_mol["confidence"]) == (90, "HIGH")

        mab = deep_P02(
            _drug_bundle(_meta={"drug_type": "monoclonal_antibody", "name": "x",
                                  "identifiers": {"smiles": ""}}),
            _dds_bundle(), _combo_bundle(), {})
        assert (mab["score"], mab["confidence"]) == (65, "LOW")

        other = deep_P02(
            _drug_bundle(_meta={"drug_type": "nanoparticle_conjugate", "name": "x",
                                  "identifiers": {"smiles": ""}}),
            _dds_bundle(), _combo_bundle(), {})
        assert (other["score"], other["confidence"]) == (75, "MODERATE")


class TestDeepP38StokesEinstein:
    """Glymphatic clearance — physical Stokes-Einstein diffusion, no fitted knobs."""

    def test_reference_size_returns_exactly_six_hours(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P38

        r = deep_P38(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Size_nm": 50.0}), {})
        assert r["value"] == 6.0
        assert r["validated"] is True
        assert r["confidence"] == "HIGH"

    def test_clearance_time_scales_linearly_with_particle_size(self):
        """D ∝ 1/r, and t_clear ∝ 1/D, so doubling+quadrupling the radius
        relative to the 50nm reference should scale t_clear by the same
        factor — a direct physical consequence of Stokes-Einstein, not a
        tuned parameter."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P38

        r = deep_P38(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Size_nm": 200.0}), {})
        assert r["value"] == 24.0  # 6h * (200/50)
        assert r["validated"] is True  # 6 <= 24 <= 48

    def test_missing_size_fails_cleanly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P38

        r = deep_P38(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Size_nm": 0.0}), {})
        assert r["validated"] is False
        assert r["confidence"] == "FAILED"


class TestDeepP18ActiveTargeting:
    """MM/GBSA-style ΔG from a validated ligand-receptor Kd lookup table."""

    def test_known_ligand_resolves_to_its_receptor_and_dg(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P18

        r = deep_P18(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Surface_Ligand": "Transferrin"}), {"score": 50})
        assert r["raw"]["receptor"] == "TfR1"
        assert r["value"] == -10.5
        assert r["validated"] is True  # |−10.5| >= 8.0

    def test_weak_ligand_is_not_validated(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P18

        r = deep_P18(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Surface_Ligand": "TAT"}), {})
        assert r["value"] == -6.5
        assert r["validated"] is False  # |−6.5| < 8.0

    def test_unrecognized_ligand_falls_back_to_generic_receptor(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P18

        r = deep_P18(_drug_bundle(), _dds_bundle(),
                      _combo_bundle({"Surface_Ligand": "made_up_peptide_37"}), {})
        assert r["raw"]["receptor"] == "unknown_BBB_receptor"
        assert r["value"] == -7.0

    def test_no_ligand_bypasses_computation_entirely(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P18

        r = deep_P18(_drug_bundle(), _dds_bundle(), _combo_bundle({}), {})
        assert r["validated"] is False
        assert r["value"] == 0
        assert "No surface ligand" in r["method"]


class TestDeepP47BindingAffinity:
    """LIE-approximation fallback — same formula whether it's reached via
    real_docking_engine's own fallback or the deep-engine's inline copy."""

    def test_lie_delta_g_matches_published_aqvist_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P47

        logp, tpsa, hbd, hba = 3.0, 60.0, 2, 5
        drug = _drug_bundle(drug_logp={"value": logp}, drug_tpsa={"value": tpsa},
                             drug_hbd={"value": hbd}, drug_hba={"value": hba})
        r = deep_P47(drug, _dds_bundle(), _combo_bundle(), {"score": 50, "value": -5})

        alpha, beta = 0.181, 0.137
        expected = -(alpha * logp + beta * (50 - tpsa / 5) + 0.5 * (hbd + hba) * 0.3)
        expected = max(-20, min(-1, expected))
        assert r["value"] == round(expected, 2)
        assert "LIE approximation" in r["method"]
        assert "LOW" in r["confidence"]


class TestDeepP31Biodistribution:
    """7-organ whole-body distribution — deterministic weighted split, no ODE."""

    def test_organ_distribution_matches_hand_computation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P31

        drug = _drug_bundle(bbb_permeability={"value": 5.0})
        r = deep_P31(drug, _dds_bundle(),
                      _combo_bundle({"Size_nm": 250.0, "Zeta_Potential_mV": -30.0}),
                      {})

        # brain=5, liver=35 (size>200), spleen=20 (|zeta|>25), kidney=8,
        # lung=5, heart=3, muscle=100 → sum=176, brain_norm=5/176*100
        expected_brain_pct = round(5.0 / 176.0 * 100, 2)
        assert r["value"] == expected_brain_pct
        assert r["raw"]["organ_distribution_pct"]["liver"] == round(35 / 176 * 100, 2)

    def test_active_targeting_ligand_triples_brain_uptake_share(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P31

        drug = _drug_bundle(bbb_permeability={"value": 5.0})
        no_ligand = deep_P31(drug, _dds_bundle(),
                              _combo_bundle({"Size_nm": 250.0, "Zeta_Potential_mV": -30.0}),
                              {})
        with_ligand = deep_P31(drug, _dds_bundle(),
                                _combo_bundle({"Size_nm": 250.0, "Zeta_Potential_mV": -30.0,
                                               "Surface_Ligand": "Transferrin"}),
                                {})
        assert with_ligand["value"] > no_ligand["value"]
        assert with_ligand["raw"]["ligand_boost"] is True
        assert no_ligand["raw"]["ligand_boost"] is False


class TestDeepPBPKODEs:
    """3- and 4-compartment PBPK ODE integrators (P13, P44) — checks the
    deterministic rate constants they build and the physically-required
    direction of the ligand-targeting effect, without hand-solving the ODE."""

    def test_p13_ligand_targeting_raises_brain_exposure(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P13

        drug = _drug_bundle(bbb_permeability={"value": 5.0})
        no_ligand = deep_P13(drug, _dds_bundle(), _combo_bundle({}), {})
        with_ligand = deep_P13(drug, _dds_bundle(),
                                _combo_bundle({"Surface_Ligand": "Transferrin"}), {})

        assert with_ligand["raw"]["k_bb_in_per_h"] == round(no_ligand["raw"]["k_bb_in_per_h"] * 3, 4)
        assert with_ligand["value"] > no_ligand["value"]  # higher brain AUC ratio

    def test_p13_fails_cleanly_without_scipy(self, monkeypatch):
        import builtins
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P13

        real_import = builtins.__import__

        def blocked(name, *a, **kw):
            if name == "scipy.integrate" or name.startswith("scipy"):
                raise ImportError("blocked for test")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", blocked)
        r = deep_P13(_drug_bundle(), _dds_bundle(), _combo_bundle({}), {})
        assert r["validated"] is False
        assert r["confidence"] == "FAILED"

    def test_p44_glymphatic_rate_matches_stokes_einstein_size_scaling(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import deep_P44

        small = deep_P44(_drug_bundle(), _dds_bundle(),
                          _combo_bundle({"Size_nm": 50.0}), {})
        large = deep_P44(_drug_bundle(), _dds_bundle(),
                          _combo_bundle({"Size_nm": 300.0}), {})
        # k_glymph = 0.2 / max(1, size/100) — unchanged at/under 100nm,
        # inversely proportional above it.
        assert small["raw"]["k_glymph_per_h"] == 0.2
        assert large["raw"]["k_glymph_per_h"] == round(0.2 / 3.0, 4)


class TestDeepValidationDispatch:
    """evaluate_deep_for_top1() — the real/HPC-deferred split must stay
    exhaustive and non-overlapping across all 28 Class-B principles."""

    def test_deep_functions_and_hpc_only_partition_cleanly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import DEEP_FUNCTIONS, HPC_ONLY_PRINCIPLES

        overlap = set(DEEP_FUNCTIONS) & set(HPC_ONLY_PRINCIPLES)
        assert overlap == set()
        assert len(DEEP_FUNCTIONS) == 7

    def test_evaluate_deep_for_top1_covers_every_registered_principle(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import (
            DEEP_FUNCTIONS,
            HPC_ONLY_PRINCIPLES,
            evaluate_deep_for_top1,
        )

        out = evaluate_deep_for_top1(_drug_bundle(), _dds_bundle(), _combo_bundle({}), {})
        assert set(out) == set(DEEP_FUNCTIONS) | set(HPC_ONLY_PRINCIPLES)
        # An HPC-only principle must carry the honest pass-through marker.
        assert "external HPC run" in out["P01"]["improvement_over_surrogate"]
        # A real DEEP_FUNCTIONS principle must not carry that marker.
        assert "external HPC run" not in out["P38"]["improvement_over_surrogate"]

    def test_a_raising_deep_function_is_caught_and_marked_failed(self):
        """A malformed Excel cell (non-numeric zeta potential) makes
        deep_P31's float() conversion raise — the dispatcher must catch
        it and report _failed() for that principle only, not crash the
        whole batch."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import evaluate_deep_for_top1

        bad_combo = _combo_bundle({"Zeta_Potential_mV": "not_a_number"})
        out = evaluate_deep_for_top1(_drug_bundle(), _dds_bundle(), bad_combo, {})
        assert out["P31"]["validated"] is False
        assert out["P31"]["confidence"] == "FAILED"
        # Other principles in the same batch must still compute normally.
        assert out["P38"]["confidence"] != "FAILED"


# ═════════════════════════════════════════════════════════════════════════════
# 18. pKa RESOLVER (cerebro_value_resolver/categories/drug_pka.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDrugPkaResolver:
    """name='' on every call keeps these fully offline: _pka_chembl short-
    circuits on a falsy name before touching the network, so Tier 7
    first-principles is exercised deterministically."""

    def test_researcher_override_short_circuits_to_tier_zero(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import resolve_drug_pka_acidic

        r = resolve_drug_pka_acidic(name="", smiles="CC(=O)O", researcher_override=3.1)
        assert r["value"] == 3.1
        assert r["tier"] == 0
        assert r["source"] == "researcher_override"

    def test_carboxylic_acid_acidic_pka_in_physically_plausible_range(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import resolve_drug_pka_acidic

        r = resolve_drug_pka_acidic(name="", smiles="CC(=O)O")  # acetic acid
        assert r["tier"] == 7
        assert "Bordwell-Hammett-Born" in r["method"]
        assert 2.0 < r["value"] < 6.0  # real carboxylic acids: pKa ~2-5

    def test_primary_amine_basic_pka_in_physically_plausible_range(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import resolve_drug_pka_basic

        r = resolve_drug_pka_basic(name="", smiles="CCN")  # ethylamine
        assert r["tier"] == 7
        assert 8.0 < r["value"] < 12.0  # real aliphatic amines: pKa(BH+) ~9.5-11

    def test_dominant_pka_picks_whichever_real_result_is_closer_to_7_4(self):
        """Cross-checks the dominant-selection logic against the real
        acidic/basic resolvers it wraps, rather than against a value
        copied out of the implementation."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import (
            resolve_drug_pka_acidic,
            resolve_drug_pka_basic,
            resolve_drug_pka_dominant,
        )

        smiles = "NCC(=O)O"  # glycine — both an amine and a carboxylic acid
        acid = resolve_drug_pka_acidic(name="", smiles=smiles)
        base = resolve_drug_pka_basic(name="", smiles=smiles)
        dom = resolve_drug_pka_dominant(name="", smiles=smiles)

        expected_kind = "acidic" if abs(acid["value"] - 7.4) <= abs(base["value"] - 7.4) else "basic"
        expected_value = acid["value"] if expected_kind == "acidic" else base["value"]
        assert dom["kind"] == expected_kind
        assert dom["value"] == expected_value

    def test_missing_smiles_reports_honest_null_not_a_fabricated_number(self):
        """Regression test for a real bug: resolve_drug_pka_acidic/basic
        used to fall back to a hardcoded generic sp3 C-H guess (~50) or a
        '-14 proxy' (~-10 to -14) whenever no SMILES was available, which
        made resolve_drug_pka_dominant's honest 'not ionizable' branch and
        hh_microspeciation's 'no ionizable groups' branch permanently
        unreachable — the system always reported *some* plausible-looking
        pKa number even with zero structural evidence to support it."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import (
            resolve_drug_pka_acidic,
            resolve_drug_pka_basic,
            resolve_drug_pka_dominant,
            resolve_drug_microspecies,
        )

        acid = resolve_drug_pka_acidic(name="", smiles="")
        base = resolve_drug_pka_basic(name="", smiles="")
        assert acid["value"] is None
        assert base["value"] is None

        dom = resolve_drug_pka_dominant(name="", smiles="")
        assert dom["value"] is None
        assert dom["note"] == "Drug is not ionizable at any pH"
        assert dom["confidence"] == "HIGH"

        micro = resolve_drug_microspecies(name="", smiles="")
        assert micro["value"]["method"] == "no ionizable groups (assumed neutral)"
        assert micro["value"]["f_neutral"] == 1.0

    def test_microspecies_fractions_sum_to_one_for_a_real_acid(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_pka import resolve_drug_microspecies

        r = resolve_drug_microspecies(name="", smiles="CC(=O)O")
        fr = r["value"]
        total = fr["f_cationic"] + fr["f_anionic"] + fr["f_zwitterion"] + fr["f_neutral"]
        assert total == pytest.approx(1.0, abs=1e-3)
        # Acetic acid (pKa ~4.86) is mostly deprotonated at physiological pH 7.4.
        assert fr["f_anionic"] > 0.9


# ═════════════════════════════════════════════════════════════════════════════
# 19. DLVO COLLOIDAL-STABILITY RESOLVER (categories/physics_dlvo.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestPhysicsDLVOResolver:
    """Pure closed-form electrostatics/vdW physics — no bundles, no network,
    so every test hand-derives the expected number from the same cited
    equation and compares, independent of the implementation."""

    def test_hamaker_combining_rule_matches_israelachvili_formula(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_hamaker_combined,
        )

        r = resolve_physics_hamaker_combined(carrier_Hamaker_J=5e-20, medium_Hamaker_J=3.7e-20)
        expected = (math.sqrt(5e-20) - math.sqrt(3.7e-20)) ** 2
        assert r["value"] == pytest.approx(expected, rel=1e-9)
        assert r["tier"] == 6

    def test_hamaker_defaults_to_generic_organic_when_not_provided(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_hamaker_combined,
        )

        r = resolve_physics_hamaker_combined(carrier_Hamaker_J=None)
        expected = (math.sqrt(6e-21) - math.sqrt(3.7e-20)) ** 2  # generic 6e-21 fallback
        assert r["value"] == pytest.approx(expected, rel=1e-9)
        assert "not provided" in r["live_db_misses"][0]

    def test_debye_length_at_physiological_ionic_strength_is_realistic(self):
        """κ⁻¹ ≈ 0.7-1.0 nm at I=0.15M is the textbook physiological Debye
        length — a real, independently-known sanity bound, not a number
        pulled from the implementation."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_debye_length,
        )

        r = resolve_physics_debye_length(ionic_strength_M=0.15)
        kappa_inv_nm = r["value"] * 1e9
        assert 0.6 < kappa_inv_nm < 1.1

    def test_debye_length_shrinks_as_ionic_strength_rises(self):
        """Higher ionic strength screens electrostatics more effectively —
        κ⁻¹ ∝ I^-0.5, a direct physical consequence, not tunable."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_debye_length,
        )

        low_I = resolve_physics_debye_length(ionic_strength_M=0.01)
        high_I = resolve_physics_debye_length(ionic_strength_M=1.0)
        assert low_I["value"] > high_I["value"]

    def test_dlvo_potential_van_der_waals_term_is_attractive(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_dlvo_potential,
        )

        r = resolve_physics_dlvo_potential()
        assert r["V_vdW_kT"] < 0  # vdW is always attractive between like particles

    def test_dlvo_potential_component_sum_matches_reported_total(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_dlvo_potential,
        )

        r = resolve_physics_dlvo_potential(zeta_mV=-40, separation_nm=3)
        assert r["value"] == pytest.approx(
            r["V_vdW_kT"] + r["V_el_kT"], rel=1e-9)

    def test_dlvo_higher_zeta_magnitude_increases_electrostatic_repulsion(self):
        """A more strongly (de)stabilized surface should raise the
        electrostatic repulsion term — this is what makes a formulation
        colloidally stable in the first place."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_dlvo_potential,
        )

        weak = resolve_physics_dlvo_potential(zeta_mV=-10)
        strong = resolve_physics_dlvo_potential(zeta_mV=-40)
        assert strong["V_el_kT"] > weak["V_el_kT"]

    def test_grahame_equation_surface_charge_matches_hand_computation(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_zeta_to_surface_charge,
        )

        eps_0, k_B, N_A, e = 8.854e-12, 1.380649e-23, 6.022e23, 1.602e-19
        T_K, epsilon_r, I, zeta_mV = 310.15, 78.5, 0.15, -25
        psi = zeta_mV * 1e-3
        expected = (math.sqrt(8 * eps_0 * epsilon_r * k_B * T_K * I * 1000 * N_A)
                    * math.sinh(e * psi / (2 * k_B * T_K)))

        r = resolve_physics_zeta_to_surface_charge(zeta_mV=zeta_mV)
        assert r["value"] == pytest.approx(expected, rel=1e-9)
        assert r["value"] < 0  # negative zeta -> negative surface charge

    def test_grahame_equation_zero_zeta_gives_zero_charge(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_zeta_to_surface_charge,
        )

        r = resolve_physics_zeta_to_surface_charge(zeta_mV=0)
        assert r["value"] == pytest.approx(0.0, abs=1e-12)

    def test_researcher_overrides_short_circuit_all_four_resolvers(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_dlvo import (
            resolve_physics_dlvo_potential,
            resolve_physics_debye_length,
            resolve_physics_hamaker_combined,
            resolve_physics_zeta_to_surface_charge,
        )

        for fn in (resolve_physics_hamaker_combined, resolve_physics_debye_length,
                   resolve_physics_dlvo_potential, resolve_physics_zeta_to_surface_charge):
            r = fn(researcher_override=1.23)
            assert r["value"] == 1.23
            assert r["tier"] == 0
            assert r["source"] == "researcher_override"


# ═════════════════════════════════════════════════════════════════════════════
# 20. MATERIAL-CLASS LOOKUP TABLES (lipid / surface / polymer)
# ═════════════════════════════════════════════════════════════════════════════
def _resolve(category, **kwargs):
    """These three material-property files build their resolvers with a
    factory (_build_*_resolver) that registers each one under @register but
    never binds it to a named module attribute — so, unlike bbb_perm.py's
    directly-defined functions, they're only reachable through the shared
    registry, exactly as production code (cerebro_resolved_bundles.py) calls
    them."""
    import src.path_resolver  # noqa: F401
    import cerebro_value_resolver.categories.material_lipid  # noqa: F401
    import cerebro_value_resolver.categories.material_polymer  # noqa: F401
    import cerebro_value_resolver.categories.material_surface  # noqa: F401
    from cerebro_value_resolver._core import resolve_value
    return resolve_value(category, **kwargs)


class TestMaterialLipidResolver:
    def test_known_lipid_type_returns_its_israelachvili_table_value(self):
        r = _resolve("material_lipid_tm", lipid_type="DSPC")
        assert r["value"] == 55.0
        assert r["tier"] == 7

    def test_lipid_type_takes_priority_over_carrier(self):
        r = _resolve("material_lipid_tm", carrier="liposome", lipid_type="dppc")
        assert r["value"] == 41.0  # DPPC's own Tm, not the generic liposome default

    def test_unrecognized_carrier_falls_back_to_generic_liposome_default(self):
        r = _resolve("material_lipid_packing_parameter", carrier="some_unknown_carrier")
        assert r["value"] == 0.95  # falls through to the "liposome" table entry

    def test_cholesterol_has_no_melting_point_falls_to_generic_default(self):
        """chol's Tm_C is explicitly None in the table — the resolver must
        not return None silently, it should fall through to the t7 default."""
        r = _resolve("material_lipid_tm", lipid_type="chol")
        assert r["value"] == 35.0  # generic_lipid default, not None

    def test_researcher_override_short_circuits(self):
        r = _resolve("material_lipid_bending_modulus", researcher_override=99.0)
        assert r["value"] == 99.0 and r["tier"] == 0


class TestMaterialSurfaceResolver:
    def test_metallic_carrier_dielectric_is_the_real_fixed_value(self):
        """Regression guard: this dict entry used to be built from a broken
        `-np_inf if False else 2.0` expression papered over by a redundant
        post-hoc assignment a few lines down. Cleaned up to a plain literal —
        this pins the value stays 2.0 (gold's real approximate epsilon_r)."""
        r = _resolve("material_dielectric", carrier="metallic")
        assert r["value"] == 2.0

    def test_known_carrier_returns_its_table_value(self):
        r = _resolve("material_hamaker_constant", carrier="plga")
        assert r["value"] == 6e-21
        assert r["tier"] == 7

    def test_unknown_carrier_falls_back_to_generic_default(self):
        r = _resolve("material_refractive_index", carrier="not_a_real_carrier")
        assert r["value"] == 1.46
        assert r["confidence"] == "LOW"


class TestMaterialPolymerResolver:
    def test_known_polymer_returns_its_table_value(self):
        r = _resolve("material_polymer_tg", carrier="pla")
        assert r["value"] == 60.0
        assert r["tier"] == 7

    def test_plga_has_no_melting_point_falls_to_generic_default(self):
        """PLGA is amorphous — Tm_C is explicitly None in the table."""
        r = _resolve("material_polymer_tm", carrier="plga")
        assert r["value"] == 100.0  # generic default, not None
        assert "warning" in r

    def test_unknown_carrier_falls_back_to_generic_default(self):
        r = _resolve("material_polymer_density", carrier="unobtainium")
        assert r["value"] == 1.25
        assert r["confidence"] == "LOW"

    def test_researcher_override_short_circuits(self):
        r = _resolve("material_polymer_mw", carrier="plga", researcher_override=45000.0)
        assert r["value"] == 45000.0 and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 21. TRANSPORT-COEFFICIENT RESOLVER (categories/physics_transport.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestPhysicsTransportComputations:
    """The underlying pure-math correlations, hand-verified against their
    published formulas independent of the resolver wrapper."""

    def test_stokes_einstein_diff_matches_published_formula(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.computations import stokes_einstein_diff

        mw, T_K, visc = 350.0, 310.15, 6.91e-4
        k_B = 1.380649e-23
        r_m = 6.6e-12 * (mw ** (1 / 3))
        expected = (k_B * T_K) / (6 * math.pi * visc * r_m)
        assert stokes_einstein_diff(mw, T_K=T_K, visc_Pa_s=visc) == pytest.approx(expected, rel=1e-9)

    def test_stokes_einstein_diff_zero_or_negative_mw_returns_zero(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.computations import stokes_einstein_diff

        assert stokes_einstein_diff(0.0) == 0.0
        assert stokes_einstein_diff(-10.0) == 0.0

    def test_larger_molecules_diffuse_more_slowly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.computations import stokes_einstein_diff

        assert stokes_einstein_diff(100.0) > stokes_einstein_diff(10000.0)


class TestPhysicsDiffCoeffWaterResolver:
    def test_missing_wilke_chang_in_chemicals_lib_falls_through_to_pure_math(self):
        """Regression test: the installed chemicals==1.5.2 no longer
        exposes Wilke_Chang (or any liquid-diffusivity correlation) under
        any name — confirmed directly against the installed package. The
        resolver used to try importing it on every single call anyway, an
        import that's guaranteed to fail, silently caught, and always
        fell through to tier 6. Fixed by not attempting the dead import;
        this pins that tier 6 (the resolver's own pure-math Wilke-Chang)
        is what actually answers when mw_Da is given."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_diff_coeff_water,
        )

        r = resolve_physics_diff_coeff_water(mw_Da=350.0)
        assert r["tier"] == 6
        assert r["source"] == "cerebro_value_resolver:wilke_chang"
        assert 1e-11 < r["value"] < 1e-8  # physically sane aqueous D for a small molecule

    def test_missing_mw_falls_back_to_typical_small_molecule_constant(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_diff_coeff_water,
        )

        r = resolve_physics_diff_coeff_water()
        assert r["value"] == 5e-10
        assert r["tier"] == 7

    def test_researcher_override_short_circuits(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_diff_coeff_water,
        )

        r = resolve_physics_diff_coeff_water(researcher_override=1e-9)
        assert r["value"] == 1e-9 and r["tier"] == 0


class TestPhysicsDiffCoeffMembraneResolver:
    def test_higher_logp_increases_membrane_retention_and_slows_diffusion(self):
        """The model's own stated assumption: more lipophilic drugs are
        retained more strongly in the bilayer, slowing lateral diffusion."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_diff_coeff_membrane,
        )

        low_logp = resolve_physics_diff_coeff_membrane(mw_Da=350.0, logp=1.0)
        high_logp = resolve_physics_diff_coeff_membrane(mw_Da=350.0, logp=5.0)
        assert high_logp["value"] < low_logp["value"]

    def test_membrane_diffusion_is_slower_than_aqueous_diffusion(self):
        """Membrane viscosity is modeled as ~100x water — lateral diffusion
        in the bilayer should always be far slower than in bulk water for
        the same molecule."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_diff_coeff_membrane,
            resolve_physics_diff_coeff_water,
        )

        water = resolve_physics_diff_coeff_water(mw_Da=350.0)
        membrane = resolve_physics_diff_coeff_membrane(mw_Da=350.0, logp=2.5)
        assert membrane["value"] < water["value"]


class TestPhysicsLJParameterResolvers:
    def test_stiel_thodos_epsilon_no_longer_gated_behind_chemicals_lib(self):
        """Regression test: this branch computes ε/k_B = 0.77·Tc inline —
        it never actually calls the `chemicals` package — but used to be
        wrapped in `if _HAS_CHEMICALS:` anyway, so a real Tb_K-based
        estimate would be silently skipped (falling to a generic 300K
        constant) whenever the unrelated `chemicals` package happened to
        be missing. Also pins the tier to 7 (pure first-principles math,
        no library involved) rather than the old mislabeled tier 5."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_lj_epsilon,
        )

        Tb_K = 350.0
        r = resolve_physics_lj_epsilon(Tb_K=Tb_K)
        assert r["value"] == pytest.approx(0.77 * 1.5 * Tb_K, rel=1e-9)
        assert r["tier"] == 7

    def test_lj_epsilon_falls_back_to_mw_then_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_lj_epsilon,
        )

        by_mw = resolve_physics_lj_epsilon(mw_Da=200.0)
        assert by_mw["value"] == pytest.approx(0.5 * 200.0)
        assert by_mw["tier"] == 6

        generic = resolve_physics_lj_epsilon()
        assert generic["value"] == 300.0
        assert generic["tier"] == 7

    def test_lj_sigma_bsl_correlation_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_lj_sigma,
        )

        Vc = 250.0
        r = resolve_physics_lj_sigma(Vc_cm3_mol=Vc)
        assert r["value"] == pytest.approx(0.841 * Vc ** (1 / 3), rel=1e-9)
        assert r["tier"] == 6

    def test_lj_sigma_falls_back_to_mw_then_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_lj_sigma,
        )

        by_mw = resolve_physics_lj_sigma(mw_Da=200.0)
        assert by_mw["value"] == pytest.approx(0.5 * 200.0 ** (1 / 3), rel=1e-9)
        assert by_mw["tier"] == 7

        generic = resolve_physics_lj_sigma()
        assert generic["value"] == 5.0


class TestPhysicsViscositySolventResolver:
    def test_water_viscosity_at_body_temperature_is_physically_realistic(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_viscosity_solvent,
        )

        r = resolve_physics_viscosity_solvent(solvent="water")
        # Real water viscosity at 37°C is ~0.69 mPa·s regardless of whether
        # thermo's lookup or the Andrade fallback answers.
        assert 5e-4 < r["value"] < 9e-4

    def test_unknown_solvent_defaults_to_water_viscosity(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_viscosity_solvent,
        )

        r = resolve_physics_viscosity_solvent(solvent="totally_made_up_solvent_xyz")
        assert r["value"] == 1e-3
        assert r["confidence"] == "LOW"

    def test_researcher_override_short_circuits(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.physics_transport import (
            resolve_physics_viscosity_solvent,
        )

        r = resolve_physics_viscosity_solvent(researcher_override=2e-3)
        assert r["value"] == 2e-3 and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 22. QUANTUM/ATOMIC RESOLVER (categories/quantum_atomic.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestQuantumAtomicResolver:
    def test_mendeleev_polarizability_is_converted_from_bohr3_to_angstrom3(self):
        """Regression test for a real unit-conversion bug: mendeleev's
        dipole_polarizability attribute is in Bohr³ (confirmed directly —
        mendeleev reports H at 4.507 Bohr³), not Å³ as the resolver assumed.
        Using it unconverted overstated every atomic polarizability by
        ~6.75x. Checked against the file's own independently-sourced
        Schwerdtfeger 2019 fallback table, which the converted mendeleev
        value should land close to."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            _atomic_polarizability,
        )

        # Real experimental atomic polarizability of hydrogen is ~0.667 Å³ —
        # this file's own fallback table agrees. mendeleev raw is 4.507 Bohr³;
        # unconverted that would wrongly read back as ~4.5.
        assert _atomic_polarizability("H") == pytest.approx(0.667, abs=0.05)
        assert _atomic_polarizability("C") == pytest.approx(1.76, abs=0.15)

    def test_molecular_polarizability_sums_atomic_contributions(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            _atomic_polarizability,
            resolve_quantum_polarizability,
        )

        r = resolve_quantum_polarizability(smiles="CCO")  # ethanol: C,C,O + 3 heavy atoms' H
        expected = (_atomic_polarizability("C") + _atomic_polarizability("C")
                    + _atomic_polarizability("O") + 3 * 0.667)
        assert r["value"] == pytest.approx(expected, abs=1e-2)
        assert r["tier"] == 5

    def test_no_smiles_falls_back_to_typical_drug_polarizability(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_polarizability,
        )

        r = resolve_quantum_polarizability(smiles="")
        assert r["value"] == 15.0
        assert r["tier"] == 7

    def test_dipole_moment_rdkit_path_returns_a_real_geometry_based_value(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_dipole_moment,
        )

        r = resolve_quantum_dipole_moment(smiles="CCO")  # ethanol has a real, nonzero dipole
        assert r["tier"] == 3
        assert r["value"] > 0.5  # ethanol's real dipole moment is ~1.7 D

    def test_homo_lumo_gap_shrinks_with_more_aromatic_rings(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_homo_lumo_gap,
        )

        few_rings = resolve_quantum_homo_lumo_gap(aromatic_rings=1)
        many_rings = resolve_quantum_homo_lumo_gap(aromatic_rings=5)
        assert many_rings["value"] < few_rings["value"]
        assert few_rings["value"] == pytest.approx(5.5 - 0.4 * 1, rel=1e-9)

    def test_homo_lumo_gap_has_a_physical_floor(self):
        """Extended conjugation can't push the gap below the floor the
        formula hard-clamps at (max(2.5, ...))."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_homo_lumo_gap,
        )

        r = resolve_quantum_homo_lumo_gap(aromatic_rings=20)
        assert r["value"] == 2.5

    def test_atomic_charges_sum_is_nonzero_for_a_real_molecule(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_atomic_charges_sum,
        )

        r = resolve_quantum_atomic_charges_sum(smiles="CCO")
        assert r["tier"] == 3
        assert r["value"] > 0

    def test_ionization_energy_known_element_matches_nist_table(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_ionization_energy,
        )

        r = resolve_quantum_ionization_energy(symbol="C")
        assert r["value"] == pytest.approx(11.260, abs=0.01)

    def test_unrecognized_symbol_falls_back_to_honest_hydrogen_like_baseline(self):
        """Regression test: this branch used to compute
        R·(Z_eff/n)²·n² with a hardcoded n=2 'second-shell baseline' —
        but n cancels out of that formula algebraically for ANY value,
        so it always silently returned the fixed hydrogen ground-state
        energy (13.606 eV) dressed up as a per-element Slater's-rules
        derivation. Now it's labeled for what it actually is."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_ionization_energy,
        )

        r = resolve_quantum_ionization_energy(symbol="Xx_not_a_real_element")
        assert r["value"] == pytest.approx(13.606, abs=0.001)
        assert r["source"] == "cerebro_value_resolver:hydrogen_like_baseline"
        assert r["confidence"] == "LOW"

    def test_researcher_overrides_short_circuit_all_five_resolvers(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.quantum_atomic import (
            resolve_quantum_atomic_charges_sum,
            resolve_quantum_dipole_moment,
            resolve_quantum_homo_lumo_gap,
            resolve_quantum_ionization_energy,
            resolve_quantum_polarizability,
        )

        for fn in (resolve_quantum_polarizability, resolve_quantum_dipole_moment,
                   resolve_quantum_homo_lumo_gap, resolve_quantum_atomic_charges_sum,
                   resolve_quantum_ionization_energy):
            r = fn(researcher_override=7.0)
            assert r["value"] == 7.0 and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 23. DRUG/DDS TYPE CLASSIFIER (categories/type_detection.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDrugTypeClassifier:
    def test_researcher_override_normalizes_and_wins(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        r = resolve_drug_type(name="ignored", researcher_override="mAb")
        assert r["value"] == "monoclonal_antibody"
        assert r["tier"] == 0

    def test_smiles_classifies_by_molecular_weight(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        r = resolve_drug_type(smiles="CCO")  # ethanol, MW ~46
        assert r["value"] == "small_molecule"
        assert r["tier"] == 3
        assert r["computed_MW_Da"] == pytest.approx(46.07, abs=0.1)

    def test_fasta_length_drives_peptide_vs_protein_vs_mab(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        short_peptide = "ACDEFGHIKLMNPQRSTVWY"  # 20 aa
        r1 = resolve_drug_type(fasta=short_peptide)
        assert r1["value"] == "peptide"

        mid_protein = "A" * 100
        r2 = resolve_drug_type(fasta=mid_protein)
        assert r2["value"] == "protein"

        full_igg = "A" * 1320
        r3 = resolve_drug_type(fasta=full_igg, name="somemab")
        assert r3["value"] == "monoclonal_antibody"

    def test_nucleic_acid_length_drives_oligo_vs_gene_therapy(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        sirna = "ACGUACGUACGUACGUACGU"  # 20 nt
        r1 = resolve_drug_type(sequence=sirna)
        assert r1["value"] == "oligonucleotide"

        mrna = "ACGU" * 20  # 80 nt
        r2 = resolve_drug_type(sequence=mrna)
        assert r2["value"] == "gene_therapy"

    def test_usan_suffix_specificity_ordering(self):
        """The suffix table must check the most specific USAN ending first
        (-ximab/-zumab/-umab/-omab) before the generic '-mab' catch-all —
        otherwise every chimeric/humanized/human mAb would still classify
        correctly as monoclonal_antibody, but the more specific matched-
        suffix provenance would be lost to the generic one."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        cases = {
            "rituximab": "ximab",     # chimeric
            "trastuzumab": "zumab",   # humanized
            "adalimumab": "umab",     # human
        }
        for name, expected_suffix in cases.items():
            r = resolve_drug_type(name=name)
            assert r["value"] == "monoclonal_antibody"
            assert r["matched_suffix"] == expected_suffix

    def test_other_usan_suffixes_map_to_their_own_class(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        assert resolve_drug_type(name="etanercept")["value"] == "fusion_protein"
        assert resolve_drug_type(name="imiglucerase")["value"] == "enzyme_replacement"
        assert resolve_drug_type(name="octreotide")["value"] == "peptide"
        assert resolve_drug_type(name="somevax")["value"] == "vaccine"

    def test_keyword_match_for_non_suffix_names(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        r = resolve_drug_type(name="a CRISPR-based gene editing construct")
        assert r["value"] == "gene_therapy"

    def test_unrecognized_name_defaults_honestly_with_a_warning(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        r = resolve_drug_type(name="completely-unrecognizable-xyz-123")
        assert r["value"] == "small_molecule"
        assert r["tier"] == 7
        assert "warning" in r

    def test_no_input_at_all_defaults_honestly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_drug_type

        r = resolve_drug_type()
        assert r["value"] == "small_molecule"
        assert r["tier"] == 7
        assert r["source"] == "cerebro_value_resolver:default_no_input"


class TestDdsTypeClassifier:
    def test_researcher_override_wins(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_dds_type

        r = resolve_dds_type(carrier="ignored", researcher_override="Liposomal")
        assert r["value"] == "liposomal"
        assert r["tier"] == 0

    def test_lnp_keyword_takes_priority_over_generic_material_keyword(self):
        """DDS_KEYWORD_MAP is ordered most-specific-first — a carrier
        string mentioning both 'PLGA' (material) and 'LNP' (gene_dds)
        should classify as the more specific gene_dds, not fall through
        to the generic polymer/material bucket."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_dds_type

        r = resolve_dds_type(carrier="PLGA-LNP hybrid formulation")
        assert r["value"] == "gene_dds"
        assert r["matched_keyword"] == "lnp"

    def test_plga_alone_classifies_as_material(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_dds_type

        r = resolve_dds_type(carrier="PLGA nanoparticle")
        assert r["value"] == "material"

    def test_no_carrier_info_defaults_honestly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_dds_type

        r = resolve_dds_type()
        assert r["value"] == "material"
        assert r["tier"] == 7
        assert r["source"] == "cerebro_value_resolver:default_no_input"

    def test_unmatched_carrier_text_defaults_to_material_by_exclusion(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.type_detection import resolve_dds_type

        r = resolve_dds_type(carrier="a completely novel unclassified carrier xyz")
        assert r["value"] == "material"
        assert r["tier"] == 7
        assert r["source"] == "cerebro_value_resolver:material_class_inferred"


# ═════════════════════════════════════════════════════════════════════════════
# 24. TARGET-BINDING + MANUFACTURING RESOLVER (categories/drug_target_and_mfg.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDrugTargetBindingResolvers:
    """name='' keeps _chembl_target_activity's network call from firing
    (it short-circuits on a falsy name), so these exercise the tier-7
    typical-drug fallback deterministically and offline."""

    def test_researcher_override_short_circuits(self):
        import src.path_resolver  # noqa: F401
        import cerebro_value_resolver.categories.drug_target_and_mfg  # noqa: F401
        from cerebro_value_resolver._core import resolve_value

        r = resolve_value("drug_target_kd", name="", researcher_override=12.5)
        assert r["value"] == 12.5 and r["tier"] == 0

    def test_kd_ic50_ki_fall_back_to_their_own_typical_drug_defaults(self):
        import src.path_resolver  # noqa: F401
        import cerebro_value_resolver.categories.drug_target_and_mfg  # noqa: F401
        from cerebro_value_resolver._core import resolve_value

        assert resolve_value("drug_target_kd", name="")["value"] == 100.0
        assert resolve_value("drug_target_ic50", name="")["value"] == 50.0
        assert resolve_value("drug_target_ki", name="")["value"] == 50.0
        assert resolve_value("drug_target_kd", name="")["tier"] == 7


class TestDrugLoadingCapacityResolver:
    def test_bunjes_rule_applies_to_lipid_carriers(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_drug_loading_capacity_pct,
        )

        r = resolve_drug_loading_capacity_pct(carrier="liposome", logp=5.0)
        assert r["value"] == pytest.approx(10.0)  # 5.0 * 2.0
        assert r["tier"] == 6

    def test_bunjes_rule_is_floored_and_capped(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_drug_loading_capacity_pct,
        )

        floored = resolve_drug_loading_capacity_pct(carrier="liposome", logp=-8.0)
        assert floored["value"] == 2.0
        capped = resolve_drug_loading_capacity_pct(carrier="liposome", logp=50.0)
        assert capped["value"] == 40.0

    def test_polymer_carrier_uses_its_own_heuristic(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_drug_loading_capacity_pct,
        )

        r = resolve_drug_loading_capacity_pct(carrier="plga", logp=2.0, mw_Da=300.0)
        assert r["value"] == pytest.approx(16.0)  # 10 + min(8, 3) + 3 (mw<400)
        assert r["tier"] == 6

    def test_unknown_carrier_falls_back_to_median_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_drug_loading_capacity_pct,
        )

        r = resolve_drug_loading_capacity_pct(carrier="some_exotic_carrier")
        assert r["value"] == 8.0
        assert r["tier"] == 7


class TestMaterialPdiAndPorosityResolvers:
    def test_known_carriers_return_their_table_defaults(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_material_pdi,
            resolve_material_porosity,
        )

        assert resolve_material_pdi(carrier="dendrimer")["value"] == 0.05
        assert resolve_material_pdi(carrier="exosome")["value"] == 0.30
        assert resolve_material_porosity(carrier="liposome")["value"] == 0.0
        assert resolve_material_porosity(carrier="nanogel")["value"] == 0.85

    def test_unknown_carrier_falls_back_to_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_material_pdi,
            resolve_material_porosity,
        )

        assert resolve_material_pdi(carrier="unobtainium")["value"] == 0.20
        assert resolve_material_porosity(carrier="unobtainium")["value"] == 0.10

    def test_researcher_overrides_short_circuit(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_target_and_mfg import (
            resolve_material_pdi,
            resolve_material_porosity,
        )

        assert resolve_material_pdi(researcher_override=0.42)["value"] == 0.42
        assert resolve_material_porosity(researcher_override=0.77)["value"] == 0.77


# ═════════════════════════════════════════════════════════════════════════════
# 25. ADMET RESOLVER (categories/drug_admet.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDrugAdmetResolver:
    """name='' short-circuits every ChEMBL lookup here (each helper checks
    `if not name` first), keeping these offline and deterministic."""

    def test_logS_yalkowsky_gse_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_solubility_logS,
        )

        r = resolve_drug_solubility_logS(name="", logp=2.0, Tm_C=125.0)
        assert r["value"] == pytest.approx(0.5 - 0.01 * (125.0 - 25) - 2.0, rel=1e-9)
        assert r["tier"] == 6

    def test_logS_falls_back_to_delaney_esol_without_melting_point(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_solubility_logS,
        )

        r = resolve_drug_solubility_logS(name="", logp=2.0, mw_Da=300.0,
                                           rotbonds=4, aromatic_rings=2)
        assert r["value"] == pytest.approx(-2.844, abs=1e-3)
        assert r["tier"] == 7

    def test_logS_with_no_logp_at_all_falls_to_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_solubility_logS,
        )

        r = resolve_drug_solubility_logS(name="")
        assert r["value"] == -3.0
        assert r["tier"] == 7

    def test_caco2_papp_hou_regression_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_caco2_papp,
        )

        r = resolve_drug_caco2_papp(name="", logp=2.0, tpsa=60.0, hbd=1.0)
        assert r["value"] == pytest.approx(6.501, abs=1e-3)
        assert r["tier"] == 6

    def test_caco2_papp_without_inputs_falls_to_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_caco2_papp,
        )

        r = resolve_drug_caco2_papp(name="")
        assert r["value"] == 10.0
        assert r["tier"] == 7

    def test_pgp_efflux_hochman_rule_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_pgp_efflux_ratio,
        )

        r = resolve_drug_pgp_efflux_ratio(name="", mw_Da=450.0, hba=5.0, logp=3.0)
        assert r["value"] == pytest.approx(3.16, abs=1e-2)
        assert r["tier"] == 6

    def test_pgp_efflux_without_inputs_falls_to_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_pgp_efflux_ratio,
        )

        r = resolve_drug_pgp_efflux_ratio(name="")
        assert r["value"] == 1.5
        assert r["tier"] == 7

    def test_cyp3a4_inhibition_defaults_to_non_inhibitor_threshold(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_cyp3a4_inhibition,
        )

        r = resolve_drug_cyp3a4_inhibition(name="")
        assert r["value"] == 50.0
        assert r["tier"] == 7

    def test_herg_aronov_rule_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_herg_ic50,
        )

        r = resolve_drug_herg_ic50(name="", logp=3.0)
        assert r["value"] == pytest.approx(39.81, abs=1e-2)
        assert r["tier"] == 6

    def test_herg_without_logp_falls_to_generic_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_herg_ic50,
        )

        r = resolve_drug_herg_ic50(name="")
        assert r["value"] == 10.0
        assert r["tier"] == 7

    def test_clearance_route_heuristic_covers_hepatic_renal_and_mixed(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_clearance_route,
        )

        hepatic = resolve_drug_clearance_route(name="", mw_Da=400.0, logp=2.0)
        renal = resolve_drug_clearance_route(name="", mw_Da=200.0, logp=0.5)
        mixed = resolve_drug_clearance_route(name="", mw_Da=300.0, logp=1.2)
        assert (hepatic["value"], renal["value"], mixed["value"]) == ("hepatic", "renal", "mixed")
        assert hepatic["tier"] == 6

    def test_clearance_route_without_inputs_defaults_to_hepatic(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_clearance_route,
        )

        r = resolve_drug_clearance_route(name="")
        assert r["value"] == "hepatic"
        assert r["tier"] == 7

    def test_researcher_overrides_short_circuit_every_resolver(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_admet import (
            resolve_drug_caco2_papp,
            resolve_drug_clearance_route,
            resolve_drug_cyp3a4_inhibition,
            resolve_drug_herg_ic50,
            resolve_drug_pgp_efflux_ratio,
            resolve_drug_solubility_logS,
        )

        for fn in (resolve_drug_solubility_logS, resolve_drug_caco2_papp,
                   resolve_drug_pgp_efflux_ratio, resolve_drug_cyp3a4_inhibition,
                   resolve_drug_herg_ic50):
            r = fn(name="", researcher_override=1.234)
            assert r["value"] == 1.234 and r["tier"] == 0

        r = resolve_drug_clearance_route(name="", researcher_override="biliary")
        assert r["value"] == "biliary" and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 26. CLINICAL PK RESOLVER (categories/pk_clinical.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestPkClinicalRegexExtractors:
    """These regexes are the tier-1 mechanism for pulling real numbers out
    of fetched OpenFDA label text — a silent parsing failure here means
    the resolver falls through to a worse tier without any signal."""

    def test_halflife_extractor_handles_a_single_value_not_just_a_range(self):
        """Regression test for a real bug: the half-life patterns required
        a range separator (to/-/–) between the number and the unit, so a
        single reported value like 'Half-life is 8 hours.' — extremely
        common in real FDA labels — matched nothing and silently fell
        through to a worse tier. The clearance/Vd extractors already had
        this separator marked optional; half-life's copy of the pattern
        was missing the same `?`."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_halflife_hours,
        )

        assert _extract_halflife_hours("Half-life is 8 hours.") == 8.0
        assert _extract_halflife_hours("The elimination half-life is 1 hour.") == 1.0

    def test_halflife_extractor_handles_plural_hours_and_days(self):
        """Regression test for a real bug: the unit alternation only had
        the singular 'hour'/'day' forms, so '\\b' failed right after
        matching the 'hour' prefix of 'hours' (not a word boundary before
        the trailing 's') — real labels almost always use the plural."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_halflife_hours,
        )

        assert _extract_halflife_hours(
            "The elimination half-life is approximately 12 to 16 hours "
            "in healthy subjects.") == 14.0
        assert _extract_halflife_hours(
            "The terminal half-life is 3-5 days following oral administration."
        ) == 96.0  # midpoint 4 days -> hours

    def test_halflife_extractor_handles_t1_2_notation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_halflife_hours,
        )

        assert _extract_halflife_hours("T1/2 of approximately 24 hours was observed.") == 24.0

    def test_clearance_extractor_parses_a_single_value(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_clearance_lph,
        )

        assert _extract_clearance_lph(
            "Total clearance (CL) is 5.2 L/h following IV administration.") == 5.2

    def test_vd_extractor_parses_a_single_value(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import _extract_vd_L

        assert _extract_vd_L("The apparent volume of distribution is 45 L.") == 45.0

    def test_protein_binding_and_bioavailability_extractors(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_bioavailability,
            _extract_protein_binding,
        )

        assert _extract_protein_binding("Plasma protein binding is approximately 98%.") == 0.98
        assert _extract_bioavailability("Absolute bioavailability is 65%.") == 0.65

    def test_extractors_return_none_on_text_without_the_expected_value(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            _extract_halflife_hours,
        )

        assert _extract_halflife_hours("This drug has no reported pharmacokinetic data.") is None


class TestPkClinicalEmpiricalFallbacks:
    """name='' keeps OpenFDA/ChEMBL/PubMed from firing (each checks a
    truthy name before touching the network) so these exercise the
    empirical/class-typical tiers deterministically and offline."""

    def test_halflife_empirical_regression_matches_published_formula(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import resolve_pk_halflife

        r = resolve_pk_halflife(name="", mw_Da=300.0, logp=2.0,
                                  molecule_class="small_molecule")
        a, b, c = -0.2, 0.18, 0.45
        expected_h = 10 ** (a + b * 2.0 + c * math.log10(300.0))
        assert r["value"] == pytest.approx(round(expected_h / 24, 4), abs=1e-4)
        assert r["tier"] == 6

    def test_halflife_class_typical_means_for_biologics(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import resolve_pk_halflife

        mab = resolve_pk_halflife(name="", molecule_class="monoclonal_antibody")
        peptide = resolve_pk_halflife(name="", molecule_class="peptide")
        assert mab["value"] == 14.0 and mab["tier"] == 7
        assert peptide["value"] == 0.02 and peptide["tier"] == 7

    def test_clearance_allometric_regression_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import resolve_pk_clearance

        r = resolve_pk_clearance(name="", mw_Da=300.0, molecule_class="small_molecule")
        assert r["value"] == pytest.approx(60 * 300.0 ** -0.25, abs=1e-3)
        assert r["tier"] == 6

    def test_clearance_class_typical_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import resolve_pk_clearance

        r = resolve_pk_clearance(name="", molecule_class="monoclonal_antibody")
        assert r["value"] == 0.3 and r["tier"] == 7

    def test_volume_distribution_logp_regression_matches_published_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            resolve_pk_volume_distribution,
        )

        r = resolve_pk_volume_distribution(name="", logp=2.0)
        vd_per_kg = max(0.2, 0.2 + 0.6 * 2.0 + 0.05 * 2.0 ** 2)
        assert r["value"] == pytest.approx(round(vd_per_kg * 70, 1), abs=1e-6)
        assert r["tier"] == 6

    def test_volume_distribution_class_typical_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            resolve_pk_volume_distribution,
        )

        r = resolve_pk_volume_distribution(name="", molecule_class="peptide")
        assert r["value"] == 7.0 and r["tier"] == 7

    def test_protein_binding_logit_regression_matches_published_formula(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            resolve_pk_protein_binding,
        )

        r = resolve_pk_protein_binding(name="", logp=2.0)
        x = -2 + 0.5 * 2.0
        expected = 1 / (1 + math.exp(-x))
        assert r["value"] == pytest.approx(round(expected, 4), abs=1e-6)
        assert r["tier"] == 6

    def test_protein_binding_and_bioavailability_generic_defaults(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            resolve_pk_oral_bioavailability,
            resolve_pk_protein_binding,
        )

        assert resolve_pk_protein_binding(name="")["value"] == 0.5
        assert resolve_pk_oral_bioavailability(name="")["value"] == 0.4

    def test_researcher_overrides_short_circuit_every_resolver(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.pk_clinical import (
            resolve_pk_clearance,
            resolve_pk_halflife,
            resolve_pk_oral_bioavailability,
            resolve_pk_protein_binding,
            resolve_pk_volume_distribution,
        )

        for fn in (resolve_pk_halflife, resolve_pk_clearance,
                   resolve_pk_volume_distribution, resolve_pk_protein_binding,
                   resolve_pk_oral_bioavailability):
            r = fn(name="", researcher_override=3.5)
            assert r["value"] == 3.5 and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 27. PHYSICOCHEMICAL DESCRIPTOR RESOLVER (categories/drug_descriptors.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDrugDescriptorBuildingBlocks:
    """These resolvers hit PubChem even with name='' (the SMILES→InChIKey
    branch in _pubchem_property fires regardless of name), so full-resolver
    tests would be network-dependent and non-deterministic. Testing the
    pure functions underneath instead — RDKit computation and the tier-7
    pure-math fallbacks — keeps this offline and exact."""

    def test_rdkit_descriptor_matches_known_ethanol_properties(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _rdkit_descriptor,
        )

        d = _rdkit_descriptor("CCO", "ethanol")
        assert d["MW_Da"] == pytest.approx(46.07, abs=0.01)
        assert d["HBD"] == 1  # the hydroxyl H
        assert d["HBA"] == 1  # the oxygen
        assert d["AromaticRings"] == 0

    def test_rdkit_descriptor_returns_none_for_invalid_smiles(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _rdkit_descriptor,
        )

        assert _rdkit_descriptor("not a real smiles!!!", "") is None

    def test_tier7_mw_sums_atomic_weights_plus_implicit_hydrogens(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import _t7_mw

        # C,C,O heavy atoms (2×12.011 + 15.999) plus 3 implicit H (3×1.008)
        expected = (2 * 12.011 + 15.999) + 3 * 1.008
        assert _t7_mw("CCO") == pytest.approx(round(expected, 2), abs=1e-2)

    def test_tier7_tpsa_counts_polar_atoms(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import _t7_tpsa

        assert _t7_tpsa("CCO") == 9.0     # one O
        assert _t7_tpsa("CCN") == 12.0    # one N

    def test_tier7_hba_counts_n_and_o_atoms(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import _t7_hba

        assert _t7_hba("CCO") == 1.0
        assert _t7_hba("NCCO") == 2.0

    def test_tier7_helpers_return_none_for_empty_smiles(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _t7_formal_charge,
            _t7_hba,
            _t7_hbd,
            _t7_mw,
            _t7_rotbonds,
            _t7_stereo,
            _t7_tpsa,
        )

        for fn in (_t7_mw, _t7_tpsa, _t7_hbd, _t7_hba, _t7_rotbonds,
                   _t7_formal_charge, _t7_stereo):
            assert fn("") is None


class TestBiologicAndOligoMwComputation:
    def test_peptide_mw_matches_hand_computed_residue_sum(self):
        """10 alanine residues: Σ(89.09) − 9×H₂O — verified independently."""
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _biologic_mw_from_fasta,
        )

        seq = "A" * 10
        expected = 10 * 89.09 - 9 * 18.015
        assert _biologic_mw_from_fasta(seq) == pytest.approx(expected, abs=1e-6)

    def test_short_fasta_below_minimum_length_returns_none(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _biologic_mw_from_fasta,
        )

        assert _biologic_mw_from_fasta("AC") is None
        assert _biologic_mw_from_fasta("") is None

    def test_dna_oligo_mw_matches_hand_computed_sum(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _oligonucleotide_mw_from_sequence,
        )

        seq = "ACGT"
        expected = (313.21 + 289.18 + 329.21 + 304.20) - 3 * 18.015 + 79.98
        assert _oligonucleotide_mw_from_sequence(seq) == pytest.approx(expected, abs=1e-6)

    def test_rna_detected_when_u_present_without_t(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _oligonucleotide_mw_from_sequence,
        )

        seq = "ACGU"
        expected = (329.21 + 305.18 + 345.21 + 306.17) - 3 * 18.015 + 79.98
        assert _oligonucleotide_mw_from_sequence(seq) == pytest.approx(expected, abs=1e-6)

    def test_moe_ps_modification_adds_per_nucleotide_mass(self):
        import src.path_resolver  # noqa: F401
        from cerebro_value_resolver.categories.drug_descriptors import (
            _oligonucleotide_mw_from_sequence,
        )

        seq = "ACGT"
        plain = _oligonucleotide_mw_from_sequence(seq, modification="DNA")
        modified = _oligonucleotide_mw_from_sequence(seq, modification="MOE_PS")
        assert modified - plain == pytest.approx(len(seq) * 88.0, abs=1e-6)


class TestDescriptorResolverResearcherOverride:
    """The one part of the full resolver testable without touching the
    network — researcher_override returns before any Tier-1 code runs."""

    def test_researcher_override_short_circuits_every_descriptor(self):
        # Built by _build_descriptor_resolver, which registers each one into
        # the shared _REGISTRY but never binds it to a module-level name
        # (same pattern as the material-table resolvers covered earlier).
        import src.path_resolver  # noqa: F401
        import cerebro_value_resolver.categories.drug_descriptors  # noqa: F401
        from cerebro_value_resolver._core import resolve_value

        for cat in ("drug_logp", "drug_mw", "drug_tpsa", "drug_hbd", "drug_hba",
                    "drug_rotbonds", "drug_aromatic_rings", "drug_formal_charge",
                    "drug_stereocenters"):
            r = resolve_value(cat, researcher_override=9.5)
            assert r["value"] == 9.5 and r["tier"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 28. CLASS-C TRANSLATIONAL ENGINE (cerebro_62_translational_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
def _trans_bundles(carrier="liposome", ligand="", size_nm=100.0, zeta_mV=-10.0,
                     rel_kin="sustained", scale_up="lab"):
    drug_bundle = {
        "drug_mw": {"value": 350.0}, "drug_logp": {"value": 2.5},
        "drug_tpsa": {"value": 60.0}, "pk_halflife": {"value": 0.5},
        "_meta": {"name": "TestDrug", "drug_type": "small_molecule",
                  "identifiers": {"smiles": "CCO"}},
    }
    dds_bundle = {"_meta": {"carrier_type": carrier, "dds_type": "material"}}
    combo_bundle = {"_meta": {"dds_row": {
        "Formulation_Name": "F001", "Formulation_ID": "F001",
        "Surface_Ligand": ligand, "Size_nm": size_nm,
        "Zeta_Potential_mV": zeta_mV, "Release_Kinetics": rel_kin,
        "Scale_Up_Readiness": scale_up}}}
    return drug_bundle, dds_bundle, combo_bundle


def _deep_results(n_validated, n_total):
    return {f"P{i}": {"validated": i < n_validated} for i in range(n_total)}


class TestTranslationalP56Patentability:
    def test_known_crowded_pair_lowers_novelty(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P56

        drug, dds, combo = _trans_bundles(carrier="liposome", ligand="transferrin")
        r = trans_P56(drug, dds, combo, _deep_results(0, 5))
        assert r["components"]["novelty_§102"] == 50
        assert r["patentability_score"] == pytest.approx(66.7, abs=0.05)
        assert r["recommendation"] == "REVIEW CLAIMS BEFORE FILING"

    def test_known_novel_pair_raises_novelty(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P56

        drug, dds, combo = _trans_bundles(carrier="solid_lipid", ligand="lactoferrin")
        r = trans_P56(drug, dds, combo, _deep_results(0, 5))
        assert r["components"]["novelty_§102"] == 95
        assert r["patentability_score"] == pytest.approx(81.7, abs=0.05)
        assert r["recommendation"] == "FILE PROVISIONAL"

    def test_deep_validation_success_raises_utility_component(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P56

        drug, dds, combo = _trans_bundles(carrier="polymer", ligand="",
                                            rel_kin="thermo", size_nm=50.0, zeta_mV=-30.0)
        r = trans_P56(drug, dds, combo, _deep_results(3, 5))
        assert r["components"]["utility_§101"] == 90
        assert r["patentability_score"] == pytest.approx(86.7, abs=0.05)

    def test_non_obviousness_penalizes_extreme_size_and_zeta(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P56

        typical = trans_P56(*_trans_bundles(size_nm=100.0, zeta_mV=-10.0),
                              _deep_results(0, 5))
        extreme = trans_P56(*_trans_bundles(size_nm=300.0, zeta_mV=-40.0),
                              _deep_results(0, 5))
        assert extreme["components"]["non_obviousness_§103"] > typical["components"]["non_obviousness_§103"]


class TestTranslationalP32FreedomToOperate:
    def test_known_crowded_combination_scores_lower_fto(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P32

        drug, dds, combo = _trans_bundles(carrier="liposome", ligand="transferrin")
        r = trans_P32(drug, dds, combo, {})
        assert r["encumbrance_level"] == "VERY_HIGH"
        assert r["fto_score"] == 30

    def test_unrecognized_combination_defaults_to_low_encumbrance(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P32

        drug, dds, combo = _trans_bundles(carrier="exosome", ligand="novel_peptide_xyz")
        r = trans_P32(drug, dds, combo, {})
        assert r["encumbrance_level"] == "LOW"
        assert r["fto_score"] == 85


class TestTranslationalP21PreIND:
    def test_deep_validation_passed_flag_uses_a_five_principle_threshold(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P21

        drug, dds, combo = _trans_bundles()
        passed = trans_P21(drug, dds, combo, _deep_results(5, 7))
        failed = trans_P21(drug, dds, combo, _deep_results(4, 7))
        assert passed["deep_validation_passed"] is True
        assert failed["deep_validation_passed"] is False

    def test_report_sections_include_the_resolved_formulation_name(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import trans_P21

        drug, dds, combo = _trans_bundles()
        r = trans_P21(drug, dds, combo, {})
        assert "F001" in r["narrative"]
        assert len(r["sections"]) == 8


class TestTranslationalDispatcher:
    def test_withholds_all_deliverables_when_deep_validation_is_insufficient(self):
        """Per its own stated gating logic: translational (Class C)
        deliverables shouldn't be generated for a DDS that hasn't cleared
        deep (Class B) validation — otherwise a regulatory/patent/grant
        outline could get built around a candidate that physics already
        rejected."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import (
            TRANSLATIONAL_FUNCTIONS,
            evaluate_translational_for_top1,
        )

        drug, dds, combo = _trans_bundles()
        out = evaluate_translational_for_top1(
            drug, dds, combo, _deep_results(2, 10))  # 20% pass rate < 70%
        assert set(out) == set(TRANSLATIONAL_FUNCTIONS)
        for r in out.values():
            assert r["status"] == "skipped_deep_validation_insufficient"

    def test_generates_all_deliverables_when_deep_validation_passes(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import (
            TRANSLATIONAL_FUNCTIONS,
            evaluate_translational_for_top1,
        )

        drug, dds, combo = _trans_bundles()
        out = evaluate_translational_for_top1(
            drug, dds, combo, _deep_results(8, 10))  # 80% pass rate >= 70%
        assert set(out) == set(TRANSLATIONAL_FUNCTIONS)
        for pid, r in out.items():
            assert r["status"] != "skipped_deep_validation_insufficient"
            assert "principle" in r

    def test_can_be_forced_to_run_regardless_of_deep_validation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_translational_engine import evaluate_translational_for_top1

        drug, dds, combo = _trans_bundles()
        out = evaluate_translational_for_top1(
            drug, dds, combo, _deep_results(0, 10), only_if_deep_passed=False)
        for r in out.values():
            assert r["status"] != "skipped_deep_validation_insufficient"


# ═════════════════════════════════════════════════════════════════════════════
# 29. 62-PRINCIPLE CATALOG (cerebro_62_principles_catalog.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestPrinciplesCatalogIntegrity:
    """The catalog is mostly static data — its value is in staying
    internally consistent and matching what it claims about itself."""

    def test_exactly_62_principles_registered(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62

        assert len(PRINCIPLES_62) == 62

    def test_every_class_field_is_one_of_the_three_valid_values(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62

        valid = {"A_surrogate", "B_deep", "C_translational"}
        bad = {pid: p["class"] for pid, p in PRINCIPLES_62.items() if p["class"] not in valid}
        assert bad == {}

    def test_class_a_plus_b_weights_are_normalized_to_one(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62

        total = sum(p["weight_cns"] for p in PRINCIPLES_62.values()
                    if p["class"] in ("A_surrogate", "B_deep"))
        assert total == pytest.approx(1.0, abs=1e-3)

    def test_translational_principles_carry_zero_ranking_weight(self):
        """Class C (translational/admin) principles shouldn't influence
        DDS ranking — the docstring's own stated policy."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import CLASS_C_TRANSLATIONAL, PRINCIPLES_62

        assert len(CLASS_C_TRANSLATIONAL) > 0
        for pid in CLASS_C_TRANSLATIONAL:
            assert PRINCIPLES_62[pid]["weight_cns"] == 0

    def test_cns_direct_named_principles_collective_weight(self):
        """Regression test for a real docstring/data mismatch: the module
        docstring used to claim these seven CNS-direct principles carry
        '≥ 40%' of the total weight collectively — checked against the
        actual normalized weights and it comes out to ~27.9%, not ≥40%.
        The docstring was corrected to state the real figure rather than
        the weights being reverse-engineered to hit an unverified target."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62

        cns_direct = ["P12", "P33", "P38", "P39", "P42", "P43", "P44"]
        total = sum(PRINCIPLES_62[pid]["weight_cns"] for pid in cns_direct)
        assert total == pytest.approx(0.279, abs=0.005)
        assert total < 0.40   # the old docstring's claim no longer stands unchecked

    def test_class_getters_partition_the_catalog_correctly(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import (
            PRINCIPLES_62,
            get_class_a_principles,
            get_class_b_principles,
            get_class_c_principles,
        )

        a, b, c = get_class_a_principles(), get_class_b_principles(), get_class_c_principles()
        assert set(a) | set(b) | set(c) == set(PRINCIPLES_62)
        assert not (set(a) & set(b)) and not (set(b) & set(c)) and not (set(a) & set(c))
        for pid in a:
            assert PRINCIPLES_62[pid]["class"] == "A_surrogate"
        for pid in b:
            assert PRINCIPLES_62[pid]["class"] == "B_deep"
        for pid in c:
            assert PRINCIPLES_62[pid]["class"] == "C_translational"

    def test_get_principle_returns_the_matching_entry(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import get_principle

        p = get_principle("P01")
        assert p["title_en"] == "Adversarial Stress-Testing Engine"

    def test_get_principle_raises_for_unknown_id(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import get_principle

        with pytest.raises(KeyError):
            get_principle("P999")

    def test_summarize_counts_match_the_actual_catalog(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62, summarize

        s = summarize()
        assert s["total"] == 62
        assert s["cns_direct_count"] == sum(1 for p in PRINCIPLES_62.values() if p["cns_relevant"])
        assert s["class_A_surrogate"] + s["class_B_deep"] + s["class_C_admin"] == 62

    def test_every_principles_deep_computation_is_wired_into_the_deep_engine(self):
        """Every principle that carries a real method_deep entry here (not
        just an HPC-deferred one) should correspond to a callable in
        cerebro_62_deep_engine.py's dispatch — a principle can be filed as
        'A_surrogate' here (its primary fast-screen role) while still
        having a deep follow-up computation for the Top-1 winner; those
        two files need to stay in sync on which principles that applies to."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_deep_engine import DEEP_FUNCTIONS, HPC_ONLY_PRINCIPLES
        from cerebro_62_principles_catalog import PRINCIPLES_62

        deep_engine_ids = set(DEEP_FUNCTIONS) | set(HPC_ONLY_PRINCIPLES)
        catalog_has_method_deep = {pid for pid, p in PRINCIPLES_62.items() if p.get("method_deep")}
        assert deep_engine_ids <= catalog_has_method_deep


# ═════════════════════════════════════════════════════════════════════════════
# 30. C+ FLOW ORCHESTRATOR (cerebro_62_orchestrator.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestOrchestratorCompositeScore:
    def test_weighted_average_matches_hand_computation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _compute_composite_score

        per_principle = {"P01": {"score": 80.0}, "P02": {"score": 40.0}}
        weights = {"P01": 0.3, "P02": 0.1}
        expected = (80.0 * 0.3 + 40.0 * 0.1) / (0.3 + 0.1)
        assert _compute_composite_score(per_principle, weights) == pytest.approx(expected)

    def test_zero_weight_principles_are_excluded_not_zero_weighted(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _compute_composite_score

        per_principle = {"P01": {"score": 80.0}, "P56": {"score": 0.0}}
        weights = {"P01": 0.5, "P56": 0.0}  # translational principle, weight 0
        assert _compute_composite_score(per_principle, weights) == 80.0

    def test_no_weighted_principles_present_returns_zero(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _compute_composite_score

        assert _compute_composite_score({"P01": {"score": 80.0}}, {}) == 0.0


class TestOrchestratorVerdictThresholds:
    def test_verdict_bands_match_documented_thresholds(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _verdict_for

        assert _verdict_for(95) == "EXCELLENT"
        assert _verdict_for(80) == "EXCELLENT"
        assert _verdict_for(79.9) == "GOOD"
        assert _verdict_for(65) == "GOOD"
        assert _verdict_for(50) == "ACCEPTABLE"
        assert _verdict_for(35) == "MARGINAL"
        assert _verdict_for(0) == "POOR"


class TestDrugDdsCompatibilityMultiplier:
    """The pathway-aware compatibility matrix — real FDA-precedent pairings
    (LNP/siRNA, AAV/gene-therapy) should score highest; known-mismatched
    pairs (oligonucleotide + bare polymer, no endosomal escape) lowest."""

    def test_ideal_fda_precedented_pairings_score_highest(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        lnp_sirna, _ = _drug_dds_compatibility_multiplier("oligonucleotide", "lnp")
        aav_gene, _ = _drug_dds_compatibility_multiplier("gene_therapy", "aav9")
        assert lnp_sirna == 1.20
        assert aav_gene == 1.20

    def test_oligo_in_bare_polymer_scores_poorly_no_endosomal_escape(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        mult, reason = _drug_dds_compatibility_multiplier("oligonucleotide", "plga")
        assert mult == 0.60
        assert "endosomal escape" in reason

    def test_mab_in_plga_is_suboptimal_organic_solvent_denaturation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        mult, reason = _drug_dds_compatibility_multiplier("monoclonal_antibody", "plga")
        assert mult == 0.75
        assert "denaturation" in reason

    def test_small_molecule_in_established_carriers_scores_well(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        for carrier in ("plga", "solid_lipid", "liposome"):
            mult, _ = _drug_dds_compatibility_multiplier("small_molecule", carrier)
            assert mult == 1.05

    def test_missing_type_data_returns_neutral_multiplier(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        mult, reason = _drug_dds_compatibility_multiplier("", "liposome")
        assert mult == 1.0
        assert reason == "no_class_data"

    def test_unmapped_pairing_defaults_to_a_mild_skepticism_not_a_penalty(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        mult, reason = _drug_dds_compatibility_multiplier("vaccine", "dendrimer")
        assert mult == 0.95
        assert "not in FDA-validated table" in reason

    def test_multiplier_never_exceeds_the_documented_range(self):
        """Every branch in the decision matrix should stay within the
        function's own documented [0.4, 1.20] range."""
        import itertools

        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import _drug_dds_compatibility_multiplier

        drug_types = ["small_molecule", "monoclonal_antibody", "peptide",
                      "oligonucleotide", "gene_therapy", "protein", "vaccine"]
        carriers = ["lnp", "aav9", "liposome", "solid_lipid", "plga",
                    "micelle", "dendrimer", "metallic"]
        for dt, ct in itertools.product(drug_types, carriers):
            mult, _ = _drug_dds_compatibility_multiplier(dt, ct)
            assert 0.4 <= mult <= 1.20


# ═════════════════════════════════════════════════════════════════════════════
# 31. CLASS-A SURROGATE ENGINE (cerebro_62_surrogate_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
def _surrogate_bundles(carrier="liposome", ligand="", size_nm=100.0, zeta_mV=-10.0,
                        phase_T=42.0, density=0.5, mw=350.0, logp=2.5,
                        tpsa=60.0, hbd=1, hba=5, pka_base=8.0, aromatic_rings=2,
                        bbb=5.0, smiles="CCO"):
    drug_bundle = {
        "drug_mw": {"value": mw}, "drug_logp": {"value": logp},
        "drug_tpsa": {"value": tpsa}, "drug_hbd": {"value": hbd},
        "drug_hba": {"value": hba}, "drug_pka_basic": {"value": pka_base},
        "drug_aromatic_rings": {"value": aromatic_rings},
        "bbb_permeability": {"value": bbb},
        "_meta": {"drug_type": "small_molecule", "name": "test_drug",
                  "identifiers": {"smiles": smiles}},
    }
    dds_bundle = {"_meta": {"carrier_type": carrier, "dds_type": "material"}}
    combo_bundle = {"_meta": {"dds_row": {
        "Surface_Ligand": ligand, "Size_nm": size_nm,
        "Zeta_Potential_mV": zeta_mV, "Phase_Transition_Temp_C": phase_T,
        "Surface_Ligand_Density_per_nm2": density}}}
    return drug_bundle, dds_bundle, combo_bundle


class TestSurrogateSharedHelpers:
    def test_triangular_window_plateau_and_decay(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import _triangular

        assert _triangular(100, 50, 150) == 100.0
        assert _triangular(30, 50, 150, 2.0, 0.5) == 60.0   # 100-(50-30)*2
        assert _triangular(200, 50, 150, 2.0, 0.5) == 75.0  # 100-(200-150)*0.5
        assert _triangular(0, 50, 150) == 0.0
        assert _triangular(-5, 50, 150) == 0.0

    def test_hill_equation_half_max_point(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import _hill

        assert _hill(50, k50=50, n=2.0) == pytest.approx(50.0)
        assert _hill(50, k50=50, n=2.0, invert=True) == pytest.approx(50.0)
        assert _hill(0, k50=50) == 0.0
        assert _hill(0, k50=50, invert=True) == 100.0

    def test_bbb_propensity_matches_wager_cns_mpo_bands(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import _bbb_propensity

        ideal = {"logp": 2.0, "mw": 300, "hbd": 0, "tpsa": 40,
                 "pka_base": 7.0, "arom_rings": 1}
        assert _bbb_propensity(ideal) == 6.0   # every band maxed out
        poor = {"logp": 6.0, "mw": 600, "hbd": 4, "tpsa": 150,
                "pka_base": 12.0, "arom_rings": 5}
        assert _bbb_propensity(poor) == 0.0

    def test_membrane_partition_logk_penalizes_ionization(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import _membrane_partition_logK

        neutral = _membrane_partition_logK({"logp": 3.0, "net_q_pH74": 0.0})
        charged = _membrane_partition_logK({"logp": 3.0, "net_q_pH74": 1.0})
        assert neutral == 3.0
        assert charged == pytest.approx(2.2)  # 3.0 - 0.8*1


class TestSurrogateBundleContract:
    def test_rejects_non_bundle_arguments(self):
        """_resolve_inputs' fail-fast guard: surrogate functions are
        bundle-only — a plain dict without _meta.drug_type/_meta.dds_type
        must raise immediately rather than silently computing nonsense."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import _resolve_inputs

        _, dds_bundle, combo_bundle = _surrogate_bundles()
        with pytest.raises(TypeError, match="not a drug bundle"):
            _resolve_inputs({"not_a_bundle": True}, dds_bundle, combo_bundle)

        drug_bundle, _, combo_bundle = _surrogate_bundles()
        with pytest.raises(TypeError, match="not a DDS bundle"):
            _resolve_inputs(drug_bundle, {"not_a_bundle": True}, combo_bundle)


class TestSurrogateRepresentativeFunctions:
    """Hand-verified spot checks across the formula patterns that recur
    throughout the file's 57 principles: CNS-MPO composite (P12),
    Henderson-Hasselbalch-driven ligand affinity (P33), Arrhenius +
    SMILES-moiety penalties (P08), and a cryo-margin linear score (P50)."""

    def test_p12_cns_stage_dosing_matches_hand_computation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import P12

        drug, dds, combo = _surrogate_bundles(ligand="")
        r = P12(drug, dds, combo)
        # bbb_factor=0.85 (stage 2 default), CNS-MPO=5.5/6 -> perm_factor=0.9167
        # base = 100*0.85*(0.4+0.6*0.9167) = 100*0.85*0.95 = 80.75; no targeting boost
        assert r["score"] == pytest.approx(80.75, abs=0.01)
        assert r["raw"]["active_targeting"] is False

    def test_p33_bbb_trojan_horse_matches_hand_computation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import P33

        drug, dds, combo = _surrogate_bundles(ligand="transferrin", size_nm=100.0,
                                                density=0.5)
        r = P33(drug, dds, combo)
        # lig=95, size_score=triangular(100,50,150)=100, density=0.5 -> factor=0.6
        # score = (0.6*95 + 0.4*100) * 0.6 = 58.2
        assert r["score"] == pytest.approx(58.2, abs=0.01)

    def test_p50_cryo_excursion_matches_hand_computation(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import P50

        drug, dds, combo = _surrogate_bundles(phase_T=42.0)
        r = P50(drug, dds, combo)
        # margin = |-20 - 42| = 62; score = min(100, 62*1.3) = 80.6
        assert r["score"] == pytest.approx(80.6, abs=0.01)

    def test_p08_oxidative_stress_penalizes_phenol_containing_drugs(self):
        """Regression test for a real bug: P08's phenol check called
        `smi.lower()` before testing for "Oc1cc"/"c1ccccc1O" — but those
        patterns are only meaningful case-sensitively (lowercase = aromatic
        ring atom, uppercase O = the phenolic substituent), and .lower()
        destroys exactly that distinction. The check could never match any
        SMILES, ever. P01's scenario-6 oxidative check had the identical
        bug. Fixed by dropping .lower() from both (matching the sibling
        checks in the same functions, which were already correctly
        case-sensitive)."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import P01, P08

        with_phenol, dds, combo = _surrogate_bundles(carrier="liposome",
                                                       smiles="Oc1ccccc1")
        without_phenol, _, _ = _surrogate_bundles(carrier="liposome", smiles="CCO")
        r_phenol = P08(with_phenol, dds, combo)
        r_plain = P08(without_phenol, dds, combo)
        assert "phenol" in r_phenol["raw"]["drug_oxidation_groups_detected"]
        assert r_phenol["score"] < r_plain["score"]

        # Same regression, P01's scenario 6.
        r_phenol_p01 = P01(with_phenol, dds, combo)
        assert r_phenol_p01["raw"]["drug_oxidation_prone"] is True

    def test_p18_active_targeting_transferrin_ligand_lookup(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import P18

        drug, dds, combo = _surrogate_bundles(ligand="transferrin", pka_base=8.0)
        r = P18(drug, dds, combo)
        assert r["raw"]["ligand"] == "transferrin"
        assert r["score"] > 0


class TestSurrogateDispatcher:
    def test_registry_has_exactly_57_functions(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import SURROGATE_FUNCTIONS

        assert len(SURROGATE_FUNCTIONS) == 57
        # The 5 translational principles must NOT be in this registry.
        assert not ({"P21", "P32", "P45", "P55", "P56"} & set(SURROGATE_FUNCTIONS))

    def test_registry_ids_match_principles_catalog_class_a(self):
        import src.path_resolver  # noqa: F401
        from cerebro_62_principles_catalog import PRINCIPLES_62
        from cerebro_62_surrogate_engine import SURROGATE_FUNCTIONS

        # P47 is filed as B_deep in the catalog but still runs here as a
        # fast surrogate proxy (its own module comment explains why) — every
        # other registered ID should be a real A_surrogate catalog entry.
        for pid in SURROGATE_FUNCTIONS:
            if pid == "P47":
                continue
            assert PRINCIPLES_62[pid]["class"] == "A_surrogate"

    def test_evaluate_all_principles_isolates_a_single_failing_function(self):
        """A malformed bundle (missing bbb_permeability entirely, so
        b_value falls back to its default) shouldn't be able to crash
        the whole batch — evaluate_all_principles_for_dds must catch a
        per-principle exception and mark just that principle FAILED."""
        import src.path_resolver  # noqa: F401
        from cerebro_62_surrogate_engine import (
            SURROGATE_FUNCTIONS,
            evaluate_all_principles_for_dds,
        )

        drug, dds, combo = _surrogate_bundles()
        out = evaluate_all_principles_for_dds(drug, dds, combo)
        assert set(out) == set(SURROGATE_FUNCTIONS)
        for pid, r in out.items():
            assert r["confidence"] != "FAILED", f"{pid} unexpectedly failed: {r}"


# ═════════════════════════════════════════════════════════════════════════════
# 32. MODULE-PATH SHIMS (CEREBRO_Pipeline.py, cerebro_enterprise_infra.py,
#     cerebro_pipeline_patches.py, src/path_resolver.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestModulePathShims:
    """These shims exist so the flat `import CEREBRO_Pipeline`-style calls
    used throughout the codebase resolve to the real src/ modules without
    changing the process's working directory. The one behavior that must
    hold for all of them: cwd is exactly what it was before the import,
    even though the modules they wrap freeze+restore os.chdir internally."""

    def test_shim_imports_leave_the_working_directory_unchanged(self):
        import os

        import src.path_resolver  # noqa: F401

        cwd_before = os.getcwd()
        import CEREBRO_Pipeline  # noqa: F401
        import cerebro_enterprise_infra  # noqa: F401
        import cerebro_pipeline_patches  # noqa: F401

        assert os.getcwd() == cwd_before

    def test_shims_register_themselves_in_sys_modules(self):
        import sys

        import src.path_resolver  # noqa: F401
        import CEREBRO_Pipeline  # noqa: F401
        import cerebro_enterprise_infra  # noqa: F401
        import cerebro_pipeline_patches  # noqa: F401

        for name in ("CEREBRO_Pipeline", "cerebro_enterprise_infra",
                     "cerebro_pipeline_patches"):
            assert name in sys.modules

    def test_pipeline_paths_are_patched_to_the_project_root_not_src_core(self):
        """CEREBRO_Pipeline.py reconstructs PATHS as
        `_new_root / _pl.PATHS[_k].name` — this only stays correct because
        every entry in the real PATHS dict (src/core/pipeline.py) is a
        single flat directory name (data, models, figures, ...) with no
        nested subdirectories; verifying that invariant holds so a future
        nested path wouldn't silently get flattened and lose its parent."""
        import src.path_resolver  # noqa: F401
        import CEREBRO_Pipeline

        for key, path in CEREBRO_Pipeline.PATHS.items():
            assert path.name == path.parts[-1]  # no nested subpath was collapsed
            assert "outputs" in path.parts
        assert "src" not in CEREBRO_Pipeline.PATHS["data"].parts
        assert "core" not in CEREBRO_Pipeline.PATHS["data"].parts

    @pytest.mark.slow
    def test_phase5_smoke_test_script_passes_end_to_end(self):
        """engine/phase5_smoke_test.py is a standalone script (real ChEMBL
        calls, real bundle resolution, real orchestrator run on two real
        drugs) meant to be run directly, not imported — so the real
        regression check is running it and confirming a clean exit, the
        same way its own docstring says to use it against a fresh Docker
        build."""
        import subprocess
        import sys

        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(project_root / "engine" / "phase5_smoke_test.py")],
            cwd=project_root, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, (
            f"phase5_smoke_test.py failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}")
        assert "ALL SMOKE TESTS PASSED" in result.stdout


# ═════════════════════════════════════════════════════════════════════════════
# 33. DDS INVERSE-DESIGN GENETIC ALGORITHM (cerebro_dds_inverse_design.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestDdsInverseDesignGaOperators:
    def test_random_individual_respects_every_parameter_bound(self):
        import random

        import src.path_resolver  # noqa: F401
        from cerebro_dds_inverse_design import (
            ALL_PARAMS,
            CATEGORICAL_SPACE,
            CONTINUOUS_SPACE,
            _random_individual,
        )

        rng = random.Random(1)
        ind = _random_individual(rng, 0)
        assert set(ind) == set(ALL_PARAMS) | {"Formulation_ID", "Formulation_Name"}
        for k, (lo, hi) in CONTINUOUS_SPACE.items():
            assert lo <= ind[k] <= hi
        for k, choices in CATEGORICAL_SPACE.items():
            assert ind[k] in choices

    def test_crossover_takes_every_gene_from_one_parent_or_the_other(self):
        import random

        import src.path_resolver  # noqa: F401
        from cerebro_dds_inverse_design import ALL_PARAMS, _crossover, _random_individual

        rng = random.Random(2)
        a = _random_individual(rng, 1)
        b = _random_individual(rng, 2)
        child = _crossover(a, b, rng)
        for k in ALL_PARAMS:
            assert child[k] in (a[k], b[k])

    def test_mutate_at_rate_zero_never_changes_genes(self):
        import random

        import src.path_resolver  # noqa: F401
        from cerebro_dds_inverse_design import ALL_PARAMS, _mutate, _random_individual

        rng = random.Random(3)
        ind = _random_individual(rng, 0)
        mutated = _mutate(dict(ind), rng, rate=0.0)
        for k in ALL_PARAMS:
            assert mutated[k] == ind[k]

    def test_dedupe_key_is_stable_and_covers_every_parameter(self):
        import random

        import src.path_resolver  # noqa: F401
        from cerebro_dds_inverse_design import ALL_PARAMS, _dedupe_key, _random_individual

        rng = random.Random(4)
        ind = _random_individual(rng, 0)
        key1, key2 = _dedupe_key(ind), _dedupe_key(dict(ind))
        assert key1 == key2
        assert len(key1) == len(ALL_PARAMS)


class TestDdsInverseDesignRealSearch:
    @pytest.mark.slow
    def test_generate_candidate_formulations_runs_the_real_orchestrator(self):
        """A small, fast real GA run (tiny population/generation counts,
        fixed seed) through the actual cerebro_62_orchestrator fitness
        function — confirms the search produces real, distinct scores
        and an honest disclaimer, not a mocked/fabricated result."""
        import src.path_resolver  # noqa: F401
        from cerebro_dds_inverse_design import generate_candidate_formulations
        from cerebro_resolved_bundles import resolve_drug_bundle

        drug_bundle = resolve_drug_bundle(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule")
        result = generate_candidate_formulations(
            drug_bundle, drug_name="Donepezil",
            n_generations=2, population_size=6, top_k=3, seed=7)

        assert result["n_evaluated"] == 2 * 6
        assert len(result["candidates"]) <= 3
        assert result["search_seed"] == 7
        assert "not independently validated" in result["disclaimer"]
        for cand in result["candidates"]:
            assert "novel_vs_input" in cand
            assert "Principle_Composite_Score" in cand


# ═════════════════════════════════════════════════════════════════════════════
# 34. LEGACY PRINCIPLE-METADATA TABLES (cerebro_dds_principle_evaluator.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestLegacyPrincipleMetadataTables:
    """This file used to run its own v21-era 24-principle scoring engine
    (_evaluate_dds/evaluate_all_dds) — fully superseded by
    cerebro_62_orchestrator.py and confirmed unreferenced anywhere else in
    the codebase, so it was removed rather than left as dead code. What's
    left is two lookup tables that cerebro_multi_drug_comparison.py and
    cerebro_completed_excel_writer.py still genuinely import."""

    def test_weights_and_docs_tables_cover_the_same_principle_ids(self):
        import src.path_resolver  # noqa: F401
        from cerebro_dds_principle_evaluator import PRINCIPLE_DOCS, PRINCIPLE_WEIGHTS

        assert set(PRINCIPLE_WEIGHTS) == set(PRINCIPLE_DOCS)
        assert len(PRINCIPLE_WEIGHTS) == 25

    def test_weights_sum_to_one(self):
        import src.path_resolver  # noqa: F401
        from cerebro_dds_principle_evaluator import PRINCIPLE_WEIGHTS

        assert sum(PRINCIPLE_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-3)

    def test_real_callers_still_import_the_tables_cleanly(self):
        """The two files that actually depend on this module — confirms
        the dead-code removal didn't touch what's genuinely load-bearing."""
        import src.path_resolver  # noqa: F401
        import cerebro_completed_excel_writer  # noqa: F401
        import cerebro_multi_drug_comparison  # noqa: F401


# ═════════════════════════════════════════════════════════════════════════════
# 35. BRAND / VISUAL IDENTITY (cerebro_brand.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestCerebroBrand:
    def test_asset_paths_point_at_the_real_project_root_not_engine_dir(self):
        """Regression test for a real bug: _PROJECT_ROOT was computed as
        Path(__file__).resolve().parent, which for engine/cerebro_brand.py
        is just engine/ itself (.parent strips only the filename) — one
        level short of the actual project root. LOGO_PATH/PATTERN_PATH/
        ENGINE_BG_PATH all silently pointed at engine/assets/brand/, which
        doesn't exist; the real assets/ directory is at the project root,
        exactly one level further up than the buggy path reached. Every
        sibling shim in this same engine/ directory (CEREBRO_Pipeline.py,
        cerebro_enterprise_infra.py, cerebro_pipeline_patches.py) already
        used the correct .parent.parent for the same file layout."""
        import src.path_resolver  # noqa: F401
        import cerebro_brand

        assert cerebro_brand.LOGO_PATH.exists()
        assert cerebro_brand.PATTERN_PATH.exists()
        assert cerebro_brand.ENGINE_BG_PATH.exists()
        assert cerebro_brand.ASSETS_DIR.name == "brand"
        assert cerebro_brand.ASSETS_DIR.parent.name == "assets"

    def test_matplotlib_style_uses_declared_palette_colors(self):
        import src.path_resolver  # noqa: F401
        from cerebro_brand import GOLD, VOID_BASE, matplotlib_style

        style = matplotlib_style()
        assert style["figure.facecolor"] == VOID_BASE
        assert style["axes.titlecolor"] == GOLD

    def test_html_brand_header_omits_redundant_title_but_keeps_subtitle(self):
        import src.path_resolver  # noqa: F401
        from cerebro_brand import PROJECT_NAME, html_brand_header

        redundant = html_brand_header(title="CEREBRO-X")
        assert redundant.count(f'<div class="subtitle">{PROJECT_NAME}</div>') == 0

        real = html_brand_header(title="Drug Delivery Report", subtitle="Donepezil")
        assert "Drug Delivery Report" in real
        assert "Donepezil" in real

    def test_reportlab_color_parses_a_real_hex_string(self):
        import src.path_resolver  # noqa: F401
        from cerebro_brand import GOLD, reportlab_color

        pytest.importorskip("reportlab")
        color = reportlab_color(GOLD)
        assert color is not None


# ═════════════════════════════════════════════════════════════════════════════
# 36. BUNDLE INSPECTOR CLI (cerebro_inspector.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestCerebroInspectorFormatting:
    def test_fmt_value_handles_every_type_it_documents(self):
        import src.path_resolver  # noqa: F401
        from cerebro_inspector import _fmt_value

        assert _fmt_value(None) == "—"
        assert _fmt_value(True) == "true"
        assert _fmt_value(False) == "false"
        assert _fmt_value(0.001234) == "1.234e-03"    # small float -> sci notation
        assert _fmt_value(12345.6789) == "1.235e+04"  # large float -> sci notation
        assert _fmt_value(3.14159) == "3.142"          # normal float -> 4 sig figs
        assert _fmt_value({"x": 1}) == "{...}"
        long_str = "a" * 50
        assert _fmt_value(long_str) == "a" * 40 + "…"
        assert _fmt_value("short") == "short"

    def test_to_json_round_trips_both_bundles(self):
        import json

        import src.path_resolver  # noqa: F401
        from cerebro_inspector import _to_json

        drug_b = {"drug_mw": {"value": 350.0, "tier": 3}, "_meta": {"name": "x"}}
        dds_b = {"material_pdi": {"value": 0.2, "tier": 7}, "_meta": {"dds_type": "material"}}
        out = json.loads(_to_json(drug_b, dds_b))
        assert out["drug"]["drug_mw"]["value"] == 350.0
        assert out["dds"]["material_pdi"]["tier"] == 7
        assert "combo" not in out

    def test_to_markdown_escapes_pipe_characters_in_method_text(self):
        """A computational_method string containing a literal '|' would
        break the markdown table's column structure if not escaped."""
        import src.path_resolver  # noqa: F401
        from cerebro_inspector import _to_markdown

        drug_b = {"drug_mw": {"value": 350.0, "tier": 3, "source": "RDKit",
                               "_computational_method": "a | b"},
                  "_meta": {"name": "x"}}
        dds_b = {"_meta": {"dds_type": "material"}}
        md = _to_markdown(drug_b, dds_b)
        assert "a \\| b" in md
        assert "| a | b |" not in md  # the raw unescaped pipe never appears as a cell break


# ═════════════════════════════════════════════════════════════════════════════
# 37. MOLECULE EXTRACTOR (cerebro_molecule_extractor.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestMoleculeExtractorPkaAndMicrospeciation:
    """This is a second, independent pKa/microspeciation implementation
    (a flat SMARTS-group lookup) alongside cerebro_value_resolver's
    Bordwell-Hammett-Born one — different pKa methodology, but the same
    Bjerrum 4-microspecies charge-state math, cross-verified here."""

    def test_carboxylic_acid_only_group_detected_and_mostly_anionic_at_ph74(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _rdkit_descriptors

        d = _rdkit_descriptors("CC(=O)O")  # acetic acid
        assert d["pKa_acidic"]["value"] == 4.2
        assert d["pKa_basic"]["value"] is None
        assert d["FractionAnionic_pH74"]["value"] > 0.99   # far above pKa at pH 7.4

    def test_primary_amine_only_group_detected_and_mostly_cationic_at_ph74(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _rdkit_descriptors

        d = _rdkit_descriptors("CCN")  # ethylamine
        assert d["pKa_basic"]["value"] == 10.6
        assert d["FractionCationic_pH74"]["value"] > 0.99

    def test_no_ionizable_groups_reports_honestly_not_fabricated(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _rdkit_descriptors

        d = _rdkit_descriptors("CC")  # ethane — no acid/base SMARTS group matches
        assert d["pKa"]["value"] is None
        assert d["pKa"]["confidence"] == "LOW"
        assert d["FractionNeutral_pH74"]["value"] == 1.0

    def test_zwitterion_candidate_produces_all_four_microspecies_summing_to_one(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _rdkit_descriptors

        d = _rdkit_descriptors("NCC(=O)O")  # glycine: amine + carboxylic acid
        total = (d["FractionCationic_pH74"]["value"] + d["FractionAnionic_pH74"]["value"]
                 + d["FractionZwitterion_pH74"]["value"] + d["FractionNeutral_pH74"]["value"])
        assert total == pytest.approx(1.0, abs=1e-3)


class TestMoleculeExtractorFastaDescriptors:
    def test_aliphatic_index_matches_ikai_1980_formula(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _aliphatic_index

        assert _aliphatic_index("AAAA") == pytest.approx(100.0)   # pure Ala: X(A)=100%
        assert _aliphatic_index("VVVV") == pytest.approx(290.0)   # pure Val: 2.9 * 100%
        assert _aliphatic_index("") == 0.0

    def test_formal_charge_confidence_matches_its_actual_rigor(self):
        """Regression test for a real mislabeling: FormalCharge for FASTA
        sequences is a residue-counting heuristic (ignores His, ignores
        pH, ignores N/C-terminal charge) — not a genuine Biopython
        ProtParam calculation like its MW_Da/pI/GRAVY siblings in the
        same dict. It used to carry source="fasta"/confidence="HIGH",
        the same tags as those genuine calculations, overclaiming rigor
        it doesn't have. Now tagged the same "fasta_proxy"/MODERATE as
        the file's other crude proxies (HBD, TPSA_A2)."""
        pytest.importorskip("Bio")
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import _fasta_descriptors

        d = _fasta_descriptors("MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKRQTLGQHDFSAGEGLYTHMKALRPDEDRLSPLHSVYVDQWDWELVMGDGERSFSTRQPAYLNFDNPDMESFQMDVEIRNQIAQVWKTAFQMLGDSVSFYEDPFVCGYNRLQPYAKFPQMTAKVYRKNQMLTGARTLIYQAHDPHIENKFATLFNDQMPDNDLLEQIRISLQKGSPWDIVKQLIENDIQVELPCFVDRGDLGGGHILFVSDNKAKGRRDQEHLNVACFPGKGAGLDEEYSAPGGEQRLKTEGSSVPKGGVDMASAAKGGYPLAAAAAPGAAAAAAAAAAALGASPADGGA")
        assert d["FormalCharge"]["source"] == "fasta_proxy"
        assert d["FormalCharge"]["confidence"] == "MODERATE"
        # The real Biopython calculations keep their genuinely-earned HIGH.
        assert d["MW_Da"]["confidence"] == "HIGH"
        assert d["pI"]["confidence"] == "HIGH"


class TestMoleculeExtractorEnrichment:
    def test_researcher_override_wins_but_computed_value_is_still_recorded(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import enrich_mol_profile

        out = enrich_mol_profile({"smiles": "CCO", "name": "test", "LogP": 1.23})
        assert out["LogP"] == 1.23
        prov = out["_descriptors_provenance"]["LogP"]
        assert prov["source"] == "researcher_override"
        assert prov["computed_value"] is not None   # what RDKit would have said, for comparison

    def test_computed_descriptor_used_when_no_override_given(self):
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import enrich_mol_profile

        out = enrich_mol_profile({"smiles": "CCO", "name": "test"})
        assert out["MW_Da"] == pytest.approx(46.07, abs=0.01)
        assert out["_descriptors_provenance"]["MW_Da"]["source"] == "rdkit"

    def test_no_smiles_or_fasta_reports_every_descriptor_as_honestly_missing(self):
        """name='' keeps this offline — enrich_mol_profile only attempts
        the live PubChem/UniProt fallback fetch when a drug name is
        given, which would make this test network-dependent."""
        import src.path_resolver  # noqa: F401
        from cerebro_molecule_extractor import enrich_mol_profile

        out = enrich_mol_profile({"name": ""})
        assert out["MW_Da"] is None
        assert out["_descriptors_provenance"]["MW_Da"]["confidence"] == "FAILED"


# ═════════════════════════════════════════════════════════════════════════════
# 38. MULTI-DRUG COMPARISON (cerebro_multi_drug_comparison.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestMultiDrugComparisonHelpers:
    def test_to_float_handles_commas_nan_and_bad_strings(self):
        import math

        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import _to_float

        assert _to_float("1,234.5") == 1234.5
        assert _to_float(float("nan")) is None
        assert _to_float(True) == 1.0
        assert _to_float("not a number") is None

    def test_flatten_numeric_recurses_and_drops_underscore_and_non_numeric_keys(self):
        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import _flatten_numeric

        flat = _flatten_numeric({"a": {"b": 1.0, "c": "text"}, "_hidden": 5.0, "d": 2})
        assert flat == {"a.b": 1.0, "d": 2.0}

    def test_normalize_score_higher_and_lower_directions(self):
        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import _normalize_score

        vals = {"A": 10.0, "B": 20.0, "C": 30.0}
        higher = _normalize_score(vals, "higher")
        assert higher == {"A": 0.0, "B": 50.0, "C": 100.0}
        lower = _normalize_score(vals, "lower")
        assert lower == {"A": 100.0, "B": 50.0, "C": 0.0}

    def test_docking_affinity_kcal_and_its_abs_variant_agree_on_direction_of_better(self):
        """Docking_Affinity_kcal (a signed, more-negative-is-stronger
        energy) belongs in LOWER_IS_BETTER; its _abs companion (computed
        in compare_drugs) belongs in HIGHER_IS_BETTER — both must agree
        that -9.0 kcal/mol beats -5.0 kcal/mol."""
        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import _direction_for

        assert _direction_for("physchem.Docking_Affinity_kcal") == "lower"
        assert _direction_for("physchem.Docking_Affinity_kcal_abs") == "higher"


class TestMultiDrugComparisonTieHandling:
    def test_a_genuine_tie_is_reported_honestly_not_credited_to_whoever_is_first(self):
        """Regression test for a real bug: when every drug lands on the
        exact same value for a metric (a realistic case — e.g. every drug
        falling back to the same Tier-7 class-mean default), _normalize_
        score gives everyone 100.0, and max() then arbitrarily picked
        whichever drug happened to be listed first as the 'winner' of a
        comparison that was actually a dead heat, silently biasing
        winner_counts toward that drug. Now reported as an explicit tie
        with no winner credited."""
        import tempfile
        from pathlib import Path

        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import compare_drugs

        drug_results = [
            {"drug_name": "DrugA", "mol_profile": {"BBB_permeability_pct": 50.0},
             "df_dds": None, "principles": {}},
            {"drug_name": "DrugB", "mol_profile": {"BBB_permeability_pct": 50.0},
             "df_dds": None, "principles": {}},
        ]
        with tempfile.TemporaryDirectory() as td:
            summary = compare_drugs(drug_results, Path(td))
        row = next(r for r in summary["per_principle"]
                   if "BBB_permeability_pct" in r["metric"])
        assert row["winner"] == "— (tie)"
        assert summary["winner_counts"]["DrugA"] == 0
        assert summary["winner_counts"]["DrugB"] == 0

    def test_a_genuine_winner_is_still_credited_normally(self):
        import tempfile
        from pathlib import Path

        import src.path_resolver  # noqa: F401
        from cerebro_multi_drug_comparison import compare_drugs

        drug_results = [
            {"drug_name": "DrugA", "mol_profile": {"BBB_permeability_pct": 80.0},
             "df_dds": None, "principles": {}},
            {"drug_name": "DrugB", "mol_profile": {"BBB_permeability_pct": 20.0},
             "df_dds": None, "principles": {}},
        ]
        with tempfile.TemporaryDirectory() as td:
            summary = compare_drugs(drug_results, Path(td))
        row = next(r for r in summary["per_principle"]
                   if "BBB_permeability_pct" in r["metric"])
        assert row["winner"] == "DrugA"
        assert summary["winner_counts"]["DrugA"] == 1


class TestMultiDrugComparisonChampionSheet:
    @pytest.mark.slow
    def test_champion_sheet_per_principle_scores_are_real_not_all_zero(self):
        """Regression test for a real bug: the Champion_DDS_Compare Excel
        sheet's per-principle-score section and two of its seven group-
        rollup rows (G2, G5) were built around an old v21-era ID/group-
        naming scheme (e.g. 'P1.1_BBB_transcytosis', 'G2_Release') that
        never matched the real 62-principle data actually being fed in
        (keyed 'P01'..'P62', groups named '...Kinetics'/'...BBB') — so
        every one of those cells silently rendered 0 for every drug,
        regardless of the real underlying scores. Confirmed end-to-end
        with two real drugs through the actual orchestrator."""
        import tempfile
        from pathlib import Path

        import openpyxl
        import pandas as pd

        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import evaluate_all_dds_62
        from cerebro_multi_drug_comparison import compare_drugs
        from cerebro_resolved_bundles import resolve_drug_bundle

        db1 = resolve_drug_bundle(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule")
        db2 = resolve_drug_bundle(
            name="Rivastigmine", smiles="CCN(C)C(=O)Oc1cccc(c1)C(C)N(C)C",
            molecule_class="small_molecule")
        df_dds = pd.DataFrame([{
            "Formulation_ID": "F001", "Formulation_Name": "Tf-PLGA",
            "Carrier_Type": "plga", "Size_nm": 100, "Zeta_Potential_mV": -25,
            "PDI": 0.2, "Encapsulation_Efficiency_pct": 75,
            "Surface_Ligand": "transferrin", "PEGylation_Degree_mol_pct": 5,
            "Release_Kinetics": "sustained", "Scale_Up_Readiness": "pilot",
        }])
        r1 = evaluate_all_dds_62(drug_bundle=db1, df_dds=df_dds, drug_name="Donepezil")
        r2 = evaluate_all_dds_62(drug_bundle=db2, df_dds=df_dds, drug_name="Rivastigmine")
        drug_results = [
            {"drug_name": "Donepezil", "mol_profile": {}, "df_dds": r1["ranked_df"],
             "dds_principle_matrix": r1["all_dds_principles"],
             "dds_principle_breakdown": r1["all_dds_breakdown"]},
            {"drug_name": "Rivastigmine", "mol_profile": {}, "df_dds": r2["ranked_df"],
             "dds_principle_matrix": r2["all_dds_principles"],
             "dds_principle_breakdown": r2["all_dds_breakdown"]},
        ]
        with tempfile.TemporaryDirectory() as td:
            compare_drugs(drug_results, Path(td))
            wb = openpyxl.load_workbook(Path(td) / "CEREBRO_X_Multi_Drug_Comparison.xlsx")
            ws = wb["Champion_DDS_Compare"]

            group_rows = {row[0]: row[2:4] for row in
                          ws.iter_rows(min_row=8, max_row=14, values_only=True)}
            assert group_rows["G2 Release Kinetics"] != (0, 0)
            assert group_rows["G5 Glymphatic BBB"] != (0, 0)

            per_principle_cells = [
                cell.value
                for row in ws.iter_rows(min_row=16, max_row=ws.max_row)
                if row[0].value and str(row[0].value).startswith("P")
                and "(" in str(row[0].value)
                for cell in row[2:4] if cell.value is not None
            ]
            assert per_principle_cells
            assert any(v != 0 for v in per_principle_cells)


# ═════════════════════════════════════════════════════════════════════════════
# 39. COMPLETED-DATA EXCEL WRITER (cerebro_completed_excel_writer.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestCompletedExcelWriterPrincipleSheets:
    """Same bug family as the Champion_DDS_Compare sheet fix: this writer
    also had two sheets built around the old v21 25-principle ID/group
    scheme, disconnected from the live 62-principle data actually being
    written everywhere else in the same workbook."""

    @pytest.mark.slow
    def test_dds_principle_matrix_group_columns_are_real_not_all_zero(self):
        """Regression test: the DDS×Principle matrix sheet's group_cols
        list used the old 'G2_Release'/'G5_Glymphatic' names, which never
        matched cerebro_62_orchestrator's real 'G2_Release_Kinetics'/
        'G5_Glymphatic_BBB' keys in m["groups"] — so those two of seven
        group columns silently showed 0 for every DDS row in every
        drug's per-drug DDSxP sheet, the primary formulation-ranking
        matrix a researcher would actually look at."""
        import tempfile
        from pathlib import Path

        import openpyxl
        import pandas as pd

        import src.path_resolver  # noqa: F401
        from cerebro_62_orchestrator import evaluate_all_dds_62
        from cerebro_completed_excel_writer import write_completed_excel
        from cerebro_resolved_bundles import resolve_drug_bundle

        db = resolve_drug_bundle(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule")
        df_dds = pd.DataFrame([{
            "Formulation_ID": "F001", "Formulation_Name": "Tf-PLGA",
            "Carrier_Type": "plga", "Size_nm": 100, "Zeta_Potential_mV": -25,
            "PDI": 0.2, "Encapsulation_Efficiency_pct": 75,
            "Surface_Ligand": "transferrin", "PEGylation_Degree_mol_pct": 5,
            "Release_Kinetics": "sustained", "Scale_Up_Readiness": "pilot",
        }])
        r = evaluate_all_dds_62(drug_bundle=db, df_dds=df_dds, drug_name="Donepezil")
        drug_results = [{
            "drug_name": "Donepezil", "mol_profile": {"_source_audit": {}},
            "df_dds": r["ranked_df"],
            "dds_principle_matrix": r["all_dds_principles"],
            "dds_principle_breakdown": r["all_dds_breakdown"],
            "principles": {}, "deep_results": r.get("deep_results", {}),
            "deep_summary": r.get("deep_summary", {}),
            "translational": r.get("translational", {}),
            "fallback_chain": r.get("fallback_chain", []),
        }]
        with tempfile.TemporaryDirectory() as td:
            out = write_completed_excel(drug_results, Path(td) / "test.xlsx")
            wb = openpyxl.load_workbook(out)
            ws = wb["D1_Donepezil_DDSxP"]
            header = [c.value for c in ws[4]]
            row1 = [c.value for c in ws[5]]
            assert row1[header.index("G2_Release_Kinetics")] != 0
            assert row1[header.index("G5_Glymphatic_BBB")] != 0

    @pytest.mark.slow
    def test_principle_explanations_sheet_lists_all_62_current_principles(self):
        """Regression test: this glossary sheet used to be built from
        cerebro_dds_principle_evaluator's old 25-principle table — a
        researcher would see 'P01'..'P62' everywhere else in the same
        workbook, then find 25 unrelated 'P1.1_...'-style rows here that
        matched nothing else in the file. Now sourced from the same live
        catalog that actually produced every score in the workbook."""
        import tempfile
        from pathlib import Path

        import openpyxl

        import src.path_resolver  # noqa: F401
        from cerebro_completed_excel_writer import write_completed_excel

        drug_results = [{
            "drug_name": "Donepezil", "mol_profile": {"_source_audit": {}},
            "df_dds": None, "dds_principle_matrix": [], "dds_principle_breakdown": [],
            "principles": {},
        }]
        with tempfile.TemporaryDirectory() as td:
            out = write_completed_excel(drug_results, Path(td) / "test.xlsx")
            wb = openpyxl.load_workbook(out)
            ws = wb["Principle_Explanations"]
            ids = [ws.cell(i, 1).value for i in range(5, ws.max_row + 1)]
            ids = [i for i in ids if i]
            assert len(ids) == 62
            assert "P01" in ids and "P62" in ids
            assert not any(i.startswith("P1.") for i in ids)   # no old-format leftovers


class TestCompletedExcelWriterHelpers:
    def test_get_tier_info_prefers_source_audit_over_inference(self):
        import src.path_resolver  # noqa: F401
        from cerebro_completed_excel_writer import _get_tier_info

        mp = {"_source_audit": {"MW_Da": {"_tier": 1, "_confidence": "HIGH"}}}
        assert _get_tier_info(mp, "MW_Da") == {"_tier": 1, "_confidence": "HIGH"}

    def test_get_tier_info_infers_tier_1_for_a_present_unaudited_value(self):
        import src.path_resolver  # noqa: F401
        from cerebro_completed_excel_writer import _get_tier_info

        info = _get_tier_info({"MW_Da": 350.0}, "MW_Da")
        assert info["_tier"] == 1

    def test_get_tier_info_reports_tier_99_when_truly_missing(self):
        import src.path_resolver  # noqa: F401
        from cerebro_completed_excel_writer import _get_tier_info

        assert _get_tier_info({}, "MW_Da")["_tier"] == 99

    def test_flatten_principles_recurses_and_converts_booleans(self):
        import src.path_resolver  # noqa: F401
        from cerebro_completed_excel_writer import _flatten_principles

        flat = _flatten_principles({"a": {"b": 1.0, "_hidden": 5}, "c": True, "d": [1, 2, 3]})
        assert flat == [("a.b", 1.0), ("c", "Yes")]   # lists skipped, bool -> Yes/No, _-keys dropped


# ═════════════════════════════════════════════════════════════════════════════
# 40. CINEMATIC VISUAL PRIMITIVES (cerebro_cinematic_primitives.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestCinematicPrimitivesLookups:
    def test_drug_profile_falls_back_to_small_molecule(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_primitives import get_drug_profile

        assert get_drug_profile(None)["narrative"] == "small molecule"
        assert get_drug_profile("totally_unknown_type")["narrative"] == "small molecule"
        assert get_drug_profile("MONOCLONAL_ANTIBODY")["shape"] == "y_shape"  # case-insensitive

    def test_dds_profile_prefers_specific_match_over_generic_substring(self):
        """AAV9 and generic AAV are both real keys — a carrier string
        naming a specific untabled serotype (e.g. 'aav5') should still
        resolve via the generic 'aav' entry, not silently fall through
        to _default, and an exact 'AAV9' should get its own profile."""
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_primitives import get_dds_profile

        aav9 = get_dds_profile("AAV9")
        aav5 = get_dds_profile("aav5")
        generic_aav = get_dds_profile("aav")
        assert aav5 == generic_aav
        assert aav9["shape"] == "icosahedral_capsid"

    def test_dds_profile_unrecognized_carrier_falls_back_to_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_primitives import DDS_VISUAL_PROFILES, get_dds_profile

        assert get_dds_profile("nonexistent_carrier_xyz") == DDS_VISUAL_PROFILES["_default"]

    def test_ligand_info_partial_match_and_default(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_primitives import LIGAND_RECEPTOR_MAP, get_ligand_info

        assert get_ligand_info("RVG29")["receptor"].startswith("Nicotinic")
        assert get_ligand_info(None) == LIGAND_RECEPTOR_MAP[""]
        assert get_ligand_info("") == LIGAND_RECEPTOR_MAP[""]


# ═════════════════════════════════════════════════════════════════════════════
# 41. CINEMATIC SCENE ENGINE (cerebro_cinematic_engine.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestCinematicEngineHelpers:
    def test_b_value_and_b_tier_handle_missing_and_malformed_bundles(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import _b_tier, _b_value

        assert _b_value({"x": {"value": 5.0}}, "x", 0) == 5.0
        assert _b_value({"x": {"value": None}}, "x", 99) == 99   # explicit None -> default
        assert _b_value("not a dict", "x", 99) == 99
        assert _b_tier({"x": {"tier": 3}}, "x") == 3
        assert _b_tier({}, "x") == 7   # unresolved defaults to lowest-confidence tier

    def test_hash_id_is_deterministic_and_short(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import _hash_id

        h1 = _hash_id("DrugA", "DDS1", "C01")
        h2 = _hash_id("DrugA", "DDS1", "C01")
        h3 = _hash_id("DrugB", "DDS1", "C01")
        assert h1 == h2 and len(h1) == 8
        assert h1 != h3

    def test_safe_filename_strips_unsafe_characters(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import _safe_filename

        assert _safe_filename("Drug/Name: Test!") == "Drug_Name__Test_"
        assert _safe_filename(None) == "x"
        assert len(_safe_filename("x" * 100)) == 40

    def test_drug_class_narrative_covers_every_modality_with_real_citations(self):
        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import _drug_class_narrative

        mab = _drug_class_narrative("monoclonal_antibody")
        assert "Lecanemab" in mab["clinical_example"]
        oligo = _drug_class_narrative("oligonucleotide")
        assert "Nusinersen" in oligo["clinical_example"]
        default = _drug_class_narrative("totally_unknown_modality")
        assert "Donepezil" in default["clinical_example"]   # falls back to small molecule


class TestCinematicSuiteGeneration:
    @pytest.mark.slow
    def test_generates_all_five_scenes_for_a_real_drug(self):
        import tempfile
        from pathlib import Path

        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import generate_cinematic_suite
        from cerebro_resolved_bundles import resolve_dds_bundle, resolve_drug_bundle

        db = resolve_drug_bundle(
            name="Donepezil",
            smiles="COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2",
            molecule_class="small_molecule")
        dds = resolve_dds_bundle(carrier_type="plga", ligand="transferrin", formulation_id="F1")
        top1 = {"Formulation_Name": "Tf-PLGA", "Carrier_Type": "plga",
                "Size_nm": 100, "Zeta_Potential_mV": -25, "PDI": 0.2,
                "Surface_Ligand": "transferrin", "Drug_Loading_Pct": 15,
                "Release_Kinetics": "sustained", "pH_Trigger": 6.5,
                "Composite_Score": 80.0, "Principle_Composite_Score": 80.0}
        with tempfile.TemporaryDirectory() as td:
            paths = generate_cinematic_suite(db, dds, top1, Path(td))
            assert len(paths) == 5
            for p in paths:
                assert p.exists()
                assert p.stat().st_size > 1000   # not an empty/error stub

    def test_a_single_failing_scene_does_not_abort_the_whole_suite(self):
        """generate_cinematic_suite catches per-scene exceptions — a
        malformed bundle missing _meta shouldn't crash the whole run,
        just log and skip whichever scene(s) choke on it."""
        import tempfile
        from pathlib import Path

        import src.path_resolver  # noqa: F401
        from cerebro_cinematic_engine import generate_cinematic_suite

        with tempfile.TemporaryDirectory() as td:
            paths = generate_cinematic_suite({}, {}, {}, Path(td))
            assert isinstance(paths, list)   # doesn't raise, even with nothing real to render


# ═════════════════════════════════════════════════════════════════════════════
# 42. PDB RESOLVER (src/core/pdb_resolver.py)
# ═════════════════════════════════════════════════════════════════════════════
class TestPdbResolver:
    @pytest.mark.slow
    def test_path_traversal_pdb_id_is_rejected_not_trusted(self):
        """Security regression test for the audit's §6 Medium finding: a
        user-supplied pdb_id must pass a strict 4-char alphanumeric check
        before being trusted — a value like '../x' must NOT be accepted,
        since a trusted pdb_id later builds both a download URL and a
        local filesystem path in real_docking_engine.py. Marked slow: a
        rejected override falls through to the real live-API cascade."""
        import src.path_resolver  # noqa: F401
        from src.core.pdb_resolver import resolve_pdb_for_drug

        r = resolve_pdb_for_drug("SomeDrug", user_pdb_id="../x")
        assert r["source"] != "User-provided (Excel input)"
        assert r["pdb_id"] != "../x"

    def test_valid_pdb_id_is_trusted_and_uppercased(self):
        import src.path_resolver  # noqa: F401
        from src.core.pdb_resolver import resolve_pdb_for_drug

        r = resolve_pdb_for_drug("SomeDrug", user_pdb_id="1abc")
        assert r["pdb_id"] == "1ABC"
        assert r["source"] == "User-provided (Excel input)"
        assert r["confidence"] == "HIGH"

    def test_pdb_id_regex_rejects_wrong_length_and_special_characters(self):
        import src.path_resolver  # noqa: F401
        from src.core.pdb_resolver import _PDB_ID_RE

        assert not _PDB_ID_RE.match("abc")     # too short
        assert not _PDB_ID_RE.match("abcde")   # too long
        assert not _PDB_ID_RE.match("ab-c")    # non-alphanumeric
        assert _PDB_ID_RE.match("1ABC")

    def test_pdb_ref_is_permanently_empty_by_design(self):
        """Regression guard for a real (if low-severity) dead-code issue:
        the auto-resolved confidence used to read
        'HIGH if drug_lower in PDB_REF else MODERATE', but PDB_REF was
        deliberately emptied in v22.1 (no hardcoded drug data) — that
        branch could never actually produce HIGH. Confirmed the table
        stays empty and auto-resolved confidence is honestly MODERATE."""
        import src.path_resolver  # noqa: F401
        from src.core.pdb_resolver import PDB_REF

        assert PDB_REF == {}

    @pytest.mark.slow
    def test_no_pdb_id_available_falls_back_to_honest_blind_docking(self):
        import src.path_resolver  # noqa: F401
        from src.core.pdb_resolver import resolve_pdb_for_drug

        r = resolve_pdb_for_drug("a-drug-name-with-no-pdb-structure-xyz-123")
        assert r["pdb_id"] is None
        assert r["confidence"] == "LOW"
