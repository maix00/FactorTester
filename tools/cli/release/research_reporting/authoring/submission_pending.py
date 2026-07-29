"""Persistence primitives for one branch's pending report submission."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .tree_store import atomic_write, load_json


def reconcile_pending(
    paths: dict[str, Path],
    head: dict[str, Any],
) -> dict[str, Any] | None:
    pending = load_pending(paths)
    if pending is None:
        return None
    sequence = pending["submission_sequence"]
    if pending["phase"] == "published":
        if (
            head["generation"] != sequence
            or head["root_ref"] != pending["published_root_ref"]
        ):
            raise ValueError(
                "published report submission no longer matches HEAD"
            )
        return pending
    if head["generation"] == pending["base_generation"]:
        return pending
    if head["generation"] == sequence:
        value = {
            **pending,
            "phase": "published",
            "published_generation": sequence,
            "published_root_ref": head["root_ref"],
            "diagnostics": [],
        }
        write_pending(paths, value)
        return value
    raise ValueError(
        "pending report submission base generation no longer matches HEAD"
    )


def load_pending(paths: dict[str, Path]) -> dict[str, Any] | None:
    path = paths["pending_submission"]
    if not path.exists():
        return None
    value = load_json(path, label="报告待修正提交")
    required = {
        "schema_version", "submission_sequence", "base_generation",
        "logical_identity", "logical_digest", "attempt",
        "last_payload_hash", "diagnostics", "phase",
        "published_generation", "published_root_ref",
    }
    if set(value) != required or value.get("schema_version") != 2:
        raise ValueError("pending report submission schema is invalid")
    sequence, base = value["submission_sequence"], value["base_generation"]
    phase = value["phase"]
    if (
        not isinstance(sequence, int)
        or not isinstance(base, int)
        or sequence != base + 1
        or not isinstance(value["attempt"], int)
        or value["attempt"] < 1
        or phase not in {"reserved", "rejected", "published"}
    ):
        raise ValueError("pending report submission sequence is invalid")
    identity = normalized_object(value["logical_identity"], "logical_identity")
    if value["logical_digest"] != digest(identity):
        raise ValueError("pending report submission identity is invalid")
    if not _is_digest(value["last_payload_hash"]):
        raise ValueError("pending report submission payload hash is invalid")
    if phase == "published":
        if (
            value["published_generation"] != sequence
            or not isinstance(value["published_root_ref"], str)
            or not value["published_root_ref"]
        ):
            raise ValueError("published report submission state is invalid")
    elif (
        value["published_generation"] is not None
        or value["published_root_ref"] != ""
    ):
        raise ValueError(
            "unpublished report submission state is invalid"
        )
    normalized_diagnostics(value["diagnostics"])
    return value


def write_pending(paths: dict[str, Path], value: dict[str, Any]) -> None:
    atomic_write(
        paths["pending_submission"],
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n",
    )


def remove_pending(paths: dict[str, Path]) -> None:
    path = paths["pending_submission"]
    if not path.exists():
        return
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def normalized_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def normalized_diagnostics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("submission diagnostics must be an array of objects")
    json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
