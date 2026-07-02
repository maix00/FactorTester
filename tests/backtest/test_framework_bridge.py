"""Framework execution bridge (ADR-030): translation, dispatch, progress, collection."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from tools.testers.backtest.engines.adapters.frameworks import UnsupportedFrameworkPlan
from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.workers import bridge as bridge_module
from tools.testers.backtest.engines.workers.bridge import run_framework_backtest_task
from tools.testers.backtest.engines.workers.contracts import WorkerResponse
from tools.testers.backtest.engines.workers.translator import (
    build_membership_payload,
    translate_market_payload,
    translate_strategy_config,
)
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.liquidity import LiquidityModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.minor_unit import MinorUnitModule
from tools.testers.backtest.modules.slippage import SlippageModule


def _config(alias: str, **field_values: Any) -> tuple[Strategy, StrategyConfig]:
    strategy = Strategy(alias=alias)
    refs = {
        "split_count": GroupMembershipModule.split_count,
        "group_index": GroupMembershipModule.group_index,
        "position_policy": GroupMembershipModule.position_policy,
        "rebalance_trigger": GroupMembershipModule.rebalance_trigger,
        "allocation_policy": GroupMembershipModule.allocation_policy,
        "execution_timing": GroupMembershipModule.execution_timing,
        "execution_delay_bars": GroupMembershipModule.execution_delay_bars,
        "fee_mode": FeeModule.fee_mode,
        "fixed_fee_rate": FeeModule.fixed_fee_rate,
        "margin_mode": MarginModule.margin_mode,
        "fixed_margin_ratio": MarginModule.fixed_margin_ratio,
        "liquidity_mode": LiquidityModule.liquidity_mode,
        "participation_rate": LiquidityModule.participation_rate,
        "slippage_mode": SlippageModule.slippage_mode,
        "slippage_bps": SlippageModule.slippage_bps,
        "initial_capital_major": LedgerModule.initial_capital_major,
        "use_minor_units": MinorUnitModule.use_minor_units,
    }
    values = {refs[name]: value for name, value in field_values.items()}
    return strategy, StrategyConfig(strategy=strategy, field_values=values)


def test_translate_passes_registered_settings_through_by_field_name():
    _, config = _config(
        "g1",
        split_count=5, group_index=2,
        position_policy="rebalance_to_target", rebalance_trigger="on_factor_signal",
        allocation_policy="equal_notional",
        execution_timing="next_bar", execution_delay_bars=1,
        fee_mode="fixed", fixed_fee_rate=0.001,
        margin_mode="none",
        liquidity_mode="volume_participation", participation_rate=0.1,
        slippage_mode="fixed_bps", slippage_bps=10.0,
        initial_capital_major=250_000.0,
    )
    out = translate_strategy_config("g1", config, {}, framework="backtrader", membership_index=3)
    assert out["strategy_id"] == "g1"
    assert out["membership_index"] == 3
    assert out["split_count"] == 5
    assert out["group_index"] == 2
    assert out["allocation_policy"] == "equal_notional"
    assert out["liquidity_mode"] == "volume_participation"
    assert out["participation_rate"] == 0.1
    assert out["slippage_mode"] == "fixed_bps"
    assert out["slippage_bps"] == 10.0
    assert out["initial_capital"] == 250_000.0
    assert out["fee_rate"] == 0.001
    assert out["margin_mode"] == "none"


def test_translate_fee_zero_and_fixed_are_representable():
    _, zero = _config("z", fee_mode="zero")
    assert translate_strategy_config("z", zero, {}, framework="qlib", membership_index=0)["fee_rate"] == 0.0
    _, fixed = _config("f", fee_mode="fixed", fixed_fee_rate=0.0005)
    assert translate_strategy_config("f", fixed, {}, framework="qlib", membership_index=0)["fee_rate"] == 0.0005


def test_translate_rejects_per_leg_fee_schedules_instead_of_flattening():
    _, config = _config("g1", fee_mode="auto")
    with pytest.raises(UnsupportedFrameworkPlan, match="fee_mode"):
        translate_strategy_config("g1", config, {}, framework="backtrader", membership_index=0)


def test_translate_rejects_historical_margin_modes():
    _, config = _config("g1", fee_mode="zero", margin_mode="exact")
    with pytest.raises(UnsupportedFrameworkPlan, match="margin_mode"):
        translate_strategy_config("g1", config, {}, framework="zipline", membership_index=0)


def test_translate_copies_long_short_wiring_from_raw_settings():
    _, config = _config("ls1", fee_mode="zero", margin_mode="none")
    raw = {"strategy_kind": "long_short", "long_indices": [0], "short_indices": [1]}
    out = translate_strategy_config("ls1", config, raw, framework="backtrader", membership_index=2)
    assert out["strategy_kind"] == "long_short"
    assert out["long_indices"] == [0]
    assert out["short_indices"] == [1]


def test_translate_records_minor_unit_fallback_when_requested(monkeypatch):
    # StrategyConfig here is built directly (bypassing strategy_config_builder's
    # default_when resolution), so use_minor_units must be set explicitly --
    # this asserts the translator's own fallback-recording, not the
    # engine_mode="basic" default policy (covered by ledger_module tests).
    _, config = _config("g1", fee_mode="zero", margin_mode="none", use_minor_units=True)
    out = translate_strategy_config("g1", config, {}, framework="qlib", membership_index=0)
    assert out["_setting_fallbacks"] == [{
        "setting_key": "use_minor_units",
        "module": "minor_unit",
        "engine": "qlib",
        "requested_value": True,
        "applied_value": "engine_native",
        "reason": "engine_disabled_value",
    }]


def test_translate_records_no_fallback_when_major_units_requested():
    _, config = _config("g1", fee_mode="zero", margin_mode="none", use_minor_units=False)
    out = translate_strategy_config("g1", config, {}, framework="qlib", membership_index=0)
    assert "_setting_fallbacks" not in out


# ── market payload + membership ─────────────────────────────────────


def _run_state_with_market_data() -> tuple[BacktestRunState, Strategy]:
    run_state = BacktestRunState()
    strategy, config = _config(
        "g1", split_count=2, group_index=1,
        position_policy="rebalance_to_target", rebalance_trigger="on_factor_signal",
        allocation_policy="equal_notional",
        fee_mode="zero", margin_mode="none",
        initial_capital_major=100_000.0,
    )
    run_state.strategy_configs = {strategy: config}
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-01-05 15:00"),
        pd.Timestamp("2026-01-06 15:00"),
        pd.Timestamp("2026-01-07 15:00"),
    ])
    run_state.market_data_store.current_prices_table = pd.DataFrame(
        {"A": [10.0, 11.0, 12.0], "B": [20.0, 19.0, 18.0]}, index=idx,
    )
    signals = pd.DataFrame({"A": [1.0, 1.0, 3.0], "B": [2.0, 2.0, 1.0]}, index=idx)
    run_state.factor_signal_store.put_precomputed_table("k", signals)
    run_state.factor_signal_store.bind_precomputed_table(strategy, "k")
    return run_state, strategy


def test_market_payload_serializes_prices_and_default_rules():
    run_state, _ = _run_state_with_market_data()
    payload = translate_market_payload(run_state)
    assert payload["instruments"] == ["A", "B"]
    assert payload["prices"]["A"] == [10.0, 11.0, 12.0]
    assert len(payload["timestamps"]) == 3
    assert payload["market_rules"]["multipliers"] == [[1.0, 1.0]] * 3
    assert payload["market_rules"]["lot_sizes"] == [[1.0, 1.0]] * 3
    assert payload["market_rules"]["margin_ratios"] == [[1.0, 1.0]] * 3


def test_membership_matches_native_quantile_bucketing():
    run_state, _ = _run_state_with_market_data()
    dialects = [{
        "strategy_id": "g1", "membership_index": 0,
        "split_count": 2, "group_index": 1,
        "rebalance_trigger": "on_factor_signal",
    }]
    idx = run_state.market_data_store.current_prices_table.index
    out = build_membership_payload(run_state, dialects, idx)
    membership = np.asarray(out["membership"], dtype=bool)
    updates = np.asarray(out["signal_updates"], dtype=bool)
    assert membership.shape == (3, 1, 2)
    # group_index=1 of split_count=2 == the higher-signal half:
    # rows 0-1: B(2.0) > A(1.0) → B; row 2: A(3.0) > B(1.0) → A
    assert membership[0, 0].tolist() == [False, True]
    assert membership[1, 0].tolist() == [False, True]
    assert membership[2, 0].tolist() == [True, False]
    assert updates.all()  # on_factor_signal updates every signal row


def test_membership_change_trigger_only_updates_when_members_change():
    run_state, _ = _run_state_with_market_data()
    dialects = [{
        "strategy_id": "g1", "membership_index": 0,
        "split_count": 2, "group_index": 1,
        "rebalance_trigger": "membership_change",
    }]
    idx = run_state.market_data_store.current_prices_table.index
    out = build_membership_payload(run_state, dialects, idx)
    updates = np.asarray(out["signal_updates"], dtype=bool)
    assert updates[:, 0].tolist() == [True, False, True]


# ── bridge end-to-end with a fake dispatcher ───────────────────────


class _FakeDispatcher:
    def __init__(self, result: dict[str, Any]):
        self.result = result
        self.request = None

    def dispatch(self, request, *, timeout_seconds=0.0, progress=None, cancel_event=None):
        self.request = request
        if progress is not None:
            progress({"completed": 1, "total": 3, "event_timestamp": "2026-01-05T15:00:00"})
            progress({"completed": 3, "total": 3, "event_timestamp": "2026-01-07T15:00:00"})
        return WorkerResponse(request.request_id, request.engine, True, self.result)


class _SinkRecorder:
    def __init__(self):
        self.manifests: list[Any] = []
        self.activities: list[dict] = []
        self.progress: list[dict] = []

    def emit_activity_manifest(self, phases):
        self.manifests.append(phases)

    def emit_activity(self, **payload):
        self.activities.append(payload)

    def emit_signal_progress(self, *, completed, total, phase="event_replay", percent=None):
        self.progress.append({"completed": completed, "total": total, "phase": phase})


class _State:
    account = None


def test_bridge_dispatches_translated_payload_and_wraps_result(monkeypatch):
    run_state, strategy = _run_state_with_market_data()
    monkeypatch.setattr(bridge_module, "_run_pre_replay_flows", lambda rs: None)
    worker_result = {
        "engine": "backtrader",
        "portfolios": {"g1": {"equity_curve": {"2026-01-07T15:00:00": 100_500.0}}},
        "target_trace": {"g1": {}},
        "strategy_diagnostics": {"g1": {}},
        "event_count": 3,
        "signal_kind": "precomputed",
    }
    dispatcher = _FakeDispatcher(worker_result)
    sink = _SinkRecorder()
    state = _State()

    execution = run_framework_backtest_task(
        state,
        run_state=run_state,
        engine="backtrader",
        group_owner=[{"group_id": "g1"}],
        settings_by_strategy={"g1": {}},
        run_id="run-1",
        activity_sink=sink,
        dispatcher=dispatcher,
    )

    payload = dispatcher.request.payload
    assert dispatcher.request.engine == "backtrader"
    assert dispatcher.request.operation == "run_group_strategy"
    assert payload["instruments"] == ["A", "B"]
    assert payload["strategy_configs"][0]["strategy_id"] == "g1"
    assert payload["strategy_configs"][0]["fee_rate"] == 0.0
    assert payload["initial_cash"] == 100_000.0
    assert np.asarray(payload["membership"]).shape == (3, 1, 2)

    assert execution["engine_result"]["engine"] == "backtrader"
    assert execution["engine_result"]["portfolios"]["g1"]["equity_curve"]
    assert execution["payload"]["instruments"] == ["A", "B"]
    assert state.account is run_state

    assert len(sink.manifests) == 1
    manifest_keys = [phase["key"] for phase in sink.manifests[0]]
    assert manifest_keys == ["pre_replay", "event_replay", "post_replay"]
    assert sink.progress == [
        {"completed": 1, "total": 3, "phase": "event_replay"},
        {"completed": 3, "total": 3, "phase": "event_replay"},
    ]
    phases = [a["phase"] for a in sink.activities]
    assert phases == ["pre_replay", "event_replay", "post_replay"]


def test_bridge_rejects_unknown_engine():
    with pytest.raises(ValueError, match="unknown framework engine"):
        run_framework_backtest_task(
            _State(), run_state=BacktestRunState(), engine="excel",
            group_owner=[], settings_by_strategy={}, run_id="r",
        )


def test_backtester_routes_non_native_engine_to_bridge(monkeypatch):
    from tools.testers.backtest.engines.native import backtester
    from tools.testers.backtest.modules.engine import EngineModule

    strategy = Strategy(alias="g1")
    config = StrategyConfig(strategy=strategy, field_values={EngineModule.engine: "backtrader"})
    run_state = BacktestRunState()
    run_state.strategy_configs = {strategy: config}

    captured: dict[str, Any] = {}

    def _fake_bridge(state, **kwargs):
        captured.update(kwargs)
        return {"run_id": kwargs["run_id"], "engine_result": {"engine": kwargs["engine"]}}

    monkeypatch.setattr(
        "tools.testers.backtest.engines.workers.bridge.run_framework_backtest_task",
        _fake_bridge,
    )
    result = backtester.run_backtest_task(
        _State(), run_state=run_state, group_owner=[], settings_by_strategy={}, run_id="r-9",
    )
    assert captured["engine"] == "backtrader"
    assert result["engine_result"]["engine"] == "backtrader"
