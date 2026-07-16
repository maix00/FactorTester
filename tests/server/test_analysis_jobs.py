from __future__ import annotations

import time
import uuid

from flask import Flask, session

from server.modules.factors import factors_bp
from server.modules.factors import analysis as analysis_routes
from server.modules.single_factor_test import sft_bp


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(factors_bp)
    app.register_blueprint(sft_bp)
    return app


def _login(client, username: str = "alice") -> None:
    with client.session_transaction() as sess:
        sess["username"] = username


def _wait_status(client, job_id: str, wanted: set[str], *, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = client.get(f"/api/jobs/{job_id}").get_json()
        if latest["status"] in wanted:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"job did not reach {wanted}: {latest}")


def test_factor_evaluation_job_submit_status_and_result(monkeypatch) -> None:
    app = _app()
    client = app.test_client()
    _login(client)

    monkeypatch.setattr(
        "server.modules.factors._common.page_runtime.get_page_owner",
        lambda page_uuid: "alice",
    )
    monkeypatch.setattr(
        analysis_routes,
        "_run_factor_evaluation",
        lambda data, *, page_uuid: (time.sleep(0.2) or {"success": True}),
    )
    monkeypatch.setattr(
        analysis_routes,
        "_run_factor_evaluation",
        lambda data, *, page_uuid: {
            "success": True,
            "factor": {"alias": data["factor_alias"]},
            "series": [{"product": "AP.CZC", "values": [1.0]}],
        },
    )

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "factor_evaluation",
            "payload": {
                "run_token": f"eval-{uuid.uuid4().hex}",
                "page_uuid": "page-analysis",
                "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
                "factor_family_alias": "Mm",
                "factor_alias": "Mm|N:10d",
            },
        },
    )
    assert submitted.status_code == 202
    assert submitted.get_json()["kind"] == "factor_evaluation"
    job_id = submitted.get_json()["job_id"]

    status = _wait_status(client, job_id, {"succeeded"})
    assert status["latest_event"]["event"] == "result"

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["kind"] == "factor_evaluation"
    assert payload["result"]["factor"]["alias"] == "Mm|N:10d"


def test_factor_type_analysis_job_submit_status_and_result(monkeypatch) -> None:
    app = _app()
    client = app.test_client()
    _login(client)

    monkeypatch.setattr(
        "server.modules.factors._common.page_runtime.get_page_owner",
        lambda page_uuid: "alice",
    )
    monkeypatch.setattr(
        analysis_routes,
        "_run_factor_type_analysis",
        lambda data, *, page_uuid: {
            "success": True,
            "best_match": {"category_label": "趋势", "correlation": 0.81},
        },
    )

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "factor_type_analysis",
            "payload": {
                "run_token": f"type-{uuid.uuid4().hex}",
                "page_uuid": "page-analysis",
                "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
                "factor_family_alias": "Mm",
                "factor_alias": "Mm|N:10d",
            },
        },
    )
    assert submitted.status_code == 202
    assert submitted.get_json()["kind"] == "factor_type_analysis"
    job_id = submitted.get_json()["job_id"]

    _wait_status(client, job_id, {"succeeded"})
    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["result"]["best_match"]["category_label"] == "趋势"


def test_analysis_job_failure_traceback_is_readable(monkeypatch) -> None:
    app = _app()
    client = app.test_client()
    _login(client)

    monkeypatch.setattr(
        "server.modules.factors._common.page_runtime.get_page_owner",
        lambda page_uuid: "alice",
    )

    def _boom(data, *, page_uuid):
        raise RuntimeError("analysis boom")

    monkeypatch.setattr(analysis_routes, "_run_factor_evaluation", _boom)

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "factor_evaluation",
            "payload": {
                "run_token": f"eval-fail-{uuid.uuid4().hex}",
                "page_uuid": "page-analysis",
                "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
                "factor_family_alias": "Mm",
                "factor_alias": "Mm|N:10d",
            },
        },
    )
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]

    _wait_status(client, job_id, {"failed"})
    result = client.get(f"/api/jobs/{job_id}/result")
    payload = result.get_json()
    assert payload["success"] is False
    assert payload["error"]["error"] == "analysis boom"
    assert "RuntimeError: analysis boom" in payload["error"]["traceback"]


def test_analysis_job_cancel_before_start_is_readable(monkeypatch) -> None:
    app = _app()
    client = app.test_client()
    _login(client)

    monkeypatch.setattr(
        "server.modules.factors._common.page_runtime.get_page_owner",
        lambda page_uuid: "alice",
    )

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "factor_evaluation",
            "payload": {
                "run_token": f"eval-cancel-{uuid.uuid4().hex}",
                "page_uuid": "page-analysis",
                "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
                "factor_family_alias": "Mm",
                "factor_alias": "Mm|N:10d",
            },
        },
    )
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    _wait_status(client, job_id, {"cancelled"})

    result = client.get(f"/api/jobs/{job_id}/result")
    payload = result.get_json()
    assert payload["status"] == "cancelled"
    assert payload["error"]["cancelled"] is True


def test_legacy_factor_analysis_endpoints_remain_synchronous(monkeypatch) -> None:
    app = _app()
    client = app.test_client()
    _login(client)

    monkeypatch.setattr(
        "server.modules.factors._common.page_runtime.get_page_owner",
        lambda page_uuid: "alice",
    )
    monkeypatch.setattr(
        analysis_routes,
        "_run_factor_evaluation",
        lambda data, *, page_uuid: {"success": True, "series": [{"product": "AP.CZC"}]},
    )
    monkeypatch.setattr(
        analysis_routes,
        "_run_factor_type_analysis",
        lambda data, *, page_uuid: {"success": True, "best_match": {"category_label": "趋势"}},
    )

    eval_response = client.post(
        "/api/factor_evaluation/evaluate",
        json={"page_uuid": "page-analysis", "paths": ["p"], "factor_family_alias": "Mm", "factor_alias": "f"},
    )
    assert eval_response.status_code == 200
    assert eval_response.get_json()["series"][0]["product"] == "AP.CZC"

    type_response = client.post(
        "/api/factor_type_analysis/analyze",
        json={"page_uuid": "page-analysis", "paths": ["p"], "factor_family_alias": "Mm", "factor_alias": "f"},
    )
    assert type_response.status_code == 200
    assert type_response.get_json()["best_match"]["category_label"] == "趋势"
