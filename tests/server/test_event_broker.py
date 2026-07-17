from server.jobs.events import EventBroker


def test_broker_reconnect_returns_gap_and_current_live_snapshots() -> None:
    broker = EventBroker(max_events_per_job=2)
    broker.publish("job-1", "activity_manifest", {"phases": ["load", "run"]})
    broker.publish("job-1", "progress", {"completed": 1, "total": 3})
    broker.publish("job-1", "activity", {"flow": "load"})
    broker.publish("job-1", "progress", {"completed": 2, "total": 3})

    snapshot = broker.read("job-1", after=1)

    assert snapshot["gap"] == {
        "requested_seq": 1,
        "oldest_seq": 3,
        "newest_seq": 4,
    }
    assert snapshot["latest_progress"]["data"]["completed"] == 2
    assert snapshot["manifest"]["data"]["phases"] == ["load", "run"]
    assert [event["seq"] for event in snapshot["events"]] == [3, 4]


def test_broker_terminal_event_closes_live_stream_without_database_history() -> None:
    broker = EventBroker()
    broker.publish("job-1", "result", {"success": True})

    snapshot = broker.wait("job-1", after=1, timeout=0.01)

    assert snapshot["closed"] is True
    assert snapshot["events"] == []
