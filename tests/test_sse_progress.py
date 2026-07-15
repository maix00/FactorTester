from __future__ import annotations

from server.services.sse_progress import SSEProgressEmitter


def test_sse_progress_emits_heartbeat_when_idle():
    emitter = SSEProgressEmitter(heartbeat_interval=0.001)
    chunk = next(emitter._generate())

    assert "event: heartbeat" in chunk
