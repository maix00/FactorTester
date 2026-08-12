from __future__ import annotations

import hashlib
import json

from server.jobs.json_artifact_writer import (
    write_json_artifact,
    write_json_mapping_artifact,
)


def test_json_artifact_is_atomic_and_uses_a_bounded_output_buffer(tmp_path):
    target = tmp_path / "large.json"
    payload = {
        "rows": [
            {"timestamp": index, "value": float(index), "label": "中国期货"}
            for index in range(20_000)
        ]
    }

    receipt = write_json_artifact(target, payload, chunk_size=32 * 1024)

    raw = target.read_bytes()
    assert json.loads(raw) == payload
    assert receipt.size_bytes == len(raw)
    assert receipt.content_hash == hashlib.sha256(raw).hexdigest()
    assert receipt.max_write_bytes <= 32 * 1024
    assert not list(tmp_path.glob(".*.tmp"))


def test_json_mapping_artifact_consumes_strategy_payloads_incrementally(tmp_path):
    target = tmp_path / "audit.json"
    emitted = []

    def strategies():
        for index in range(3):
            emitted.append(index)
            yield f"A{index}", {"orders": list(range(index + 1))}

    receipt = write_json_mapping_artifact(
        target,
        fields={"run_id": "run-1"},
        mapping_name="strategies",
        items=strategies(),
        chunk_size=1024,
    )

    assert json.loads(target.read_bytes()) == {
        "run_id": "run-1",
        "strategies": {
            "A0": {"orders": [0]},
            "A1": {"orders": [0, 1]},
            "A2": {"orders": [0, 1, 2]},
        },
    }
    assert emitted == [0, 1, 2]
    assert receipt.max_write_bytes <= 1024


def test_json_artifact_streams_nested_token_sources(tmp_path):
    target = tmp_path / "nested.json"

    class TokenRows:
        def iter_json_tokens(self):
            yield "["
            yield '{"step":"first"}'
            yield ","
            yield '{"step":"second"}'
            yield "]"

    write_json_artifact(target, {"execution_trace": TokenRows()}, chunk_size=1024)

    assert json.loads(target.read_bytes()) == {
        "execution_trace": [
            {"step": "first"},
            {"step": "second"},
        ],
    }
