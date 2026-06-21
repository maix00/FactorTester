from __future__ import annotations

import json
import subprocess

import pytest

from tools.backtest.workers import (
    EngineWorkerDispatcher,
    WorkerExecutionError,
    WorkerRequest,
)


def test_worker_contract_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValueError, match="schema version"):
        WorkerRequest.from_dict({
            "schema_version": 999,
            "request_id": "request-1",
            "engine": "backtrader",
            "operation": "health",
        })


def test_dispatcher_rejects_response_identity_mismatch(monkeypatch) -> None:
    response = {
        "schema_version": 1,
        "request_id": "another-request",
        "engine": "backtrader",
        "success": True,
        "result": {},
        "error": None,
    }
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, json.dumps(response), "",
    ))

    with pytest.raises(WorkerExecutionError, match="identity"):
        EngineWorkerDispatcher().dispatch(WorkerRequest(
            "request-1", "backtrader", "health",
        ))


def test_dispatcher_has_no_implicit_native_fallback() -> None:
    with pytest.raises(WorkerExecutionError, match="no worker registered"):
        EngineWorkerDispatcher().dispatch(WorkerRequest(
            "request-1", "unknown-engine", "health",
        ))


def test_backtrader_worker_health_and_multi_strategy_run() -> None:
    dispatcher = EngineWorkerDispatcher()
    try:
        health = dispatcher.dispatch(WorkerRequest(
            "health-1", "backtrader", "health",
        ))
    except WorkerExecutionError as exc:
        if "EnvironmentNameNotFound" in str(exc):
            pytest.skip("GTHT-backtrader is not installed")
        raise

    assert health.result["framework_version"] == "1.9.78.123"
    assert "run_target_weights" in health.result["operations"]

    result = dispatcher.dispatch(WorkerRequest(
        "run-1",
        "backtrader",
        "run_target_weights",
        {
            "timestamps": [
                "2024-01-01T00:00:00",
                "2024-01-02T00:00:00",
                "2024-01-03T00:00:00",
            ],
            "instruments": ["asset-a"],
            "prices": {"asset-a": [100.0, 110.0, 120.0]},
            "initial_cash": 100_000.0,
            "strategies": [
                    {
                        "strategy_id": "comparison-a",
                        "targets": {"2024-01-01T00:00:00": {"asset-a": 0.5}},
                },
                {
                    "strategy_id": "comparison-b",
                    "targets": {"2024-01-01T00:00:00": {"asset-a": 0.0}},
                },
            ],
        },
    ))

    portfolios = result.result["portfolios"]
    assert set(portfolios) == {"comparison-a", "comparison-b"}
    assert portfolios["comparison-a"]["final_value"] > 100_000.0
    assert portfolios["comparison-b"]["final_value"] == 100_000.0
