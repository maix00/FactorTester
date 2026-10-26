from dataclasses import dataclass

from tools.factors.events import (
    EVENT_SCHEMA_VERSION,
    EventId,
    EventRef,
    Occurrence,
    resolve_event_ref,
)


@dataclass
class Line:
    values: dict[EventId, int]

    def latest(self, event):
        return self.values.get(event)


def test_event_ref_serializes_without_runtime_objects():
    ref = EventRef(EventId.TRADING_DAY_START, Occurrence.LATEST, 5)
    encoded = ref.to_dict()
    assert encoded["schema"] == EVENT_SCHEMA_VERSION
    assert EventRef.from_dict(encoded) == ref


def test_event_boundary_resolves_from_runtime_event_line():
    line = Line({EventId.TRADING_DAY_START: 100})
    assert resolve_event_ref(
        EventRef(EventId.TRADING_DAY_START), line, 120,
    ) == 100
    assert resolve_event_ref(
        EventRef(EventId.TRADING_SESSION_START), line, 120,
    ) is None
