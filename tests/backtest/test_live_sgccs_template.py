from __future__ import annotations

import os
import time

import pytest

from server import create_app


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SGCCS_TEMPLATE") != "1",
    reason="requires an account template and LocalCNFutures data",
)


USERNAME = os.environ.get("FACTORTESTER_LIVE_USERNAME", "18717974771")
TEMPLATE_ID = os.environ.get("FACTORTESTER_LIVE_TEMPLATE_ID", "1780356047164")
FACTOR_FAMILY = os.environ.get("FACTORTESTER_LIVE_FACTOR_FAMILY", "SgCCS")


def test_live_template_import_runs_as_a_durable_process_job() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = USERNAME
        session["_sid"] = "live-durable-research-job"

    created = client.post("/api/test-authoring/workspaces", json={
        "title": "live durable template acceptance",
        "factor_families": [{"alias": FACTOR_FAMILY}],
        "factors": [],
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    workspace = created.get_json()["workspace"]

    listed = client.get("/api/test-authoring/configuration-templates")
    assert listed.status_code == 200, listed.get_data(as_text=True)
    legacy_key = f"{FACTOR_FAMILY}:{TEMPLATE_ID}"
    template = next(
        (
            item for item in listed.get_json()["templates"]
            if item.get("legacy_template_id") == legacy_key
        ),
        None,
    )
    assert template is not None, f"migrated template {legacy_key} not found"

    loaded = client.post(
        f"/api/test-authoring/workspaces/{workspace['workspace_id']}/configuration/load-template",
        json={"expected_revision": 1, "configuration_id": template["configuration_id"]},
    )
    assert loaded.status_code == 200, loaded.get_data(as_text=True)
    configuration = loaded.get_json()["configuration"]
    backtest = configuration["payload"]["analyses"]["backtest"]
    assert backtest.get("groups"), "migrated template did not normalize group_settings.groups"

    submitted = client.post("/api/runs", json={
        "workspace_id": workspace["workspace_id"],
        "configuration_revision": configuration["revision"],
        "analyses": ["backtest"],
        "retention_mode": "full",
    })
    assert submitted.status_code == 202, submitted.get_data(as_text=True)
    job_id = submitted.get_json()["jobs"][0]["job_id"]

    deadline = time.monotonic() + float(os.environ.get("FACTORTESTER_LIVE_TIMEOUT", "600"))
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] in {"succeeded", "failed", "cancelled", "expired"}:
            break
        time.sleep(0.25)

    assert status is not None
    assert status["execution_mode"] == "process"
    assert status["status"] == "succeeded", client.get(f"/api/jobs/{job_id}/result").get_json()
    result = client.get(f"/api/jobs/{job_id}/result").get_json()["result"]
    artifact = client.get(f"/api/jobs/{job_id}/artifacts/group_execution").get_json()["artifact"]
    net_returns = client.get(
        f"/api/jobs/{job_id}/artifacts/net_returns"
    ).get_json()["artifact"]
    order_audit = client.get(
        f"/api/jobs/{job_id}/artifacts/order_audit"
    ).get_json()
    assert result["success"] is True
    assert artifact.get("groups") or artifact.get("group_results")
    assert net_returns["artifact_kind"] == "net_return_series"
    assert net_returns["series"]
    assert order_audit["run_id"] == result["run_id"]
    assert isinstance(order_audit["strategies"], dict)
