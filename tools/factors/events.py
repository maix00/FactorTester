"""Stable event contract for factor definitions.

Factors reference event ids from this module, never Nautilus objects.  A
runtime (Nautilus adapter, research backtest, live engine) emits occurrences
for these ids; the factor interval kernel only queries occurrences.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

EVENT_SCHEMA_VERSION = "event:v1"


class EventId(str, Enum):
    """Authoritative event ids used by factor:v2 definitions."""

    TRADING_DAY_START = "trading_day_start"
    TRADING_SESSION_START = "trading_session_start"
    CONTRACT_ROLL = "contract_roll"
    INSTRUMENT_STATUS = "instrument_status"
    BAR = "bar"


class Occurrence(str, Enum):
    LATEST = "latest"
    PREVIOUS = "previous"
    FIRST = "first"


@dataclass(frozen=True, slots=True)
class EventRef:
    """A serializable factor boundary reference."""

    event: EventId
    occurrence: Occurrence = Occurrence.LATEST
    offset: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.offset, int):
            raise TypeError("event offset must be an integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": EVENT_SCHEMA_VERSION,
            "event": self.event.value,
            "occurrence": self.occurrence.value,
            "offset": self.offset,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EventRef":
        if value.get("schema") != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported event schema")
        return cls(
            EventId(str(value["event"])),
            Occurrence(str(value.get("occurrence") or "latest")),
            int(value.get("offset") or 0),
        )


class EventLine(Protocol):
    """Runtime view of emitted event occurrences, indexed by bar ordinal."""

    def latest(self, event: EventId) -> int | None: ...

    def previous(self, event: EventId) -> int | None: ...

    def first(self, event: EventId) -> int | None: ...


def resolve_event_ref(
    ref: EventRef, line: EventLine, current_index: int,
) -> int | None:
    """Resolve a factor boundary to an absolute bar ordinal."""
    if ref.occurrence is Occurrence.FIRST:
        occurrence = line.first(ref.event)
    elif ref.occurrence is Occurrence.PREVIOUS:
        occurrence = line.previous(ref.event)
    else:
        occurrence = line.latest(ref.event)
    if occurrence is None:
        return None
    if ref.offset < 0:
        occurrence = max(0, occurrence + ref.offset)
    else:
        occurrence += ref.offset
    return occurrence
