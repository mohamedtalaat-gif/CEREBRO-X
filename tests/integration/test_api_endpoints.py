# -*- coding: utf-8 -*-
"""
Integration tests — test full API endpoints with TestClient.
Requires: pip install httpx
"""
import pytest


class TestHealthEndpoints:

    def test_root(self, test_client):
        r = test_client.get("/")
        assert r.status_code == 200
        assert r.json()["version"] == "2.0.0"

    def test_liveness(self, test_client):
        r = test_client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "alive"


class TestAuthFlow:

    def test_register_and_login(self, test_client):
        # Register — note: the public schema has no `role` field, so a
        # "role" in the request body must be silently ignored, never granted.
        r = test_client.post("/auth/register", json={
            "email": "int_test@cerebro.local",
            "username": "int_testuser",
            "password": "strongpw123",
            "role": "researcher",
        })
        assert r.status_code in (200, 409)  # 409 if already exists
        if r.status_code == 200:
            assert r.json()["role"] == "readonly"

        # Login
        r = test_client.post("/auth/login", data={
            "username": "int_testuser",
            "password": "strongpw123",
        })
        if r.status_code == 200:
            data = r.json()
            assert "access_token" in data
            assert data["role"] == "readonly"

    def test_register_ignores_requested_admin_role(self, test_client):
        """A self-registration payload must never be able to grant admin."""
        r = test_client.post("/auth/register", json={
            "email": "escalation_attempt@cerebro.local",
            "username": "escalation_attempt",
            "password": "strongpw123",
            "role": "admin",
        })
        assert r.status_code in (200, 409)
        if r.status_code == 200:
            assert r.json()["role"] == "readonly"

    def test_protected_route_without_auth(self, test_client):
        r = test_client.get("/results")
        assert r.status_code == 401


class TestPipelineEndpoints:

    def test_dds_ranking_404_before_run(self, test_client, auth_headers):
        if not auth_headers:
            pytest.skip("Auth not configured")
        r = test_client.get("/dds/ranking", headers=auth_headers)
        # 404 if no data yet, 200 if data exists
        assert r.status_code in (200, 404)
