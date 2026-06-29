from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, FlowOverride, Phase
from tools.testers.backtest.modules.base import ExecutableModule, FieldRef


class _DummyModule(ExecutableModule):
    a: ClassVar[FieldRef[int]] = FieldRef("a")
    b: ClassVar[FieldRef[int]] = FieldRef("b")

    flow_one: ClassVar[Flow] = Flow(
        "flow_one", inputs=(), outputs=(a,),
        phase=Phase.PRE_REPLAY, compute=lambda account, ctx: None,
    )
    flow_two: ClassVar[Flow] = Flow(
        "flow_two", inputs=(a,), outputs=(b,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=20,
        after=(flow_one,), compute=lambda account, ctx: None,
    )


def test_flow_owner_autofilled():
    assert _DummyModule.flow_one.owner == "_DummyModule"
    assert _DummyModule.flow_one.qualified_name == "_DummyModule.flow_one"


def test_flow_after_references_flow_object():
    assert _DummyModule.flow_two.after == (_DummyModule.flow_one,)
    assert _DummyModule.flow_two.after[0].name == "flow_one"


def test_flow_is_frozen_dataclass():
    import dataclasses
    assert dataclasses.is_dataclass(Flow)
    try:
        _DummyModule.flow_one.order = 5  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Flow should be frozen")


def test_flow_override_chain_composition():
    calls: list[str] = []

    def base_compute(account, ctx) -> None:
        calls.append("base")

    def override_compute(account, ctx, base_compute) -> None:
        calls.append("override")
        base_compute(account, ctx)

    override = FlowOverride(flow_names=("flow_one",), compute=override_compute)

    def wrap(ov_compute, base):
        def wrapped(account, ctx):
            ov_compute(account, ctx, base)
        return wrapped

    wrapped = wrap(override.compute, base_compute)
    wrapped(None, None)
    assert calls == ["override", "base"]
