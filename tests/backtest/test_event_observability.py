from __future__ import annotations

import logging

import pandas as pd
import pytest

from tools.testers.backtest.engines.native.contracts import RunIdentity
from tools.testers.backtest.engines.observability.events import ProgressObserver, StructuredEventLogger
from tools.testers.backtest.engines.native.runtime import EventRuntime, EventTopic, ReplayEventSource


def test_two_users_receive_independent_structured_event_context(caplog) -> None:
    logger = logging.getLogger("test.backtest.events")
    caplog.set_level(logging.INFO, logger=logger.name)
    for user_id, page_uuid in (("user-a", "page-a"), ("user-b", "page-b")):
        run_id = f"run-{user_id}"
        runtime = EventRuntime(run_id)
        runtime.add_source(ReplayEventSource(
            [pd.Timestamp("2026-01-01")],
            [user_id],
            topic=EventTopic.REPORT,
        ))
        runtime.add_observer(StructuredEventLogger(
            RunIdentity(
                run_id=run_id,
                user_id=user_id,
                page_uuid=page_uuid,
                session_id=f"session-{user_id}",
            ),
            logger,
        ))
        runtime.run()

    records = [record for record in caplog.records if record.message == "backtest_event"]
    assert [(record.run_id, record.user_id, record.page_uuid) for record in records] == [
        ("run-user-a", "user-a", "page-a"),
        ("run-user-b", "user-b", "page-b"),
    ]
    assert logger.handlers == []


def test_progress_is_typed_and_failed_events_are_journaled() -> None:
    updates = []
    runtime = EventRuntime("failed-run")
    runtime.add_source(ReplayEventSource(
        [pd.Timestamp("2026-01-01")], [1], topic=EventTopic.MARKET_DATA
    ))
    runtime.add_observer(ProgressObserver("failed-run", updates.append))

    def fail(event, runtime):
        raise ValueError("bad market event")

    runtime.subscribe(EventTopic.MARKET_DATA, fail)
    with pytest.raises(ValueError, match="bad market event"):
        runtime.run()

    assert len(runtime.journal) == 1
    assert not runtime.journal[0].succeeded
    assert runtime.journal[0].error_type == "ValueError"
    assert len(updates) == 1
    assert not updates[0].succeeded
