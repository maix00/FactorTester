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
        _require_sidecars(paths, pending)
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
        _restore_sidecars(paths, pending)
        _require_sidecars(paths, pending)
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
    legacy_required = {
        "schema_version", "submission_sequence", "base_generation",
        "logical_identity", "logical_digest", "attempt",
        "last_payload_hash", "diagnostics", "phase",
        "published_generation", "published_root_ref",
    }
    if set(value) == legacy_required and value.get("schema_version") == 2:
        value = {**value, "schema_version": 4, "sidecars": []}
    required = legacy_required | {"sidecars"}
    if set(value) != required or value.get("schema_version") != 4:
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
    _validate_sidecars(value["sidecars"])
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


def _validate_sidecars(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("submission sidecars must be an array")
    paths: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path", "base_generation", "next_generation", "next_hash",
            "next_value",
        }:
            raise ValueError("submission sidecar fields are invalid")
        path = item["path"]
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or path in paths
        ):
            raise ValueError("submission sidecar path is invalid")
        paths.add(path)
        base = item["base_generation"]
        next_generation = item["next_generation"]
        if (
            not isinstance(base, int)
            or base < 0
            or next_generation != base + 1
            or not _is_digest(item["next_hash"])
        ):
            raise ValueError("submission sidecar generation/hash is invalid")
        next_value = item["next_value"]
        if (
            not isinstance(next_value, dict)
            or next_value.get("generation") != next_generation
            or digest(next_value) != item["next_hash"]
        ):
            raise ValueError("submission sidecar recovery value is invalid")
    return value


def _restore_sidecars(
    paths: dict[str, Path],
    pending: dict[str, Any],
) -> None:
    branch_root = paths["root"].parent
    for sidecar in pending["sidecars"]:
        path = branch_root / sidecar["path"]
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"pending submission sidecar is unreadable: {sidecar['path']}"
                ) from exc
            if (
                isinstance(current, dict)
                and current.get("generation") == sidecar["next_generation"]
                and digest(current) == sidecar["next_hash"]
            ):
                continue
            if (
                not isinstance(current, dict)
                or current.get("generation") != sidecar["base_generation"]
            ):
                raise ValueError(
                    f"pending submission sidecar conflicts: {sidecar['path']}"
                )
        atomic_write(
            path,
            json.dumps(
                sidecar["next_value"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode() + b"\n",
        )


def _require_sidecars(
    paths: dict[str, Path],
    pending: dict[str, Any],
) -> None:
    branch_root = paths["root"].parent
    for sidecar in pending["sidecars"]:
        path = branch_root / sidecar["path"]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"pending submission sidecar is unavailable: {sidecar['path']}"
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("generation") != sidecar["next_generation"]
            or digest(value) != sidecar["next_hash"]
        ):
            raise ValueError(
                f"pending submission sidecar does not match: {sidecar['path']}"
            )
