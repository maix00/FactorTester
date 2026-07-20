from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tools.testers.backtest.engines.workers import (
    EngineWorkerDispatcher,
    WorkerExecutionError,
    WorkerRequest,
)
from tools.testers.backtest.engines.workers.operations import RUN_STRATEGY_INTENTS


def _strategy_settings(**overrides):
    values = {
        "rebalance_trigger": "on_factor_signal",
        "position_policy": "rebalance_to_target",
    }
    values.update(overrides)
    return values


def _real_group_payload_or_skip() -> dict[str, Any]:
    try:
        from sources.LocalCNFutures import SOURCE_DATA_DIR
    except Exception as exc:  # pragma: no cover - source module unavailable
        pytest.skip(f"LocalCNFutures unavailable: {exc}")

    root = Path(SOURCE_DATA_DIR) / "main_dayk"
    instruments = ("A.DCE", "AG.SHF")
    if not all((root / f"{instrument}.parquet").is_file() for instrument in instruments):
        pytest.skip("LocalCNFutures main_dayk real-data files are not available")

    series = []
    for instrument in instruments:
        frame = pd.read_parquet(root / f"{instrument}.parquet", columns=["trading_day", "close_price"])
        values = pd.Series(
            frame["close_price"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(pd.to_datetime(frame["trading_day"])),
        ).dropna().sort_index()
        series.append(values[~values.index.duplicated(keep="last")])
    index = series[0].index.intersection(series[1].index).sort_values()[-8:]
    if len(index) < 8:
        pytest.skip(f"not enough overlapping real trading days: {len(index)}")
    prices = {
        instrument: [float(value) for value in values.reindex(index)]
        for instrument, values in zip(instruments, series, strict=True)
    }
    momentum = pd.DataFrame(prices, index=index).pct_change(2).fillna(0.0)
    membership = []
    for _, row in momentum.iterrows():
        ranked = row.sort_values(ascending=False).index.tolist()
        high = set(ranked[:1])
        low = set(ranked[1:])
        membership.append([
            [True, True],
            [instruments[0] in high, instruments[1] in high],
            [instruments[0] in low, instruments[1] in low],
        ])
    return {
        "timestamps": [timestamp.isoformat() for timestamp in index],
        "instruments": list(instruments),
        "prices": prices,
        "membership": membership,
        "signal_updates": [[True, True, True] for _ in index],
        "initial_cash": 1_000_000.0,
        "market_rules": {
            "margin_ratios": [[1.0, 1.0]] * len(index),
            "multipliers": [[1.0, 1.0]] * len(index),
            "lot_sizes": [[1.0, 1.0]] * len(index),
        },
        "strategy_configs": [
            _strategy_settings(
                strategy_id="top-momentum",
                membership_index=1,
                allocation_policy="equal_notional",
            ),
            _strategy_settings(
                strategy_id="long-short",
                strategy_kind="long_short",
                long_indices=[1],
                short_indices=[2],
                allocation_policy="equal_notional",
            ),
        ],
    }


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


def test_worker_health_exposes_strategy_intent_operation_manifest() -> None:
    health = EngineWorkerDispatcher().dispatch(WorkerRequest(
        "health-backtrader", "backtrader", "health",
    )).result

    assert RUN_STRATEGY_INTENTS in health["operations"]
    assert "run_group_strategy" in health["operations"]
    manifest = health["operation_manifest"]
    assert manifest[RUN_STRATEGY_INTENTS]["aliases"] == ["run_group_strategy"]
    assert "strategy_kind" in manifest[RUN_STRATEGY_INTENTS]["description"]


def test_strategy_intent_worker_rejects_unregistered_strategy_kind() -> None:
    payload = {
        "timestamps": ["2024-01-01", "2024-01-02"],
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0, 101.0]},
        "membership": [[[True]], [[True]]],
        "signal_updates": [[True], [True]],
        "initial_cash": 100_000.0,
        "strategy_configs": [_strategy_settings(
            strategy_id="cross-over",
            strategy_kind="technical_cross_over",
            allocation_policy="equal_notional",
        )],
    }

    with pytest.raises(WorkerExecutionError, match="strategy_kind='technical_cross_over'"):
        EngineWorkerDispatcher().dispatch(WorkerRequest(
            "unknown-intent", "backtrader", RUN_STRATEGY_INTENTS, payload,
        ))


def test_rqalpha_worker_is_declared_without_native_fallback() -> None:
    dispatcher = EngineWorkerDispatcher(environments={"rqalpha": "missing-rqalpha-env"})

    with pytest.raises(WorkerExecutionError, match="missing-rqalpha-env|rqalpha"):
        dispatcher.dispatch(WorkerRequest(
            "request-1", "rqalpha", "run_group_strategy", {},
        ))


def test_native_group_strategy_reports_setting_fallback_diagnostics() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy

    payload = {
        "timestamps": ["2024-01-01T00:00:00", "2024-01-02T00:00:00"],
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0, 100.0]},
        "membership": [[[True]], [[True]]],
        "signal_updates": [[True], [True]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "margin_ratios": [[1.0], [1.0]],
            "multipliers": [[1.0], [1.0]],
            "lot_sizes": [[1.0], [1.0]],
        },
        "strategy_configs": [_strategy_settings(
            strategy_id="group-1",
            allocation_policy="equal_notional",
            _setting_fallbacks=[{
                "setting_key": "money_unit_policy",
                "module": "accounting",
                "engine": "qlib",
                "requested_value": "minor_units",
                "applied_value": "engine_native",
                "reason": "engine_disabled_value",
            }],
        )],
    }

    result = run_group_strategy(payload)

    assert result["strategy_diagnostics"]["group-1"]["setting_fallback_count"] == 1
    assert result["strategy_diagnostics"]["group-1"]["setting_fallbacks"][0]["module"] == "accounting"


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
                _strategy_settings(
                    strategy_id="comparison-a",
                    targets={"2024-01-01T00:00:00": {"asset-a": 0.5}},
                ),
                _strategy_settings(
                    strategy_id="comparison-b",
                    targets={"2024-01-01T00:00:00": {"asset-a": 0.0}},
                ),
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
        "strategies": [_strategy_settings(
            strategy_id="equal-notional",
            targets={
                "2024-01-01T00:00:00": {"asset-a": 0.45, "asset-b": 0.45},
            },
        )],
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
    events: list[dict[str, Any]] = []
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
                "strategy_configs": [_strategy_settings(
                    strategy_id="group-1",
                    allocation_policy="equal_notional",
                )],
            },
        ),
        progress=events.append,
    )

    assert [event["completed"] for event in events] == [1, 2, 3]
    assert events[-1]["event_timestamp"].startswith("2024-01-03")


def test_framework_progress_is_bounded_for_long_replays() -> None:
    from tools.testers.backtest.engines.workers.runners.common import should_report_progress

    checkpoints = [
        completed for completed in range(1, 10_001)
        if should_report_progress(completed, 10_000)
    ]

    assert checkpoints[0] == 1
    assert checkpoints[-1] == 10_000
    assert len(checkpoints) <= 102


def test_native_group_strategy_progress_counts_every_bar() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy

    events = []
    payload = {
        "timestamps": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0, 101.0, 102.0]},
        "membership": [
            [[True], [False]],
            [[True], [False]],
            [[False], [True]],
        ],
        "signal_updates": [[True, True], [True, True], [True, True]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "margin_ratios": [[1.0], [1.0], [1.0]],
            "multipliers": [[1.0], [1.0], [1.0]],
            "lot_sizes": [[1.0], [1.0], [1.0]],
        },
        "strategy_configs": [
            _strategy_settings(strategy_id="group-1", allocation_policy="equal_notional"),
            _strategy_settings(strategy_id="group-2", allocation_policy="equal_notional"),
            {
                **_strategy_settings(
                    strategy_id="long-short:1",
                    allocation_policy="equal_notional",
                ),
                "strategy_kind": "long_short",
                "long_indices": [0],
                "short_indices": [1],
            },
        ],
    }

    run_group_strategy(payload, progress=lambda completed, total, timestamp: events.append({
        "completed": completed,
        "total": total,
        "timestamp": timestamp,
    }))

    # The vectorized native engine advances every strategy together on each bar,
    # so replay progress is reported per bar (not per strategy sub-step).
    assert [event["completed"] for event in events] == [1, 2, 3]
    assert {event["total"] for event in events} == {3}


def test_frameworks_calculate_identical_group_targets_inside_each_worker() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

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
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            },
            {
                "strategy_id": "membership",
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "membership_change",
                "position_policy": "rebalance_to_target",
            },
            {
                "strategy_id": "long-short",
                "strategy_kind": "long_short",
                "long_indices": [1],
                "short_indices": [2],
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
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


def test_frameworks_preserve_equal_risk_and_equal_notional_equity_difference() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    dispatcher = EngineWorkerDispatcher()
    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 7)]
    payload = {
        "timestamps": timestamps,
        "instruments": ["volatile", "stable"],
        "prices": {
            "volatile": [100.0, 110.0, 99.0, 118.8, 95.04, 123.552],
            "stable": [100.0, 101.0, 102.01, 103.0301, 104.060401, 105.10100501],
        },
        "membership": [[[True, True], [True, True]]] * 6,
        "signal_updates": [[True, True]] * 6,
        "initial_cash": 100_000.0,
        "market_rules": {
            "margin_ratios": [[1.0, 1.0]] * 6,
            "multipliers": [[1.0, 1.0]] * 6,
            "lot_sizes": [[0.000001, 0.000001]] * 6,
        },
        "strategy_configs": [
            _strategy_settings(
                strategy_id="equal-risk",
                allocation_policy="inverse_volatility",
                volatility_lookback=2,
                membership_index=0,
                execution_timing="same_bar",
            ),
            _strategy_settings(
                strategy_id="equal-notional",
                allocation_policy="equal_notional",
                membership_index=1,
                execution_timing="same_bar",
            ),
        ],
    }

    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"allocation-equity-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("backtrader", "qlib", "zipline")
    }
    results["native"] = run_native(payload)

    assert {
        engine: result["target_trace"]
        for engine, result in results.items()
    } == {
        engine: results["native"]["target_trace"]
        for engine in results
    }
    for engine, result in results.items():
        risk_trace = result["target_trace"]["equal-risk"]
        notional_trace = result["target_trace"]["equal-notional"]
        assert risk_trace[timestamps[-1]] != notional_trace[timestamps[-1]]
        risk_equity = result["portfolios"]["equal-risk"]["equity_curve"]
        notional_equity = result["portfolios"]["equal-notional"]["equity_curve"]
        assert risk_equity != notional_equity, engine
        assert (
            result["portfolios"]["equal-risk"]["final_value"]
            != result["portfolios"]["equal-notional"]["final_value"]
        ), engine


def test_framework_workers_match_native_on_small_real_group_payload(record_property) -> None:
    """Real-data smoke for the worker boundary, not just synthetic prices.

    This catches framework-specific broker/order lifecycle drift. In
    particular, Backtrader's raw per-order submit cash check does not express
    FactorTester's atomic sell-first rebalance contract, so the Backtrader
    group worker must use the portable worker kernel for this operation.
    """
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    payload = _real_group_payload_or_skip()
    dispatcher = EngineWorkerDispatcher()
    timings: dict[str, float] = {}
    results = {}
    for engine in ("backtrader", "qlib", "zipline"):
        started = time.perf_counter()
        results[engine] = dispatcher.dispatch(WorkerRequest(
            f"real-group-{engine}", engine, RUN_STRATEGY_INTENTS, payload
        ), timeout_seconds=120).result
        timings[engine] = time.perf_counter() - started
    started = time.perf_counter()
    results["native"] = run_native(payload)
    timings["native"] = time.perf_counter() - started
    record_property("framework_worker_timings_seconds", {
        engine: round(elapsed, 6) for engine, elapsed in timings.items()
    })
    assert all(elapsed >= 0.0 for elapsed in timings.values())

    for strategy in ("top-momentum", "long-short"):
        traces = {
            engine: result["target_trace"][strategy]
            for engine, result in results.items()
        }
        assert traces == {engine: traces["native"] for engine in traces}

        equity = {
            engine: result["portfolios"][strategy]["equity_curve"]
            for engine, result in results.items()
        }
        assert equity == {engine: equity["native"] for engine in equity}

        positions = {
            engine: result["portfolios"][strategy]["position_curve"]
            for engine, result in results.items()
        }
        assert positions == {engine: positions["native"] for engine in positions}


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
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
                "margin_mode": "proportional_scale",
                "collateral_fraction": 0.05,
            }],
    }
    if engine == "native":
        from tools.testers.backtest.engines.workers.runners.native import run_group_strategy

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
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 5)]
    payload = {
        "timestamps": timestamps,
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0] * 4},
        "volumes": {"asset-a": [100.0] * 4},
        "membership": [[[True]]] * 4,
        "signal_updates": [[True]] * 4,
        "initial_cash": 100_000.0,
        "strategy_configs": [_strategy_settings(
            strategy_id="group-1",
            allocation_policy="equal_notional",
            liquidity_mode="volume_participation",
            participation_rate=0.1,
        )],
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
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 4)]
    config = {
        "strategy_id": "group-1",
        "allocation_policy": "equal_notional",
        "rebalance_trigger": "on_factor_signal",
        "position_policy": "buy_and_hold",
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


def test_framework_rebalance_nets_same_event_and_sizes_buys_after_fees() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    timestamps = [f"2024-01-0{day}T00:00:00" for day in range(1, 5)]
    payload = {
        "timestamps": timestamps,
        "instruments": ["asset-a", "asset-b"],
        "prices": {"asset-a": [100.0] * 4, "asset-b": [100.0] * 4},
        "membership": [
            [[True, False]],
            [[True, False]],
            [[False, True]],
            [[False, True]],
        ],
        "signal_updates": [[True], [False], [True], [False]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "multipliers": [[1.0, 1.0]] * 4,
            "lot_sizes": [[1.0, 1.0]] * 4,
            "margin_ratios": [[1.0, 1.0]] * 4,
        },
        "strategy_configs": [{
            "strategy_id": "group-1",
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
            "fee_rate": 0.001,
            "collect_execution_trace": True,
        }],
    }
    dispatcher = EngineWorkerDispatcher()
    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"net-fee-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("backtrader", "qlib", "zipline")
    }
    results["native"] = run_native(payload)

    assert all(
        result["target_trace"]["group-1"] == {
            "2024-01-01T00:00:00": {"asset-a": 1.0},
            "2024-01-03T00:00:00": {"asset-b": 1.0},
        }
        for result in results.values()
    )
    positions = {
        engine: result["portfolios"]["group-1"]["positions"]
        for engine, result in results.items()
    }
    assert positions == {
        engine: {"asset-a": 0.0, "asset-b": 997.0}
        for engine in results
    }
    position_curves = {
        engine: result["portfolios"]["group-1"]["position_curve"]
        for engine, result in results.items()
    }
    assert position_curves == {
        engine: position_curves["native"]
        for engine in results
    }
    equity_curves = {
        engine: result["portfolios"]["group-1"]["equity_curve"]
        for engine, result in results.items()
    }
    assert equity_curves == {
        engine: equity_curves["native"]
        for engine in results
    }
    execution_traces = {
        engine: result["execution_trace"]["group-1"]
        for engine, result in results.items()
    }
    assert execution_traces == {
        engine: execution_traces["native"]
        for engine in results
    }
    rebalance_trace = execution_traces["native"]["2024-01-04T00:00:00"]
    assert rebalance_trace["delta"] == {"asset-a": -999.0, "asset-b": 997.0}
    assert rebalance_trace["target_size"] == {"asset-a": 0.0, "asset-b": 997.0}
    assert rebalance_trace["cash_available_after_sells"] == pytest.approx(99_800.2)
    assert rebalance_trace["buy_cost_with_fee"] == pytest.approx(99_799.7)
    final_values = {
        engine: result["portfolios"]["group-1"]["final_value"]
        for engine, result in results.items()
    }
    assert final_values == {
        engine: final_values["native"]
        for engine in results
    }


def test_framework_execution_timing_changes_returns_without_changing_targets() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    base_payload: dict[str, Any] = {
        "timestamps": [f"2024-01-0{day}T00:00:00" for day in range(1, 4)],
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0, 200.0, 200.0]},
        "membership": [[[True]], [[True]], [[True]]],
        "signal_updates": [[True], [False], [False]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "multipliers": [[1.0], [1.0], [1.0]],
            "lot_sizes": [[1.0], [1.0], [1.0]],
            "margin_ratios": [[1.0], [1.0], [1.0]],
        },
        "strategy_configs": [{
            "strategy_id": "group-1",
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "buy_and_hold",
        }],
    }

    same_bar_payload = {
        **base_payload,
        "strategy_configs": [{
            **base_payload["strategy_configs"][0],
            "execution_timing": "same_bar",
        }],
    }
    next_bar_payload = {
        **base_payload,
        "strategy_configs": [{
            **base_payload["strategy_configs"][0],
            "execution_timing": "next_bar",
        }],
    }
    same_bar = run_native(same_bar_payload)
    next_bar = run_native(next_bar_payload)

    assert same_bar["target_trace"] == next_bar["target_trace"]
    assert same_bar["portfolios"]["group-1"]["positions"]["asset-a"] == 1000.0
    # The next-bar order is intended from the signal row, but the final
    # broker cash check happens at the actual execution row. At 200.0, only
    # 500 contracts fit in the 100_000 cash ledger.
    assert next_bar["portfolios"]["group-1"]["positions"]["asset-a"] == 500.0
    assert same_bar["portfolios"]["group-1"]["final_value"] == 200_000.0
    assert next_bar["portfolios"]["group-1"]["final_value"] == 100_000.0


def test_execution_delay_bars_is_a_matching_parameter_not_slippage() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy

    payload = {
        "timestamps": [f"2024-01-0{day}T00:00:00" for day in range(1, 5)],
        "instruments": ["asset-a"],
        "prices": {"asset-a": [100.0, 200.0, 400.0, 400.0]},
        "membership": [[[True]], [[True]], [[True]], [[True]]],
        "signal_updates": [[True], [False], [False], [False]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "multipliers": [[1.0], [1.0], [1.0], [1.0]],
            "lot_sizes": [[1.0], [1.0], [1.0], [1.0]],
            "margin_ratios": [[1.0], [1.0], [1.0], [1.0]],
        },
        "strategy_configs": [_strategy_settings(
            strategy_id="group-1",
            allocation_policy="equal_notional",
            position_policy="buy_and_hold",
            execution_timing="next_bar",
            execution_delay_bars=2,
            slippage_mode="none",
        )],
    }

    result = run_group_strategy(payload)

    assert result["portfolios"]["group-1"]["position_curve"] == {
        "2024-01-01T00:00:00": {"asset-a": 0.0},
        "2024-01-02T00:00:00": {"asset-a": 0.0},
        "2024-01-03T00:00:00": {"asset-a": 250.0},
        "2024-01-04T00:00:00": {"asset-a": 250.0},
    }
    assert result["portfolios"]["group-1"]["final_value"] == 100_000.0


def test_framework_group_execution_matches_with_multiplier_fee_and_timing() -> None:
    from tools.testers.backtest.engines.workers.runners.native import run_group_strategy as run_native

    payload = {
        "timestamps": [f"2024-01-0{day}T00:00:00" for day in range(1, 5)],
        "instruments": ["asset-a", "asset-b"],
        "prices": {
            "asset-a": [100.0, 110.0, 120.0, 130.0],
            "asset-b": [200.0, 190.0, 180.0, 170.0],
        },
        "membership": [
            [[True, False]],
            [[True, False]],
            [[False, True]],
            [[False, True]],
        ],
        "signal_updates": [[True], [False], [True], [False]],
        "initial_cash": 100_000.0,
        "market_rules": {
            "multipliers": [[10.0, 20.0]] * 4,
            "lot_sizes": [[1.0, 1.0]] * 4,
            "margin_ratios": [[1.0, 1.0]] * 4,
        },
        "strategy_configs": [{
            "strategy_id": "group-1",
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
            "execution_timing": "next_bar",
            "fee_rate": 0.001,
            "collect_execution_trace": True,
        }],
    }
    dispatcher = EngineWorkerDispatcher()
    results = {
        engine: dispatcher.dispatch(WorkerRequest(
            f"multiplier-fee-{engine}", engine, "run_group_strategy", payload
        )).result
        for engine in ("qlib", "zipline")
    }
    results["native"] = run_native(payload)
    backtrader = dispatcher.dispatch(WorkerRequest(
        "multiplier-fee-backtrader", "backtrader", "run_group_strategy", payload
    )).result

    assert {
        engine: result["target_trace"]["group-1"]
        for engine, result in results.items()
    } == {
        engine: results["native"]["target_trace"]["group-1"]
        for engine in results
    }
    assert {
        engine: result["portfolios"]["group-1"]["position_curve"]
        for engine, result in results.items()
    } == {
        engine: results["native"]["portfolios"]["group-1"]["position_curve"]
        for engine in results
    }
    assert {
        engine: result["portfolios"]["group-1"]["equity_curve"]
        for engine, result in results.items()
    } == {
        engine: results["native"]["portfolios"]["group-1"]["equity_curve"]
        for engine in results
    }
    assert {
        engine: result["execution_trace"]["group-1"]
        for engine, result in results.items()
    } == {
        engine: results["native"]["execution_trace"]["group-1"]
        for engine in results
    }
    # Backtrader's raw broker behavior remains covered by run_target_weights.
    # The higher-level strategy-intent operation must match FactorTester's
    # atomic sell-first, execution-bar resizing contract.
    assert backtrader["target_trace"]["group-1"] == results["native"]["target_trace"]["group-1"]
    assert (
        backtrader["portfolios"]["group-1"]["position_curve"]
        == results["native"]["portfolios"]["group-1"]["position_curve"]
    )
    assert (
        backtrader["portfolios"]["group-1"]["equity_curve"]
        == results["native"]["portfolios"]["group-1"]["equity_curve"]
    )
