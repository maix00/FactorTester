from __future__ import annotations

from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.flow import Phase
from tools.testers.backtest.engines.native.ledger import Ledger, LedgerState
from tools.testers.backtest.engines.native.scheduler import EventQueue, ResolvedFlow, run
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.strategy import Strategy
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
