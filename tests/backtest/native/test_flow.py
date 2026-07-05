from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, FlowBinding, FlowDefinition, Phase
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
    flow_def: ClassVar[FlowDefinition] = FlowDefinition(
        "shared_lookup", inputs=(), outputs=(a,), compute=lambda account, ctx: None,
    )
    bound_flow: ClassVar[FlowBinding] = flow_def.bind(
        name="shared_lookup_on_signal",
        phase=Phase.PER_EVENT,
        event_kind=EventKind.SIGNAL,
    )


def test_flow_owner_autofilled():
    assert _DummyModule.flow_one.owner == "_DummyModule"
    assert _DummyModule.flow_one.qualified_name == "_DummyModule.flow_one"
    assert _DummyModule.flow_def.owner == "_DummyModule"
    assert _DummyModule.bound_flow.owner == "_DummyModule"
    assert _DummyModule.bound_flow.qualified_name == "_DummyModule.shared_lookup_on_signal"


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


def test_flow_definition_binding_can_override_display_name():
    assert _DummyModule.bound_flow.definition_name == "shared_lookup"
    assert _DummyModule.bound_flow.effective_name == "shared_lookup_on_signal"
