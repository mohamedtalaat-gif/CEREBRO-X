"""
Shared test fixtures for CEREBRO-X test suite.
"""
import os
import sys
from pathlib import Path

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Path setup — ensure src/ is importable
# ─────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Register module aliases so old-style imports work in tests
import src.path_resolver  # noqa: F401

# ─────────────────────────────────────────────────────────────────────────────
# Environment defaults for testing
# ─────────────────────────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite:///test_cerebro.db")
os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_32chars_minimum_ok")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")  # DB 15 = test
os.environ.setdefault("CELERY_ALWAYS_EAGER", "1")
os.environ.setdefault("CEREBRO_ADMIN_PASSWORD", "test_admin_pw")


# ═════════════════════════════════════════════════════════════════════════════
# Database fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path for tests."""
    return tmp_path / "test.db"


@pytest.fixture
def db_session(tmp_path):
    """SQLAlchemy session with auth tables created."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    db_url = f"sqlite:///{tmp_path / 'test_auth.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    try:
        from src.api.auth import AuthBase
        AuthBase.metadata.create_all(bind=engine)
    except Exception:
        pass

    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ═════════════════════════════════════════════════════════════════════════════
# API fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def test_client():
    """FastAPI TestClient for integration tests."""
    try:
        from fastapi.testclient import TestClient

        from src.api.app import app
        with TestClient(app) as client:
            yield client
    except ImportError:
        pytest.skip("fastapi/httpx not installed")


@pytest.fixture
def auth_headers(db_session):
    """JWT auth headers for authenticated API calls."""
    try:
        from src.api.auth import AuthService, UserCreate
        svc = AuthService(db_session)
        svc.create_user(UserCreate(
            email="test@cerebro.local",
            username="testuser",
            password="testpassword123",
            role="admin",
        ))
        result = svc.login("testuser", "testpassword123")
        return {"Authorization": f"Bearer {result.access_token}"}
    except Exception:
        return {}


# ═════════════════════════════════════════════════════════════════════════════
# Data fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_drug_data():
    """Minimal drug data dict for testing — uses generic placeholder name."""
    return {
        "Drug": "TEST_DRUG_ANTIBODY",
        "MW_Da": 143379.0,
        "LogP": -0.7,
        "Half_Life_Days": 7.0,
        "Docking_Affinity_kcal": -8.5,
        "Indication": "Test indication",
        "Molecule_Class": "monoclonal_antibody",
    }


@pytest.fixture
def sample_formulation_df():
    """Small formulation DataFrame for DDS testing."""
    import pandas as pd
    return pd.DataFrame([
        {
            "Formulation_ID": "F001",
            "Formulation_Name": "LNP-ApoE",
            "Drug": "TEST_DRUG_X",
            "Carrier_Type": "LNP",
            "size_nm": 85,
            "zeta_potential_mv": -12,
            "pdi": 0.15,
            "encapsulation_efficiency_pct": 88,
            "drug_loading_pct": 5.2,
            "pegylation_degree_mol_pct": 5.0,
            "ligand_density_per_nm2": 1.0,
            "surface_logp": -1.2,
            "pgp_escape_coeff": 0.8,
            "carpa_risk_index": 0.2,
            "off_target_liver_pct": 25,
            "phase_transition_temp_c": 55,
            "Surface_Ligand": "ApoE",
            "apo_e_affinity": "very_high",
            "route": "IV",
            "BBB_Engineering_Score": 85.0,
        },
        {
            "Formulation_ID": "F002",
            "Formulation_Name": "Exosome-RVG",
            "Drug": "TEST_DRUG_X",
            "Carrier_Type": "Exosome",
            "size_nm": 95,
            "zeta_potential_mv": -8,
            "pdi": 0.12,
            "encapsulation_efficiency_pct": 72,
            "drug_loading_pct": 3.1,
            "pegylation_degree_mol_pct": 3.0,
            "ligand_density_per_nm2": 0.8,
            "surface_logp": -0.9,
            "pgp_escape_coeff": 0.7,
            "carpa_risk_index": 0.15,
            "off_target_liver_pct": 20,
            "phase_transition_temp_c": 60,
            "Surface_Ligand": "RVG29",
            "apo_e_affinity": "moderate",
            "route": "IV",
            "BBB_Engineering_Score": 78.0,
        },
    ])


@pytest.fixture
def sample_predictions():
    """Numpy arrays for drift detection tests."""
    import numpy as np
    np.random.seed(42)
    ref = np.random.normal(0.65, 0.1, 200)
    return ref
