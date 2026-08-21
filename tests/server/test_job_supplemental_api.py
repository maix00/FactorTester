from __future__ import annotations

import hashlib
import time

from flask import Flask
import orjson
import pytest

import settings as Settings
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.scheduling import ResearchJobScheduler
from server.jobs.states import JobStatus
from server.modules.single_factor_test import sft_bp


class _Daemon:
    def __init__(self) -> None:
        self.wakes = 0

    def wake(self) -> None:
        self.wakes += 1


def _parent(repository: JobRepository, root) -> None:
    repository.create(JobRecord(
        job_id="parent-1", run_id="run-1", owner="alice",
        workspace_id="workspace-1", kind="backtest",
        status=JobStatus.SUBMITTED, deployment_id="test",
        job_spec={"run_spec": {"schema_version": 1}},
        run_spec_hash="run-spec-hash", created_at=time.time(),
    ))
    repository.transition("parent-1", JobStatus.PLANNING)
    repository.set_execution_plan(
        "parent-1", plan={"runner": "test"}, notices=[],
        requires_confirmation=False,
    )
    repository.transition("parent-1", JobStatus.RUNNING)
    source = {
        "artifact_version": 1,
        "strategies": {
            "strategy-1": {
                "identity": {
                    "strategy_id": "strategy-1", "group_index": 0,
                    "product_path_selection_id": "products-1",
                    "strategy_configuration_id": "config-1",
                },
                "result_group": {
                    "strategy_id": "strategy-1", "metrics_key": "strategy-1",
                    "timestamps": [1704067200000, 1704153600000],
                    "total_equity": [100.0, 101.0],
                },
                "position_curve": {}, "notional_curve": {},
                "margin_curve": {}, "fill_turnover": {},
            },
        },
        "metrics": {"strategy-1": {"Total Return": 0.01}},
        "detail_context": {},
    }
    raw = orjson.dumps(source)
    target = root / "parent-1" / "strategy-analysis-source.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    repository.record_artifact(
        job_id="parent-1", name="strategy_analysis_source",
        relative_path="parent-1/strategy-analysis-source.json",
        content_type="application/json",
        content_hash=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw),
    )
    repository.transition(
        "parent-1", JobStatus.SUCCEEDED, result_summary={"success": True},
    )


def test_supplemental_routes_create_single_flight_and_page(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    daemon = _Daemon()
    monkeypatch.setattr(
        "server.modules.single_factor_test.supplemental_routes._daemon_client",
        lambda: daemon,
    )
    repository = JobRepository()
    _parent(repository, tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    request = {
        "kind": "backtest_strategy_analysis",
        "params": {"analysis_tab": "returns", "strategy_id": "strategy-1"},
    }
    created = client.post("/api/jobs/parent-1/supplementals", json=request)
    duplicate = client.post("/api/jobs/parent-1/supplementals", json=request)
    listed = client.get(
        "/api/jobs/parent-1/supplementals",
        query_string={"search": "backtest_strategy", "limit": 10},
    )

    assert created.status_code == 201
    assert duplicate.status_code == 202
    assert created.get_json()["job"]["status"] == "queued"
    assert duplicate.get_json()["job"]["job_id"] == created.get_json()["job"]["job_id"]
    assert daemon.wakes == 2
    payload = listed.get_json()
    assert payload["total"] == 1
    assert payload["jobs"][0]["supplemental_kind"] == "backtest_strategy_analysis"


def test_visitor_cannot_submit_supplemental(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    _parent(JobRepository(), tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "visitor:test"
        session["manager_gateway_public_jobs"] = True

    response = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "backtest_strategy_analysis", "params": {},
    })

    assert response.status_code == 403


def test_strategy_supplemental_executes_and_persists_under_parent(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("GTHT_DEPLOYMENT_ID", "supplemental-test")
    repository = JobRepository()
    _parent(repository, tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"
    created = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "backtest_strategy_analysis",
        "params": {"analysis_tab": "returns", "strategy_id": "strategy-1"},
    }).get_json()
    child_id = created["job"]["job_id"]

    deadline = time.monotonic() + 8
    with ResearchJobScheduler(
        repository=repository, deployment_id="supplemental-test",
        execution_workers=1, result_artifact_root=str(tmp_path / "artifacts"),
    ) as scheduler:
        while time.monotonic() < deadline:
            scheduler.tick()
            child = repository.require(child_id)
            if child.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("supplemental job did not finish")

    assert child.status is JobStatus.SUCCEEDED, child.error
    artifact_name = child.result_summary["artifact_name"]
    artifact = repository.require_artifact(
        job_id="parent-1", name=artifact_name,
    )
    assert artifact["relative_path"].startswith("parent-1/")
    payload = orjson.loads(
        (tmp_path / "artifacts" / artifact["relative_path"]).read_bytes()
    )
    assert payload["return_series"][-1]["return"] == pytest.approx(0.01)


def test_custom_analysis_tab_persists_source_runs_and_deletes_without_history(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "jobs.sqlite")
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("GTHT_DEPLOYMENT_ID", "supplemental-test")
    repository = JobRepository()
    _parent(repository, tmp_path / "artifacts")
    app = Flask(__name__)
    app.secret_key = "supplemental"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "alice"

    created_tab = client.post("/api/jobs/parent-1/custom-analyses", json={
        "title": "收益检查",
        "source": (
            "source = artifacts.load_json('strategy_analysis_source')\n"
            "result = {'strategies': len(source['strategies'])}"
        ),
    })
    assert created_tab.status_code == 201
    tab = created_tab.get_json()["analysis"]
    renamed = client.patch(
        f"/api/jobs/parent-1/custom-analyses/{tab['tab_id']}",
        json={"title": "收益复核", "source": tab["source"]},
    )
    assert renamed.get_json()["analysis"]["title"] == "收益复核"

    created_job = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "custom_python_analysis", "params": {"tab_id": tab["tab_id"]},
    })
    assert created_job.status_code == 201
    child_id = created_job.get_json()["job"]["job_id"]
    deadline = time.monotonic() + 8
    with ResearchJobScheduler(
        repository=repository, deployment_id="supplemental-test",
        execution_workers=1, result_artifact_root=str(tmp_path / "artifacts"),
    ) as scheduler:
        while time.monotonic() < deadline:
            scheduler.tick()
            child = repository.require(child_id)
            if child.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("custom supplemental job did not finish")

    assert child.status is JobStatus.SUCCEEDED, child.error
    source_name = child.result_summary["source_artifact_name"]
    result_name = child.result_summary["artifact_name"]
    source_artifact = repository.require_artifact(
        job_id="parent-1", name=source_name,
    )
    result_artifact = repository.require_artifact(
        job_id="parent-1", name=result_name,
    )
    assert source_artifact["artifact_role"] == "input"
    assert result_artifact["artifact_role"] == "output"
    assert source_artifact["relative_path"] == (
        f"parent-1/custom-analyses/{tab['tab_id']}/source.py"
    )
    assert result_artifact["relative_path"] == (
        f"parent-1/custom-analyses/{tab['tab_id']}/result.json"
    )

    updated_source = (
        "source = artifacts.load_json('strategy_analysis_source')\n"
        "result = {'strategies': len(source['strategies']) + 1}"
    )
    updated = client.patch(
        f"/api/jobs/parent-1/custom-analyses/{tab['tab_id']}",
        json={"title": "收益复核", "source": updated_source},
    )
    assert updated.status_code == 200
    rerun = client.post("/api/jobs/parent-1/supplementals", json={
        "kind": "custom_python_analysis", "params": {"tab_id": tab["tab_id"]},
    })
    assert rerun.status_code == 201
    rerun_id = rerun.get_json()["job"]["job_id"]
    assert rerun_id != child_id
    deadline = time.monotonic() + 8
    with ResearchJobScheduler(
        repository=repository, deployment_id="supplemental-test",
        execution_workers=1, result_artifact_root=str(tmp_path / "artifacts"),
    ) as scheduler:
        while time.monotonic() < deadline:
            scheduler.tick()
            rerun_job = repository.require(rerun_id)
            if rerun_job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("custom supplemental rerun did not finish")

    assert rerun_job.status is JobStatus.SUCCEEDED, rerun_job.error
    assert repository.count_supplemental(
        parent_job_id="parent-1", owner="alice",
    ) == 2
    source_after = repository.require_artifact(
        job_id="parent-1", name=source_name,
    )
    result_after = repository.require_artifact(
        job_id="parent-1", name=result_name,
    )
    assert source_after["relative_path"] == source_artifact["relative_path"]
    assert result_after["relative_path"] == result_artifact["relative_path"]
    assert source_after["content_hash"] != source_artifact["content_hash"]
    result_payload = orjson.loads(
        (tmp_path / "artifacts" / result_after["relative_path"]).read_bytes()
    )
    assert result_payload["result"]["strategies"] == 2

    deleted_result = client.delete(
        f"/api/jobs/parent-1/artifacts/{result_name}"
    )
    assert deleted_result.status_code == 200
    assert client.get("/api/jobs/parent-1/custom-analyses").get_json()[
        "analyses"
    ][0]["tab_id"] == tab["tab_id"]

    deleted_tab = client.delete(
        f"/api/jobs/parent-1/custom-analyses/{tab['tab_id']}"
    )
    assert deleted_tab.status_code == 200
    assert repository.load(child_id) is not None
    assert repository.load_artifact(
        job_id="parent-1", owner="alice", name=source_name,
    )["state"] == "deleted"
    detail = client.get(
        f"/api/jobs/parent-1/supplementals/{child_id}"
    ).get_json()
    assert detail["recoverable"] is False
