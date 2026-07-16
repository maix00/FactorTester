from __future__ import annotations

import settings as Settings
from flask import Flask
import pytest

from server.modules.single_factor_test import sft_bp
from server.services import test_jobs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "research-jobs.sqlite")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    with test_jobs._lock:
        test_jobs._jobs.clear()
        test_jobs._run_token_to_job.clear()
        test_jobs._run_id_to_job.clear()
    return client


def test_user_can_create_and_reopen_a_durable_research_workspace(client) -> None:
    created = client.post(
        "/api/workspaces",
        json={
            "kind": "single_factor",
            "title": "MmMADevRat research",
            "factor_family_alias": "MmMADevRat",
            "draft": {"time_range": {"start": "2025-01-02", "end": "2025-02-14"}},
        },
    )

    assert created.status_code == 201
    workspace = created.get_json()["workspace"]
    assert workspace["owner"] == "alice"
    assert workspace["revision"] == 1
    assert workspace["draft"]["time_range"]["end"] == "2025-02-14"

    reopened = client.get(f"/api/workspaces/{workspace['workspace_id']}")

    assert reopened.status_code == 200
    assert reopened.get_json()["workspace"] == workspace


def test_workspace_updates_create_revisions_and_reject_stale_writers(client) -> None:
    created = client.post(
        "/api/workspaces",
        json={"kind": "single_factor", "draft": {"factor_configs": [{"N": "10d"}]}},
    ).get_json()["workspace"]

    updated = client.patch(
        f"/api/workspaces/{created['workspace_id']}",
        json={
            "expected_revision": 1,
            "draft": {"factor_configs": [{"N": "20d"}]},
        },
    )

    assert updated.status_code == 200
    assert updated.get_json()["workspace"]["revision"] == 2
    assert updated.get_json()["workspace"]["draft"]["factor_configs"] == [{"N": "20d"}]

    stale = client.patch(
        f"/api/workspaces/{created['workspace_id']}",
        json={"expected_revision": 1, "draft": {"factor_configs": []}},
    )

    assert stale.status_code == 409
    assert stale.get_json()["current_revision"] == 2


def test_submitted_run_freezes_workspace_revision_and_creates_page_independent_job(
    client,
    monkeypatch,
) -> None:
    workspace = client.post(
        "/api/workspaces",
        json={
            "kind": "single_factor",
            "factor_family_alias": "MmMADevRat",
            "draft": {"factor_configs": [{"N": "10d"}], "product_paths": ["core8_path"]},
        },
    ).get_json()["workspace"]

    def fake_submit(kind, payload):
        return test_jobs.create_job(
            kind=kind,
            run_token=payload["run_token"],
            run_id=payload["run_id"],
            workspace_id=payload["workspace_id"],
            owner="alice",
            payload=payload,
        )

    monkeypatch.setattr(
        "server.modules.single_factor_test.research_jobs._submit_kind",
        fake_submit,
        raising=False,
    )

    submitted = client.post(
        "/api/runs",
        json={
            "workspace_id": workspace["workspace_id"],
            "workspace_revision": 1,
            "analyses": ["ic"],
            "lifecycle_policy": "durable",
        },
    )

    assert submitted.status_code == 202
    submission = submitted.get_json()
    assert submission["run_id"]
    assert len(submission["jobs"]) == 1
    assert submission["jobs"][0]["kind"] == "ic"

    client.patch(
        f"/api/workspaces/{workspace['workspace_id']}",
        json={
            "expected_revision": 1,
            "draft": {"factor_configs": [{"N": "20d"}], "product_paths": ["core8_path"]},
        },
    )
    frozen = client.get(f"/api/runs/{submission['run_id']}")

    assert frozen.status_code == 200
    run_spec = frozen.get_json()["run"]["run_spec"]
    assert run_spec["workspace_revision"] == 1
    assert run_spec["configuration"]["factor_configs"] == [{"N": "10d"}]
    assert "page_uuid" not in run_spec
