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


@pytest.mark.parametrize("engine", ["backtrader", "qlib", "zipline"])
def test_framework_worker_health_and_multi_strategy_run(engine: str) -> None:
    dispatcher = EngineWorkerDispatcher()
    try:
        health = dispatcher.dispatch(WorkerRequest(
            f"health-{engine}", engine, "health",
        ))
    except WorkerExecutionError as exc:
        if "EnvironmentNameNotFound" in str(exc):
            pytest.skip(f"GTHT-{engine} is not installed")
        raise

    assert "run_target_weights" in health.result["operations"]

    result = dispatcher.dispatch(WorkerRequest(
        "run-1",
        engine,
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


def test_framework_workers_share_next_bar_target_weight_semantics() -> None:
    dispatcher = EngineWorkerDispatcher()
    payload = {
        "timestamps": [
            "2024-01-01T00:00:00",
            "2024-01-02T00:00:00",
            "2024-01-03T00:00:00",
        ],
        "instruments": ["asset-a", "asset-b"],
        "prices": {
            "asset-a": [100.0, 110.0, 121.0],
            "asset-b": [100.0, 90.0, 81.0],
        },
        "initial_cash": 100_000.0,
        "strategies": [{
            "strategy_id": "equal-notional",
            "targets": {
                "2024-01-01T00:00:00": {"asset-a": 0.45, "asset-b": 0.45},
            },
        }],
    }

    final_values = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"parity-{engine}", engine, "run_target_weights", payload,
        )).result["portfolios"]["equal-notional"]["final_value"]
        for engine in ("backtrader", "qlib", "zipline")
    }

    assert final_values["backtrader"] == pytest.approx(final_values["qlib"], abs=250.0)
    assert final_values["zipline"] == pytest.approx(final_values["qlib"], abs=250.0)
