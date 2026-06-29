from __future__ import annotations

import pytest

from tools.testers.backtest.engines.native.flow import Flow, FlowOverride, Phase
from tools.testers.backtest.engines.native.scheduler import FlowRegistry


def test_resolve_composes_override_chain_in_registration_order():
    calls: list[str] = []

    def base_compute(account, ctx) -> None:
        calls.append("base")

    def override1(account, ctx, base) -> None:
        calls.append("ov1-before")
        base(account, ctx)
        calls.append("ov1-after")

    def override2(account, ctx, base) -> None:
        calls.append("ov2-before")
        base(account, ctx)
        calls.append("ov2-after")

    flow = Flow("f", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=base_compute)
    registry = FlowRegistry()
    registry.register_flow(flow)
    registry.register_override(FlowOverride(flow_names=("f",), compute=override1))
    registry.register_override(FlowOverride(flow_names=("f",), compute=override2))

    resolved = registry.resolve()
    assert len(resolved) == 1
    resolved[0].compute(None, None)
    # registered ov1 then ov2 -> ov2 wraps ov1 wraps base -> ov2 runs outermost
    assert calls == ["ov2-before", "ov1-before", "base", "ov1-after", "ov2-after"]


def test_resolve_merges_extra_inputs():
    from tools.testers.backtest.modules.base import FieldRef

    extra = FieldRef("extra", owner="X")
    flow = Flow("f", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=lambda a, c: None)
    registry = FlowRegistry()
    registry.register_flow(flow)
    registry.register_override(FlowOverride(flow_names=("f",), extra_inputs=(extra,), compute=lambda a, c, b: b(a, c)))
    resolved = registry.resolve()
    assert extra in resolved[0].inputs


def test_register_flow_duplicate_name_raises():
    flow1 = Flow("dup", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=lambda a, c: None)
    flow2 = Flow("dup", inputs=(), outputs=(), phase=Phase.PRE_REPLAY, compute=lambda a, c: None)
    registry = FlowRegistry()
    registry.register_flow(flow1)
    with pytest.raises(ValueError):
        registry.register_flow(flow2)
