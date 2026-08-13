from __future__ import annotations

import threading
import time

import pytest

from server.manager.data_plane.relay import (
    RelayConflict,
    RelayRegistry,
    RelayTimeout,
)


def test_relay_streams_without_persisting_and_preserves_chunk_order() -> None:
    registry = RelayRegistry(max_buffer_bytes=6, rendezvous_timeout=1.0)
    producer = registry.attach_producer("attempt-1", expected_bytes=9)
    consumer = registry.attach_consumer("attempt-1")
    observed: list[bytes] = []

    thread = threading.Thread(
        target=lambda: observed.extend(consumer.iter_chunks()),
        daemon=True,
    )
    thread.start()
    for chunk in (b"abc", b"def", b"ghi"):
        producer.write(chunk)
    producer.finish()
    thread.join(timeout=1.0)

    assert observed == [b"abc", b"def", b"ghi"]
    assert consumer.bytes_read == 9
    assert registry.get("attempt-1") is None


def test_bounded_relay_applies_backpressure_until_consumer_reads() -> None:
    registry = RelayRegistry(max_buffer_bytes=4, rendezvous_timeout=1.0)
    producer = registry.attach_producer("attempt-1", expected_bytes=8)
    consumer = registry.attach_consumer("attempt-1")
    producer.write(b"1234")
    completed = threading.Event()

    thread = threading.Thread(
        target=lambda: (producer.write(b"5678"), completed.set()),
        daemon=True,
    )
    thread.start()
    time.sleep(0.03)
    assert not completed.is_set()

    iterator = consumer.iter_chunks()
    assert next(iterator) == b"1234"
    thread.join(timeout=1.0)
    assert completed.is_set()
    producer.finish()
    assert list(iterator) == [b"5678"]


def test_duplicate_side_and_size_mismatch_fail_explicitly() -> None:
    registry = RelayRegistry(max_buffer_bytes=8, rendezvous_timeout=0.05)
    producer = registry.attach_producer("attempt-1", expected_bytes=3)
    with pytest.raises(RelayConflict, match="producer"):
        registry.attach_producer("attempt-1", expected_bytes=3)
    registry.attach_consumer("attempt-1")
    producer.write(b"ab")
    with pytest.raises(ValueError, match="expected 3"):
        producer.finish()


def test_unmatched_consumer_times_out_and_session_is_removed() -> None:
    registry = RelayRegistry(max_buffer_bytes=8, rendezvous_timeout=0.03)
    consumer = registry.attach_consumer("attempt-1")

    with pytest.raises(RelayTimeout, match="producer"):
        list(consumer.iter_chunks())

    assert registry.get("attempt-1") is None
