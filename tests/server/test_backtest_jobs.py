from __future__ import annotations

import time
import uuid

from flask import Flask, request, session

from server.modules.single_factor_test import sft_bp
from server.services import test_jobs


def _wait(job, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.status in test_jobs.TERMINAL_STATUSES:
            return
        time.sleep(0.01)
    raise AssertionError(f"job did not finish: {job.summary()}")


def _job(owner: str = "alice"):
    token = f"run-{uuid.uuid4().hex}"
    return test_jobs.create_job(
        run_token=token,
        page_uuid="page-a",
        owner=owner,
        payload={"run_token": token, "page_uuid": "page-a"},
    )


def test_backtest_job_records_progress_and_success_result() -> None:
    job = _job()

    def _target(sink):
        sink.emit_signal_progress(completed=1, total=3)
        sink.emit_result({"success": True, "answer": 42})

    future = test_jobs.submit(job, _target)
    future.result(timeout=3)
    _wait(job)

    assert job.status == "succeeded"
    assert job.kind == "backtest"
    assert job.result == {"success": True, "answer": 42}
    assert [event.event for event in job.events_after()] == ["signal_progress", "result"]
    assert job.summary()["latest_event"]["event"] == "result"


def test_backtest_job_records_failure_traceback() -> None:
    job = _job()

    def _target(_sink):
        raise RuntimeError("boom")

    future = test_jobs.submit(job, _target)
    future.result(timeout=3)
    _wait(job)

    assert job.status == "failed"
    assert job.error is not None
    assert job.error["error"] == "boom"
    assert "RuntimeError: boom" in job.error["traceback"]


def test_backtest_job_cancel_is_owner_scoped() -> None:
    job = _job(owner="alice")

    try:
        test_jobs.cancel(job.job_id, "bob")
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-owner cancel should fail")

    assert test_jobs.cancel(job.job_id, "alice") is True
    assert job.cancel_event.is_set() is True
    assert job.status == "cancelled"
    assert job.error is not None
    assert job.error["cancelled"] is True


def test_backtest_job_routes_submit_status_and_result(monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)

    def _fake_start(payload):
        job = test_jobs.create_job(
            kind="backtest",
            run_token=str(payload["run_token"]),
            page_uuid=str(payload["page_uuid"]),
            owner="alice",
            payload=payload,
        )

        def _target(sink):
            sink.emit_activity(message="started")
            sink.emit_result({"success": True, "groups": []})

        test_jobs.submit(job, _target)
        return job

    monkeypatch.setattr(
        "server.modules.single_factor_test.group.start_group_test_job",
        _fake_start,
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post("/backtest/jobs", json={"run_token": f"route-{uuid.uuid4().hex}", "page_uuid": "page-a"})
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]

    deadline = time.monotonic() + 3.0
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/backtest/jobs/{job_id}")
        if status.get_json()["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert status is not None
    assert status.get_json()["status"] == "succeeded"

    result = client.get(f"/backtest/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.get_json()["result"] == {"success": True, "groups": []}


def test_generic_job_routes_submit_status_and_result(monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)

    def _fake_start(payload):
        job = test_jobs.create_job(
            kind="backtest",
            run_token=str(payload["run_token"]),
            page_uuid=str(payload["page_uuid"]),
            owner="alice",
            payload=payload,
        )

        def _target(sink):
            sink.emit_result({"success": True, "groups": []})

        test_jobs.submit(job, _target)
        return job

    monkeypatch.setattr(
        "server.modules.single_factor_test.group.start_group_test_job",
        _fake_start,
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "backtest",
            "payload": {"run_token": f"generic-{uuid.uuid4().hex}", "page_uuid": "page-a"},
        },
    )
    assert submitted.status_code == 202
    assert submitted.get_json()["kind"] == "backtest"
    job_id = submitted.get_json()["job_id"]

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert status["kind"] == "backtest"

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.get_json()["result"] == {"success": True, "groups": []}


def test_ic_job_records_progress_and_success_result(monkeypatch) -> None:
    from server.modules.single_factor_test import ic as ic_module

    class _Tester:
        sync_signal_index = "old"
        sync_signal_index_replaced = "old"

    tester = _Tester()
    family = object()

    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_runtime_from_payload",
        lambda data: ("page-ic", tester, family),
    )
    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_compute",
        lambda data, tester, family: (
            ["factor-a"], "paths-hash", [], {("key",): []}, {("key",): {}}, None, None, [0], 0
        ),
    )

    def _fake_compute(_tester, param_items, _param_payloads, _primary_ic_lag, *, emitter=None, cancel_event=None):
        assert cancel_event is not None
        assert len(param_items) == 1
        emitter.emit_start(total=2, groups=1, phase="init")
        emitter.emit_progress(1, 2, "eval")
        return ic_module._ICComputeResult()

    monkeypatch.setattr(ic_module, "_compute_ic_groups", _fake_compute)
    monkeypatch.setattr(
        ic_module,
        "_build_ic_response",
        lambda *args, **kwargs: {"success": True, "factors": [], "ic_stats": {"columns": [], "rows": []}},
    )

    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/api/jobs", json={"run_token": f"ic-{uuid.uuid4().hex}", "page_uuid": "page-ic"}):
        session["username"] = "alice"
        job = ic_module.start_ic_test_job(request.get_json())

    job.future.result(timeout=3)
    _wait(job)

    assert job.kind == "ic"
    assert job.status == "succeeded"
    assert job.result == {"success": True, "factors": [], "ic_stats": {"columns": [], "rows": []}}
    assert [event.event for event in job.events_after()] == ["start", "progress", "result"]
    assert tester.sync_signal_index is None
    assert tester.sync_signal_index_replaced is None


def test_generic_ic_job_routes_submit_status_and_result(monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)

    def _fake_start(payload):
        job = test_jobs.create_job(
            kind="ic",
            run_token=str(payload["run_token"]),
            page_uuid=str(payload["page_uuid"]),
            owner="alice",
            payload=payload,
        )

        def _target(sink):
            sink.emit_start(total=1, groups=1, phase="init")
            sink.emit_progress(1, 1, "eval")
            sink.emit_result({"success": True, "factors": []})

        test_jobs.submit(job, _target)
        return job

    monkeypatch.setattr(
        "server.modules.single_factor_test.ic.start_ic_test_job",
        _fake_start,
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "ic",
            "payload": {"run_token": f"ic-route-{uuid.uuid4().hex}", "page_uuid": "page-ic"},
        },
    )
    assert submitted.status_code == 202
    assert submitted.get_json()["kind"] == "ic"
    job_id = submitted.get_json()["job_id"]

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert status["kind"] == "ic"
    assert status["latest_event"]["event"] == "result"

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.get_json()["result"] == {"success": True, "factors": []}


def test_generic_ic_job_result_reports_failure_traceback(monkeypatch) -> None:
    from server.modules.single_factor_test import ic as ic_module

    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_runtime_from_payload",
        lambda data: ("page-ic-fail", object(), object()),
    )
    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_compute",
        lambda data, tester, family: (_ for _ in ()).throw(RuntimeError("ic boom")),
    )

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "ic",
            "payload": {"run_token": f"ic-fail-{uuid.uuid4().hex}", "page_uuid": "page-ic-fail"},
        },
    )
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] == "failed":
            break
        time.sleep(0.01)
    assert status["status"] == "failed"

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["success"] is False
    assert payload["kind"] == "ic"
    assert payload["error"]["error"] == "ic boom"
    assert "RuntimeError: ic boom" in payload["error"]["traceback"]


def test_generic_ic_job_cancel_result_is_readable(monkeypatch) -> None:
    from server.modules.single_factor_test import ic as ic_module

    class _Tester:
        sync_signal_index = None
        sync_signal_index_replaced = None

    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_runtime_from_payload",
        lambda data: ("page-ic-cancel", _Tester(), object()),
    )
    monkeypatch.setattr(
        ic_module,
        "_prepare_ic_compute",
        lambda data, tester, family: (
            ["factor-a"], "paths-hash", [], {("key",): []}, {("key",): {}}, None, None, [0], 0
        ),
    )

    def _fake_compute(_tester, _param_items, _param_payloads, _primary_ic_lag, *, emitter=None, cancel_event=None):
        emitter.emit_start(total=1, groups=1, phase="init")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                raise ic_module._ICCancelled("IC test job cancelled")
            time.sleep(0.01)
        raise AssertionError("cancel was not requested")

    monkeypatch.setattr(ic_module, "_compute_ic_groups", _fake_compute)

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post(
        "/api/jobs",
        json={
            "kind": "ic",
            "payload": {"run_token": f"ic-cancel-{uuid.uuid4().hex}", "page_uuid": "page-ic-cancel"},
        },
    )
    assert submitted.status_code == 202
    job_id = submitted.get_json()["job_id"]

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] == "running":
            break
        time.sleep(0.01)
    assert status["status"] == "running"

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.get_json()["cancelled"] is True

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").get_json()
        if status["status"] == "cancelled":
            break
        time.sleep(0.01)
    assert status["status"] == "cancelled"

    result = client.get(f"/api/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["success"] is False
    assert payload["kind"] == "ic"
    assert payload["error"]["cancelled"] is True


def test_backtest_job_submit_response_exposes_run_token_for_step_mode(monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)

    def _fake_start(payload):
        job = test_jobs.create_job(
            kind="backtest",
            run_token=str(payload["run_token"]),
            page_uuid=str(payload["page_uuid"]),
            owner="alice",
            payload=payload,
        )

        def _target(sink):
            sink.emit_step({"timestamp": "2026-01-02 09:00:00", "event": "SIGNAL"})
            sink.emit_result({"success": True, "groups": []})

        test_jobs.submit(job, _target)
        return job

    monkeypatch.setattr(
        "server.modules.single_factor_test.group.start_group_test_job",
        _fake_start,
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    submitted = client.post(
        "/backtest/jobs",
        json={"run_token": "step-token", "page_uuid": "page-a", "step_mode": True},
    )
    assert submitted.status_code == 202
    payload = submitted.get_json()
    assert payload["run_token"] == "step-token"
    assert payload["stream_url"] == f"/backtest/jobs/{payload['job_id']}/stream"


def test_backtest_job_list_filters_by_page_and_status() -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    active = test_jobs.create_job(
        kind="backtest",
        run_token=f"list-active-{uuid.uuid4().hex}",
        page_uuid="page-list-a",
        owner="alice",
        payload={"page_uuid": "page-list-a"},
    )
    other_page = test_jobs.create_job(
        kind="backtest",
        run_token=f"list-other-{uuid.uuid4().hex}",
        page_uuid="page-list-b",
        owner="alice",
        payload={"page_uuid": "page-list-b"},
    )
    other_page.succeed({"success": True})
    other_page.close()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    response = client.get("/backtest/jobs?page_uuid=page-list-a&status=queued,running")
    assert response.status_code == 200
    payload = response.get_json()
    assert [job["job_id"] for job in payload["jobs"]] == [active.job_id]

    generic = client.get("/api/jobs?kind=backtest&page_uuid=page-list-a&status=queued,running")
    assert generic.status_code == 200
    assert [job["job_id"] for job in generic.get_json()["jobs"]] == [active.job_id]


def test_backtest_job_result_reports_failure_payload() -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sft_bp)
    job = _job(owner="alice")
    job.fail({"success": False, "error": "bad input", "traceback": "trace"}, cancelled=False)
    job.close()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    result = client.get(f"/backtest/jobs/{job.job_id}/result")
    assert result.status_code == 200
    payload = result.get_json()
    assert payload["success"] is False
    assert payload["status"] == "failed"
    assert payload["error"]["traceback"] == "trace"
