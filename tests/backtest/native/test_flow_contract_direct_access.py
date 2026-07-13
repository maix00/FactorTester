from __future__ import annotations

import pytest

from tools.data.types.data_money import DataMoney
from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.engines.native.ledger import Ledger, LedgerState
from tools.testers.backtest.engines.native.scheduler import EventQueue, ResolvedFlow, run
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.cash_pool import CashPoolModule, set_cash_for_ledger_pool
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.ledger_module import LedgerModule


def _flow(inputs=()):
    def compute(state, ctx):
        strategy = next(iter(ctx.active_strategies))
        state.config_for(strategy).get(GroupMembershipModule.allocation_policy)
        state.ledger_config_for("private:test").fixed_fee_rate

    return ResolvedFlow(
        name="direct_config_read",
        owner="TestModule",
        inputs=tuple(inputs),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute,
        description="direct config read",
    )


def _state() -> BacktestRunState:
    strategy = Strategy(alias="S")
    ledger = Ledger(name="private:test")
    config = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"direct_config_read"}),
        field_values={GroupMembershipModule.allocation_policy: "equal_notional"},
    )
    state = BacktestRunState(
        ledgers={ledger: LedgerState(strategy=strategy, base_currency="CNY", ledger=ledger)},
        strategy_configs={strategy: config},
    )
    state.ledger_configs[ledger] = LedgerConfig(fixed_fee_rate=0.0003)
    return state


def test_flow_contract_audits_direct_strategy_and_ledger_config_reads():
    steps = []

    run(
        _state(),
        EventQueue(),
        [_flow()],
        audit_flow_contract=True,
        step_mode=True,
        step_callback=steps.append,
    )

    violations = steps[-1]["input_contract_violations"]
    assert {item["field"] for item in violations} == {
        "GroupMembershipModule.allocation_policy",
        "FeeModule.fixed_fee_rate",
    }
    assert {item["access"] for item in violations} == {"read"}


def test_flow_contract_accepts_declared_direct_config_reads():
    steps = []

    run(
        _state(),
        EventQueue(),
        [_flow(inputs=(GroupMembershipModule.allocation_policy, FeeModule.fixed_fee_rate))],
        audit_flow_contract=True,
        step_mode=True,
        step_callback=steps.append,
    )

    assert steps[-1]["input_contract_violations"] == []


def test_flow_contract_audits_direct_strategy_field_values_mapping_reads():
    def compute(state, ctx):
        strategy = next(iter(ctx.active_strategies))
        state.config_for(strategy).field_values[GroupMembershipModule.allocation_policy]

    flow = ResolvedFlow(
        name="direct_field_values_read",
        owner="TestModule",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute,
        description="direct field_values read",
    )
    state = _state()
    strategy = next(iter(state.strategy_configs))
    state.strategy_configs[strategy] = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"direct_field_values_read"}),
        field_values={GroupMembershipModule.allocation_policy: "equal_notional"},
    )
    steps = []

    run(
        state,
        EventQueue(),
        [flow],
        audit_flow_contract=True,
        step_mode=True,
        step_callback=steps.append,
    )

    assert steps[-1]["input_contract_violations"] == [{
        "flow": "TestModule.direct_field_values_read",
        "phase": "pre_replay",
        "event_kind": "",
        "access": "read",
        "field": "GroupMembershipModule.allocation_policy",
    }]


def test_step_contract_audits_direct_ledger_field_writes():
    def compute(state, ctx):
        strategy = next(iter(ctx.active_strategies))
        ledger = state.ledger_for_strategy(strategy)
        ledger.set(LedgerModule.positions, {"P": 1})

    flow = ResolvedFlow(
        name="direct_ledger_write",
        owner="TestModule",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute,
        description="direct ledger write",
    )
    state = _state()
    strategy = next(iter(state.strategy_configs))
    state.strategy_configs[strategy] = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"direct_ledger_write"}),
    )
    steps = []

    run(
        state,
        EventQueue(),
        [flow],
        audit_flow_contract=True,
        step_mode=True,
        step_callback=steps.append,
    )

    assert steps[-1]["input_contract_violations"] == [{
        "flow": "TestModule.direct_ledger_write",
        "phase": "pre_replay",
        "event_kind": "",
        "access": "write",
        "field": "LedgerModule.positions",
    }]


def test_step_contract_rejects_raw_ledger_fields_mutation():
    def compute(state, ctx):
        strategy = next(iter(ctx.active_strategies))
        ledger = state.ledger_for_strategy(strategy)
        ledger.fields[LedgerModule.positions] = {"P": 1}

    flow = ResolvedFlow(
        name="raw_ledger_write",
        owner="TestModule",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute,
        description="raw ledger write",
    )
    state = _state()
    strategy = next(iter(state.strategy_configs))
    state.strategy_configs[strategy] = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"raw_ledger_write"}),
    )

    with pytest.raises(RuntimeError, match="LedgerState\\[private:.*\\]\\.fields is guarded"):
        run(
            state,
            EventQueue(),
            [flow],
            audit_flow_contract=True,
            step_mode=True,
            step_callback=lambda _: None,
        )


def test_step_contract_audits_cash_pool_setter_and_rejects_raw_cash_mutation():
    def compute_cash_setter(state, ctx):
        strategy = next(iter(ctx.active_strategies))
        ledger = state.ledger_for_strategy(strategy)
        set_cash_for_ledger_pool(
            state,
            ledger,
            DataMoney.from_major(1000.0, currency="CNY", use_minor_units=False),
        )

    setter_flow = ResolvedFlow(
        name="cash_setter_write",
        owner="TestModule",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute_cash_setter,
        description="cash setter write",
    )
    state = _state()
    strategy = next(iter(state.strategy_configs))
    state.strategy_configs[strategy] = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"cash_setter_write"}),
    )
    steps = []
    run(
        state,
        EventQueue(),
        [setter_flow],
        audit_flow_contract=True,
        step_mode=True,
        step_callback=steps.append,
    )
    assert steps[-1]["input_contract_violations"] == [{
        "flow": "TestModule.cash_setter_write",
        "phase": "pre_replay",
        "event_kind": "",
        "access": "write",
        "field": "CashPoolModule.cash",
    }]

    def compute_raw_cash(state, ctx):
        state.cash_pool_store.cash_by_pool["private:test"] = object()

    raw_flow = ResolvedFlow(
        name="raw_cash_write",
        owner="TestModule",
        inputs=(),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        event_kind=None,
        order=1,
        after=(),
        before=(),
        compute=compute_raw_cash,
        description="raw cash write",
    )
    state = _state()
    strategy = next(iter(state.strategy_configs))
    state.strategy_configs[strategy] = StrategyConfig(
        strategy=strategy,
        active_flow_names=frozenset({"raw_cash_write"}),
    )
    with pytest.raises(RuntimeError, match="CashPoolStore\\.cash_by_pool is guarded"):
        run(
            state,
            EventQueue(),
            [raw_flow],
            audit_flow_contract=True,
            step_mode=True,
            step_callback=lambda _: None,
        )
