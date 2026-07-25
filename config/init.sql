-- =============================================================================
-- CEREBRO-X v22.1  —  Database Initialization
-- =============================================================================
-- Runs once when PostgreSQL container starts for the first time.
-- Creates schemas, extensions, and base tables.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";        -- trigram text search

-- ── Schema: auth ────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS auth;

-- Users table (managed by SQLAlchemy but pre-create for indexes)
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    username        VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255),
    role            VARCHAR(50) DEFAULT 'readonly' NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role     ON users(role);

-- API Keys
CREATE TABLE IF NOT EXISTS api_keys (
    id          SERIAL PRIMARY KEY,
    key_hash    VARCHAR(255) UNIQUE NOT NULL,
    key_prefix  VARCHAR(10) NOT NULL,
    name        VARCHAR(100) NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    scopes      JSONB DEFAULT '[]'::jsonb,
    is_active   BOOLEAN DEFAULT TRUE,
    last_used   TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_apikeys_hash ON api_keys(key_hash);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    action      VARCHAR(100) NOT NULL,
    resource    VARCHAR(200),
    ip_address  VARCHAR(45),
    user_agent  VARCHAR(500),
    details     JSONB DEFAULT '{}'::jsonb,
    timestamp   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user      ON audit_logs(user_id);

-- Refresh tokens
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id          SERIAL PRIMARY KEY,
    token_hash  VARCHAR(255) UNIQUE NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMP NOT NULL,
    revoked     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_hash ON refresh_tokens(token_hash);

-- ── Schema: pipeline ────────────────────────────────────────────────────────

-- Drug records
CREATE TABLE IF NOT EXISTS drugs (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    mw          FLOAT,
    logp        FLOAT,
    half_life   FLOAT,
    affinity    FLOAT,
    ml_score    FLOAT,
    smiles      TEXT,
    indication  VARCHAR(255),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drugs_name ON drugs(name);

-- Pipeline runs
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          SERIAL PRIMARY KEY,
    run_id      VARCHAR(100) UNIQUE NOT NULL,
    status      VARCHAR(50) DEFAULT 'pending',
    config      JSONB DEFAULT '{}'::jsonb,
    metrics     JSONB DEFAULT '{}'::jsonb,
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    error       TEXT,
    created_by  INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_time   ON pipeline_runs(started_at DESC);

-- ── Schema: mlops ───────────────────────────────────────────────────────────

-- Model versions
CREATE TABLE IF NOT EXISTS model_versions (
    id                  SERIAL PRIMARY KEY,
    model_name          VARCHAR(100) NOT NULL,
    version             VARCHAR(20) NOT NULL,
    stage               VARCHAR(50) DEFAULT 'development',
    metrics             JSONB DEFAULT '{}'::jsonb,
    hyperparams         JSONB DEFAULT '{}'::jsonb,
    training_data_hash  VARCHAR(64),
    artifact_path       TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    description         TEXT DEFAULT '',
    tags                JSONB DEFAULT '{}'::jsonb,
    run_id              VARCHAR(100),
    UNIQUE(model_name, version)
);

CREATE INDEX IF NOT EXISTS idx_models_name_stage ON model_versions(model_name, stage);

-- Drift events
CREATE TABLE IF NOT EXISTS drift_events (
    id            SERIAL PRIMARY KEY,
    model_name    VARCHAR(100) NOT NULL,
    drift_type    VARCHAR(50) NOT NULL,
    metric_name   VARCHAR(100),
    metric_value  FLOAT,
    threshold     FLOAT,
    severity      VARCHAR(20) DEFAULT 'warning',
    details       JSONB DEFAULT '{}'::jsonb,
    detected_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_model_time ON drift_events(model_name, detected_at DESC);

-- ── Cleanup: expired tokens (run periodically) ─────────────────────────────
-- Can be called by pg_cron or Celery beat:
--   SELECT cleanup_expired_tokens();
CREATE OR REPLACE FUNCTION cleanup_expired_tokens()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM refresh_tokens
    WHERE expires_at < NOW() OR revoked = TRUE;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ── Log ─────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE 'CEREBRO-X database initialized successfully';
END $$;
