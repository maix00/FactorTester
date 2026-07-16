from __future__ import annotations

import settings as Settings
from flask import Flask
import pytest
import time

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


def test_expired_view_cancels_observer_bound_job_but_not_durable_job(
    client,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.services.view_leases.VIEW_LEASE_GRACE_SECONDS",
        0.01,
        raising=False,
    )
    workspace = client.post(
        "/api/workspaces",
        json={"kind": "single_factor", "draft": {}},
    ).get_json()["workspace"]
    lease = client.post(
        "/api/view-leases",
        json={"view_uuid": "view-a", "workspace_id": workspace["workspace_id"]},
    )
    assert lease.status_code == 201

    observer_job = test_jobs.create_job(
        kind="factor_evaluation",
        run_token="observer-job",
        run_id="observer-run",
        workspace_id=workspace["workspace_id"],
        view_uuid="view-a",
        lifecycle_policy="observer_bound",
        owner="alice",
        payload={"run_id": "observer-run"},
    )
    durable_job = test_jobs.create_job(
        kind="ic",
        run_token="durable-job",
        run_id="durable-run",
        workspace_id=workspace["workspace_id"],
        view_uuid="view-a",
        lifecycle_policy="durable",
        owner="alice",
        payload={"run_id": "durable-run"},
    )

    detached = client.delete("/api/view-leases/view-a")
    assert detached.status_code == 202
    time.sleep(0.02)
    expired = client.get("/api/view-leases/view-a")

    assert expired.get_json()["lease"]["status"] == "expired"
    assert client.get(f"/api/jobs/{observer_job.job_id}").get_json()["status"] == "cancelled"
    assert client.get(f"/api/jobs/{observer_job.job_id}").get_json()["cancel_reason"] == "view_closed"
    assert client.get(f"/api/jobs/{durable_job.job_id}").get_json()["status"] == "queued"


def test_job_artifact_is_queryable_after_live_registry_is_gone(client) -> None:
    job = test_jobs.create_job(
        kind="backtest",
        run_token="artifact-job",
        run_id="artifact-run",
        workspace_id="workspace-a",
        owner="alice",
        payload={"run_id": "artifact-run"},
    )
    test_jobs.store_artifact(
        job,
        "group_execution",
        {"groups": [{"name": "A1", "return": 0.15}]},
    )
    with test_jobs._lock:
        test_jobs._jobs.clear()
        test_jobs._run_token_to_job.clear()
        test_jobs._run_id_to_job.clear()

    artifact = client.get(f"/api/jobs/{job.job_id}/artifacts/group_execution")

    assert artifact.status_code == 200
    assert artifact.get_json()["artifact"]["groups"][0]["name"] == "A1"


def test_workspace_bootstrap_lists_only_its_runs_and_jobs(client) -> None:
    workspace_a = client.post(
        "/api/workspaces",
        json={"kind": "single_factor", "title": "A", "draft": {}},
    ).get_json()["workspace"]
    workspace_b = client.post(
        "/api/workspaces",
        json={"kind": "single_factor", "title": "B", "draft": {}},
    ).get_json()["workspace"]
    job_a = test_jobs.create_job(
        kind="ic",
        run_token="list-a",
        run_id="run-a",
        workspace_id=workspace_a["workspace_id"],
        owner="alice",
        payload={"run_id": "run-a"},
    )
    test_jobs.create_job(
        kind="ic",
        run_token="list-b",
        run_id="run-b",
        workspace_id=workspace_b["workspace_id"],
        owner="alice",
        payload={"run_id": "run-b"},
    )

    workspaces = client.get("/api/workspaces").get_json()["workspaces"]
    jobs = client.get(
        f"/api/jobs?workspace_id={workspace_a['workspace_id']}&status=queued"
    ).get_json()["jobs"]

    assert {item["workspace_id"] for item in workspaces} == {
        workspace_a["workspace_id"],
        workspace_b["workspace_id"],
    }
    assert [item["job_id"] for item in jobs] == [job_a.job_id]
    assert jobs[0]["run_id"] == "run-a"
