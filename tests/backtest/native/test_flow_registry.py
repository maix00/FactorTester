from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, FlowDefinition, Phase
from tools.testers.backtest.engines.native.scheduler import FlowRegistry


def test_resolve_keeps_definition_name_for_bound_flow():
    definition = FlowDefinition(
        "lookup_market_snapshot",
        inputs=(),
        outputs=(),
        compute=lambda account, ctx: None,
        description="读取市场快照",
    )
    flow = definition.bind(
        name="lookup_current_prices_on_signal",
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
        description="读取信号时点市场快照",
    )
    registry = FlowRegistry()
    registry.register_flow(flow)

    resolved = registry.resolve()
    assert len(resolved) == 1
    assert resolved[0].name == "lookup_current_prices_on_signal"
    assert resolved[0].definition_name == "lookup_market_snapshot"
    assert resolved[0].effective_description == "读取信号时点市场快照"


def test_register_flow_duplicate_name_raises():
    flow1 = Flow("dup", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=lambda a, c: None)
    flow2 = Flow("dup", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=lambda a, c: None)
    registry = FlowRegistry()
    registry.register_flow(flow1)
    with pytest.raises(ValueError):
        registry.register_flow(flow2)
