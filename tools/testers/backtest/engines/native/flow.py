"""Phase/Flow/FlowDefinition/FlowBinding — computation units in the native
event-driven backtest engine.

FlowDefinition describes what a step does. FlowBinding describes where that
step runs (phase/event kind/order). The legacy Flow constructor remains as a
single-binding convenience because many modules still declare one-off flows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from .events import EventKind
from .fields import FieldRef


class Phase(str, Enum):
    def __new__(cls, value: str, label: str):
        member = str.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member

    PRE_REPLAY = ("pre_replay", "回放准备")
    PER_EVENT = ("per_event", "事件回放")
    POST_REPLAY = ("post_replay", "结果整理")


def phase_label(value: Phase | str) -> str:
    """Return the label declared by ``Phase`` for a phase value."""
    try:
        return Phase(value).label
    except ValueError:
        return str(value)


@dataclass(frozen=True)
class FlowDefinition:
    name: str
    inputs: tuple[FieldRef, ...]
    outputs: tuple[FieldRef, ...]
    compute: Callable[..., None]
    owner: str = ""  # auto-filled by ExecutableModule.__init_subclass__, like FieldRef.owner —
                      # only happens if this definition/binding is assigned as a class attribute,
                      # not just buried anonymously inside a `flows` tuple literal
    description: str = ""  # human-readable label for progress/UI display
    strategy_scoped: bool = False
    # Infrastructure boundary: materializes event-time inputs into
    # FlowContext. It is still scheduler-visible for dependency ordering
    # and no-lookahead guarantees; UIs may group or hide it.
    input_materialization: bool = False

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}"

    @property
    def effective_description(self) -> str:
        return self.description or self.name

    def bind(
        self,
        *,
        phase: Phase,
        event_kind: EventKind | None = None,
        order: int = 100,
        after: tuple[Any, ...] = (),
        before: tuple[Any, ...] = (),
        name: str | None = None,
        description: str | None = None,
        strategy_scoped: bool | None = None,
        input_materialization: bool | None = None,
    ) -> "FlowBinding":
        return FlowBinding(
            definition=self,
            phase=phase,
            event_kind=event_kind,
            order=order,
            after=after,
            before=before,
            name=name,
            description=description,
            strategy_scoped=strategy_scoped,
            input_materialization=input_materialization,
        )

    def __repr__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True)
class FlowBinding:
    definition: FlowDefinition
    phase: Phase
    event_kind: EventKind | None = None  # required when phase=PER_EVENT; must be None otherwise
    order: int = 100  # sort key — only compared within the same (phase, event_kind) group
    after: tuple[Any, ...] = ()   # references other bindings/definitions directly, not strings
    before: tuple[Any, ...] = ()
    name: str | None = None
    description: str | None = None
    strategy_scoped: bool | None = None
    input_materialization: bool | None = None

    @property
    def definition_name(self) -> str:
        return self.definition.name

    @property
    def inputs(self) -> tuple[FieldRef, ...]:
        return self.definition.inputs

    @property
    def outputs(self) -> tuple[FieldRef, ...]:
        return self.definition.outputs

    @property
    def compute(self) -> Callable[..., None]:
        return self.definition.compute

    @property
    def owner(self) -> str:
        return self.definition.owner

    @property
    def effective_name(self) -> str:
        return self.name or self.definition.name

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.effective_name}"

    @property
    def effective_description(self) -> str:
        return self.description or self.definition.description or self.effective_name

    @property
    def effective_strategy_scoped(self) -> bool:
        if self.strategy_scoped is not None:
            return self.strategy_scoped
        return self.definition.strategy_scoped

    @property
    def effective_input_materialization(self) -> bool:
        if self.input_materialization is not None:
            return self.input_materialization
        return self.definition.input_materialization

    def __repr__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True)
class Flow:
    name: str
    inputs: tuple[FieldRef, ...]
    outputs: tuple[FieldRef, ...]
    phase: Phase
    compute: Callable[..., None]
    owner: str = ""  # auto-filled by ExecutableModule.__init_subclass__, like FieldRef.owner —
                      # only happens if this Flow is assigned as a class attribute, not just
                      # buried anonymously inside a `flows` tuple literal
    event_kind: EventKind | None = None  # required when phase=PER_EVENT; must be None otherwise
    order: int = 100  # sort key — only compared within the same (phase, event_kind) group
    after: tuple[Any, ...] = ()   # references other Flow objects directly, not strings/FieldRefs
    before: tuple[Any, ...] = ()
    description: str = ""  # human-readable label for progress/UI display
        # (e.g. "更新账本现金"); falls back to `name` when not given -- not
        # every Flow has been given a real description yet, this lets the
        # rest of the engine read `effective_description` uniformly while
        # that fills in incrementally.
    strategy_scoped: bool = False
        # PRE/POST flows with strategy_scoped=True run only when at least one
        # StrategyConfig activates the flow name. Generic setup/teardown flows
        # keep the default and run once for the whole run state.
    # Same meaning as FlowDefinition.input_materialization for legacy
    # single-binding Flow declarations.
    input_materialization: bool = False

    @property
    def definition_name(self) -> str:
        return self.name

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}"

    @property
    def effective_description(self) -> str:
        return self.description or self.name

    def bind(
        self,
        *,
        phase: Phase | None = None,
        event_kind: EventKind | None = None,
        order: int | None = None,
        after: tuple[Any, ...] | None = None,
        before: tuple[Any, ...] | None = None,
        name: str | None = None,
        description: str | None = None,
        strategy_scoped: bool | None = None,
    ) -> FlowBinding:
        definition = FlowDefinition(
            self.name,
            inputs=self.inputs,
            outputs=self.outputs,
            compute=self.compute,
            owner=self.owner,
            description=self.description,
            strategy_scoped=self.strategy_scoped,
            input_materialization=self.input_materialization,
        )
        return definition.bind(
            phase=phase or self.phase,
            event_kind=self.event_kind if event_kind is None else event_kind,
            order=self.order if order is None else order,
            after=self.after if after is None else after,
            before=self.before if before is None else before,
            name=name,
            description=description,
            strategy_scoped=strategy_scoped,
        )

    def __repr__(self) -> str:
        return self.qualified_name
