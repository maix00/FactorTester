"""Nautilus configuration previews must be authenticated and fail closed."""

from __future__ import annotations

from flask import Flask

from server.modules.nautilus_workbench import nautilus_workbench_bp
from server.modules.single_factor_test.research_jobs import (
    _RunRequestError,
    _reject_unavailable_nautilus_run,
)
from server.services.research_run_identity import (
    NAUTILUS_RUN_SPEC_VERSION,
    RUN_SPEC_VERSION,
    run_spec_version_for_configuration,
)
from server.services.nautilus_bridge.config import freeze_instrument_execution_policy


def _client():
    app = Flask(__name__)
    app.secret_key = "test-only"
    app.register_blueprint(nautilus_workbench_bp)
    return app.test_client()


def test_preview_requires_login_and_never_claims_execution_ready():
    client = _client()
    body = {
        "analysis_kind": "backtest",
        "configuration": {"analyses": {"backtest": {"execution": {
            "backend": "nautilus_trader", "contract_version": 4, "settings": {
            "data_source_ref": "T/MIN1",
            "product_scope_refs": ["product-group:treasuries"],
            "instrument_execution_policy": freeze_instrument_execution_policy(
                preset="basic",
            ).manifest(),
            "start_utc": "2025-04-01T01:00:00Z",
            "end_utc": "2025-05-01T07:15:00Z",
            "bar_end_timestamps": True,
            "execution_price_basis": "open",
            "execution_timing": "next_bar_open",
            "fee_mode": "zero",
        }}}}},
    }
    assert client.post("/api/nautilus/config/preview", json=body).status_code == 401
    with client.session_transaction() as session:
        session["username"] = "tester"
    response = client.post("/api/nautilus/config/preview", json=body)
    assert response.status_code == 200
    assert response.json["ready"] is False
    assert response.json["engine"] == "nautilus_trader"
    assert any(item["path"] == "execution.engine" for item in response.json["blockers"])


def test_frozen_nautilus_backend_cannot_fall_through_legacy_runner():
    prepared = {"analyses": ["backtest"], "frozen_configuration": {"payload": {"analyses": {
        "backtest": {"execution": {
            "backend": "nautilus_trader", "contract_version": 4, "settings": {},
        }},
    }}}}
    try:
        _reject_unavailable_nautilus_run(prepared)
    except _RunRequestError as exc:
        assert exc.details["code"] == "nautilus_execution_unavailable"
    else:
        raise AssertionError("Nautilus backend fell through to the legacy runner")


def test_run_spec_version_follows_selected_backtest_backend():
    configuration = {"analyses": {"backtest": {"execution": {
        "backend": "nautilus_trader", "contract_version": 4,
        "settings": {},
    }}}}
    assert run_spec_version_for_configuration(
        configuration, ["backtest"],
    ) == NAUTILUS_RUN_SPEC_VERSION
    assert run_spec_version_for_configuration(
        configuration, ["ic"],
    ) == RUN_SPEC_VERSION


def test_legacy_backtest_cannot_fall_through_runner():
    prepared = {"analyses": ["backtest"], "frozen_configuration": {
        "payload": {"analyses": {"backtest": {"execution": {
            "settings": {},
        }}}},
    }}
    try:
        _reject_unavailable_nautilus_run(prepared)
    except _RunRequestError as exc:
        assert exc.details["code"] == "legacy_backtest_unavailable"
    else:
        raise AssertionError("Legacy backtest fell through to the retired runner")
