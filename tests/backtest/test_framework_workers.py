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


def test_framework_worker_streams_event_time_progress() -> None:
    dispatcher = EngineWorkerDispatcher()
    events = []
    dispatcher.dispatch(
        WorkerRequest(
            "progress-backtrader",
            "backtrader",
            "run_group_strategy",
            {
                "timestamps": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "instruments": ["asset-a"],
                "prices": {"asset-a": [100.0, 101.0, 102.0]},
                "membership": [[[True]], [[True]], [[True]]],
                "signal_updates": [[True], [True], [True]],
                "initial_cash": 100_000.0,
                "strategy_configs": [{
                    "strategy_id": "group-1",
                    "allocation_policy": "equal_notional",
                }],
            },
        ),
        progress=events.append,
    )

    assert [event["completed"] for event in events] == [1, 2, 3]
    assert events[-1]["event_timestamp"].startswith("2024-01-03")


def test_frameworks_calculate_identical_group_targets_inside_each_worker() -> None:
    from tools.backtest.workers.runners.native import run_group_strategy as run_native

    dispatcher = EngineWorkerDispatcher()
    payload = {
        "timestamps": [
            "2024-01-01T00:00:00",
            "2024-01-02T00:00:00",
            "2024-01-03T00:00:00",
            "2024-01-04T00:00:00",
        ],
        "instruments": ["volatile", "stable"],
        "prices": {
            "volatile": [100.0, 110.0, 99.0, 118.8],
            "stable": [100.0, 101.0, 102.01, 103.0301],
        },
        "membership": [
            [[True, True], [True, False], [False, True]],
            [[True, True], [True, False], [False, True]],
            [[True, True], [False, True], [True, False]],
            [[True, True], [False, True], [True, False]],
        ],
        "signal_updates": [
            [True, True, True],
            [True, True, True],
            [True, True, True],
            [True, True, True],
        ],
        "initial_cash": 100_000.0,
        "strategy_configs": [
            {
                "strategy_id": "equal-risk",
                "allocation_policy": "inverse_volatility",
                "volatility_lookback": 2,
                "rebalance_mode": "on_factor_signal",
            },
            {
                "strategy_id": "membership",
                "allocation_policy": "equal_notional",
                "rebalance_mode": "membership_change",
            },
            {
                "strategy_id": "long-short",
                "strategy_kind": "long_short",
                "long_indices": [1],
                "short_indices": [2],
                "allocation_policy": "equal_notional",
                "rebalance_mode": "on_factor_signal",
            },
        ],
    }

    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"group-target-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("backtrader", "qlib", "zipline")
    }
    results["native"] = run_native(payload)

    traces = [results[engine]["target_trace"] for engine in results]
    assert traces[1:] == traces[:-1], {
        engine: results[engine]["target_trace"] for engine in results
    }
    assert all(
        len(result["portfolios"]["equal-risk"]["equity_curve"]) == 4
        for result in results.values()
    )
    assert all(
        result["portfolios"]["long-short"]["positions"]
        for result in results.values()
    )


@pytest.mark.parametrize("engine", ["native", "backtrader", "qlib", "zipline"])
def test_framework_margin_plugin_scales_orders_without_rewriting_targets(engine: str) -> None:
    dispatcher = EngineWorkerDispatcher()
    payload = {
            "timestamps": [
                "2024-01-01T00:00:00",
                "2024-01-02T00:00:00",
                "2024-01-03T00:00:00",
            ],
            "instruments": ["asset-a"],
            "prices": {"asset-a": [100.0, 100.0, 100.0]},
            "membership": [[[True]], [[True]], [[True]]],
            "signal_updates": [[True], [True], [True]],
            "initial_cash": 100_000.0,
            "market_rules": {
                "margin_ratios": [[0.2], [0.2], [0.2]],
                "multipliers": [[1.0], [1.0], [1.0]],
                "lot_sizes": [[1.0], [1.0], [1.0]],
            },
            "strategy_configs": [{
                "strategy_id": "group-1",
                "allocation_policy": "equal_notional",
                "rebalance_mode": "on_factor_signal",
                "margin_mode": "proportional_scale",
                "collateral_fraction": 0.05,
            }],
    }
    if engine == "native":
        from tools.backtest.workers.runners.native import run_group_strategy

        result = run_group_strategy(payload)
    else:
        result = dispatcher.dispatch(WorkerRequest(
            f"margin-{engine}", engine, "run_group_strategy", payload
        )).result

    assert result["target_trace"]["group-1"] == {
        "2024-01-01T00:00:00": {"asset-a": 1.0},
        "2024-01-02T00:00:00": {"asset-a": 1.0},
        "2024-01-03T00:00:00": {"asset-a": 1.0},
    }
    assert result["portfolios"]["group-1"]["positions"]["asset-a"] == 250.0


def test_framework_liquidity_plugin_limits_each_bar_without_changing_target() -> None:
    from tools.backtest.workers.runners.native import run_group_strategy as run_native

    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 5)]
    payload = {
        "timestamps": timestamps,
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0] * 4},
        "volumes": {"asset-a": [100.0] * 4},
        "membership": [[[True]]] * 4,
        "signal_updates": [[True]] * 4,
        "initial_cash": 100_000.0,
        "strategy_configs": [{
            "strategy_id": "group-1",
            "allocation_policy": "equal_notional",
            "liquidity_mode": "volume_participation",
            "participation_rate": 0.1,
        }],
    }
    dispatcher = EngineWorkerDispatcher()
    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"liquidity-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("backtrader", "qlib", "zipline")
    }
    results["native"] = run_native(payload)

    assert all(
        result["target_trace"]["group-1"][timestamps[0]] == {"asset-a": 1.0}
        for result in results.values()
    )
    assert {
        engine: result["portfolios"]["group-1"]["positions"]["asset-a"]
        for engine, result in results.items()
    } == {engine: 30.0 for engine in results}


@pytest.mark.parametrize(
    ("overrides", "price", "expected_position"),
    [
        ({"fee_rate": 0.001}, 333.0, 300.0),
        ({"slippage_mode": "fixed_bps", "slippage_bps": 10.0}, 334.0, 299.0),
    ],
)
def test_framework_fee_and_slippage_plugins_are_consistent(
    overrides: dict, price: float, expected_position: float
) -> None:
    from tools.backtest.workers.runners.native import run_group_strategy as run_native

    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 4)]
    config = {
        "strategy_id": "group-1",
        "allocation_policy": "equal_notional",
        "rebalance_mode": "buy_and_hold",
        **overrides,
    }
    payload = {
        "timestamps": timestamps,
        "instruments": ["asset-a"],
        "prices": {"asset-a": [price] * 3},
        "membership": [[[True]]] * 3,
        "signal_updates": [[True]] * 3,
        "initial_cash": 100_000.0,
        "strategy_configs": [config],
    }
    dispatcher = EngineWorkerDispatcher()
    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"execution-plugin-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("backtrader", "qlib", "zipline")
    }
    results["native"] = run_native(payload)

    positions = {
        engine: result["portfolios"]["group-1"]["positions"]["asset-a"]
        for engine, result in results.items()
    }
    assert positions == {engine: expected_position for engine in results}
    final_values = {
        engine: result["portfolios"]["group-1"]["final_value"]
        for engine, result in results.items()
    }
    assert max(final_values.values()) - min(final_values.values()) < 1.0, final_values
