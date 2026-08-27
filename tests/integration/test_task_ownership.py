"""
Integration tests — task ownership authorization on Celery status polling.

Covers the fix for: GET /pipeline/status/{task_id} used to accept any
authenticated user and return full task status/results for ANY task_id, with
no check that the requester was the one who submitted that task. A
low-privileged user who obtained another user's task_id (e.g. via logs, error
messages, or a shared support ticket) could poll it and read that user's
pipeline results.

The fix records (task_id, user_id) at submission time (TaskOwnershipModel)
and enforces owner-or-admin access when polling status.
"""
import uuid

import pytest


class _FakeDelayResult:
    """Stand-in for the object returned by Task.delay()/send_task() — tests
    run without a live Celery broker/worker."""
    def __init__(self, task_id):
        self.id = task_id


class _FakeAsyncResult:
    """Stand-in for celery.result.AsyncResult(task_id, app=...)."""
    def __init__(self, task_id, app=None):
        self.task_id = task_id
        self.state = "SUCCESS"

    def ready(self):
        return True

    @property
    def result(self):
        return {"drugs_analyzed": 1, "proprietary": "secret-molecule-data"}


@pytest.fixture
def app_module():
    from src.api import app as _app_module
    return _app_module


@pytest.fixture
def make_user(app_module):
    """Create a user directly in the running app's own database (bypassing
    the public-registration role restriction) and log them in."""
    from src.api.auth import AuthService, UserCreate

    def _make(username: str, role: str):
        db = app_module.SessionLocal()
        try:
            svc = AuthService(db)
            user = svc.create_user(UserCreate(
                email=f"{username}@cerebro.local",
                username=username,
                password="testpassword123",
                role=role,
            ))
            token = svc.login(username, "testpassword123")
        finally:
            db.close()
        return user, {"Authorization": f"Bearer {token.access_token}"}

    return _make


class TestTaskOwnershipAuthorization:

    def test_non_owner_forbidden_owner_and_admin_allowed(
        self, test_client, app_module, make_user, monkeypatch
    ):
        uid = uuid.uuid4().hex[:8]
        _, headers_owner = make_user(f"owner_{uid}", "researcher")
        _, headers_other = make_user(f"other_{uid}", "readonly")
        _, headers_admin = make_user(f"admin_{uid}", "admin")

        task_id = str(uuid.uuid4())
        monkeypatch.setattr(
            app_module.pipeline_full_task, "delay",
            lambda payload: _FakeDelayResult(task_id),
        )
        monkeypatch.setattr("celery.result.AsyncResult", _FakeAsyncResult)

        # Owner submits the pipeline run.
        r = test_client.post(
            "/pipeline/run", json={"drugs": ["aspirin"]}, headers=headers_owner
        )
        assert r.status_code == 200
        assert r.json()["task_id"] == task_id

        # A different, non-admin user must NOT be able to read the owner's results.
        r_other = test_client.get(f"/pipeline/status/{task_id}", headers=headers_other)
        assert r_other.status_code == 403

        # The owner can poll their own task.
        r_owner = test_client.get(f"/pipeline/status/{task_id}", headers=headers_owner)
        assert r_owner.status_code == 200
        assert r_owner.json()["task_id"] == task_id

        # An admin can poll any task.
        r_admin = test_client.get(f"/pipeline/status/{task_id}", headers=headers_admin)
        assert r_admin.status_code == 200

    def test_dds_run_records_ownership_too(
        self, test_client, app_module, make_user, monkeypatch
    ):
        uid = uuid.uuid4().hex[:8]
        _, headers_owner = make_user(f"dds_owner_{uid}", "researcher")
        _, headers_other = make_user(f"dds_other_{uid}", "readonly")

        task_id = str(uuid.uuid4())
        monkeypatch.setattr(
            app_module.celery_app, "send_task",
            lambda name, *a, **kw: _FakeDelayResult(task_id),
        )
        monkeypatch.setattr("celery.result.AsyncResult", _FakeAsyncResult)

        r = test_client.post("/dds/run", json={}, headers=headers_owner)
        assert r.status_code == 200
        assert r.json()["task_id"] == task_id

        r_other = test_client.get(f"/pipeline/status/{task_id}", headers=headers_other)
        assert r_other.status_code == 403

        r_owner = test_client.get(f"/pipeline/status/{task_id}", headers=headers_owner)
        assert r_owner.status_code == 200

    def test_unknown_task_id_denied_to_non_admin(self, test_client, make_user):
        uid = uuid.uuid4().hex[:8]
        _, headers = make_user(f"nobody_{uid}", "researcher")
        r = test_client.get(f"/pipeline/status/{uuid.uuid4()}", headers=headers)
        assert r.status_code == 403
