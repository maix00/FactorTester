"""Phase/Flow/FlowOverride — the unit of computation in the new event-driven
backtest engine. A Flow self-declares which phase and (for PER_EVENT) which
EventKind triggers it; the scheduler reads this directly, it is never wired
externally."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .events import EventKind
from .fields import FieldRef


class Phase(str, Enum):
    PRE_REPLAY = "pre_replay"     # runs once before the replay loop, batched
    PER_EVENT = "per_event"       # runs once per dispatched event of its event_kind
    POST_REPLAY = "post_replay"   # runs once after the replay loop, batched


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
    after: tuple["Flow", ...] = ()   # references other Flow objects directly, not strings/FieldRefs
    before: tuple["Flow", ...] = ()
    description: str = ""  # human-readable label for progress/UI display
        # (e.g. "更新账本现金"); falls back to `name` when not given -- not
        # every Flow has been given a real description yet, this lets the
        # rest of the engine read `effective_description` uniformly while
        # that fills in incrementally.
    strategy_scoped: bool = False
        # PRE/POST flows with strategy_scoped=True run only when at least one
        # StrategyConfig activates the flow name. Generic setup/teardown flows
        # keep the default and run once for the whole run state.

    @property
    def qualified_name(self) -> str:
        return f"{self.owner}.{self.name}"

    @property
    def effective_description(self) -> str:
        return self.description or self.name

    def __repr__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True)
class FlowOverride:
    flow_names: tuple[str, ...]   # one override can target several same-algorithm Flow
                                   # registrations at once (e.g. equity_on_signal + equity_on_order)
    extra_inputs: tuple[FieldRef, ...] = ()
    compute: Callable[..., None] | None = None  # (state, ctx, base_compute) -> None
