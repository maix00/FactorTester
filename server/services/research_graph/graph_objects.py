"""Immutable, scope-bound objects referenced by Research Graph facts."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import time
from typing import Any, Iterable, Mapping

import orjson


GRAPH_OBJECT_REF_PREFIX = "research-graph-object:sha256:"
MAX_GRAPH_OBJECT_BYTES = 32 * 1024
_REF_RE = re.compile(
    rf"{re.escape(GRAPH_OBJECT_REF_PREFIX)}(?P<hash>[0-9a-f]{{64}})"
)


def create_graph_object_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS research_graph_objects (
            object_hash TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            object_kind TEXT NOT NULL,
            object_json TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )


def prepare_graph_object(
    owner: str,
    instance_id: str,
    object_kind: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    """Canonicalize and hash one object without touching the database."""
    owner = _required_text(owner, "owner")
    instance_id = _required_text(instance_id, "instance_id")
    object_kind = _required_text(object_kind, "object_kind")
    if not isinstance(body, Mapping):
        raise TypeError("graph object body must be an object")
    body_value = dict(body)
    object_bytes = _canonical_bytes(body_value)
    if len(object_bytes) > MAX_GRAPH_OBJECT_BYTES:
        raise ValueError("graph object exceeds 32 KiB")
    object_hash = _object_hash(
        owner=owner,
        instance_id=instance_id,
        object_kind=object_kind,
        body=body_value,
    )
    return {
        "object_ref": GRAPH_OBJECT_REF_PREFIX + object_hash,
        "object_hash": object_hash,
        "owner": owner,
        "instance_id": instance_id,
        "object_kind": object_kind,
        "object_json": object_bytes.decode(),
        "byte_size": len(object_bytes),
        "created_at": time.time(),
    }


def insert_graph_objects(
    conn: sqlite3.Connection,
    objects: Iterable[Mapping[str, Any]],
) -> None:
    """Insert prepared values in the caller's transaction without reads."""
    rows = [_validate_prepared_object(value) for value in objects]
    if rows:
        conn.executemany(
            """
            INSERT OR IGNORE INTO research_graph_objects (
                object_hash, owner, instance_id, object_kind,
                object_json, byte_size, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def load_graph_objects(
    conn: sqlite3.Connection,
    owner: str,
    instance_id: str,
    refs: Iterable[str],
    expected_kinds: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load and verify an exact batch of references with one SELECT."""
    owner = _required_text(owner, "owner")
    instance_id = _required_text(instance_id, "instance_id")
    ref_hashes = {_validate_ref(ref): ref for ref in refs}
    if not ref_hashes:
        return {}
    placeholders = ", ".join("?" for _ in ref_hashes)
    rows = conn.execute(
        f"""
        SELECT object_hash, owner, instance_id, object_kind,
               object_json, byte_size
        FROM research_graph_objects
        WHERE owner=? AND instance_id=?
          AND object_hash IN ({placeholders})
        """,
        (owner, instance_id, *ref_hashes),
    ).fetchall()
    loaded: dict[str, dict[str, Any]] = {}
    for row in rows:
        object_hash = str(row["object_hash"])
        object_json = str(row["object_json"])
        encoded = object_json.encode()
        if len(encoded) > MAX_GRAPH_OBJECT_BYTES:
            raise ValueError("stored research graph object exceeds 32 KiB")
        try:
            body = orjson.loads(encoded)
        except orjson.JSONDecodeError as exc:
            raise ValueError(
                "stored research graph object is invalid JSON"
            ) from exc
        if not isinstance(body, dict) or _canonical_bytes(body) != encoded:
            raise ValueError(
                "stored research graph object is not canonical JSON"
            )
        if row["byte_size"] != len(encoded):
            raise ValueError("research graph object byte_size mismatch")
        expected_hash = _object_hash(
            owner=str(row["owner"]),
            instance_id=str(row["instance_id"]),
            object_kind=str(row["object_kind"]),
            body=body,
        )
        if expected_hash != object_hash:
            raise ValueError("research graph object hash mismatch")
        ref = GRAPH_OBJECT_REF_PREFIX + object_hash
        if expected_kinds is not None:
            expected_kind = expected_kinds.get(ref)
            if expected_kind is None or expected_kind != row["object_kind"]:
                raise ValueError("research graph object kind mismatch")
        loaded[ref] = body
    missing = set(ref_hashes.values()) - set(loaded)
    if missing:
        raise KeyError("research graph object not found")
    return loaded


def _object_hash(
    *,
    owner: str,
    instance_id: str,
    object_kind: str,
    body: Mapping[str, Any],
) -> str:
    envelope = {
        "body": body,
        "instance_id": instance_id,
        "object_kind": object_kind,
        "owner": owner,
        "schema_version": 1,
    }
    return hashlib.sha256(_canonical_bytes(envelope)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    try:
        return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    except (TypeError, orjson.JSONEncodeError) as exc:
        raise ValueError("graph object must be canonical JSON") from exc


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _validate_ref(ref: Any) -> str:
    if not isinstance(ref, str):
        raise ValueError("research graph object ref is invalid")
    match = _REF_RE.fullmatch(ref)
    if match is None:
        raise ValueError("research graph object ref is invalid")
    return match.group("hash")


def _validate_prepared_object(
    value: Mapping[str, Any],
) -> tuple[str, str, str, str, str, int, float]:
    if not isinstance(value, Mapping):
        raise TypeError("prepared graph object must be an object")
    owner = _required_text(value.get("owner"), "owner")
    instance_id = _required_text(value.get("instance_id"), "instance_id")
    object_kind = _required_text(value.get("object_kind"), "object_kind")
    object_hash = _validate_ref(value.get("object_ref"))
    if value.get("object_hash") != object_hash:
        raise ValueError("research graph object hash mismatch")
    object_json = value.get("object_json")
    if not isinstance(object_json, str):
        raise ValueError("graph object_json must be canonical JSON")
    try:
        body = orjson.loads(object_json)
    except orjson.JSONDecodeError as exc:
        raise ValueError("graph object_json must be canonical JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("graph object body must be an object")
    canonical = _canonical_bytes(body)
    if object_json.encode() != canonical:
        raise ValueError("graph object_json must be canonical JSON")
    byte_size = value.get("byte_size")
    if (
        not isinstance(byte_size, int)
        or isinstance(byte_size, bool)
        or byte_size != len(canonical)
    ):
        raise ValueError("research graph object byte_size mismatch")
    if byte_size > MAX_GRAPH_OBJECT_BYTES:
        raise ValueError("graph object exceeds 32 KiB")
    if _object_hash(
        owner=owner,
        instance_id=instance_id,
        object_kind=object_kind,
        body=body,
    ) != object_hash:
        raise ValueError("research graph object hash mismatch")
    created_at = value.get("created_at")
    if (
        not isinstance(created_at, (int, float))
        or isinstance(created_at, bool)
        or not math.isfinite(created_at)
    ):
        raise ValueError("created_at must be finite")
    return (
        object_hash,
        owner,
        instance_id,
        object_kind,
        object_json,
        byte_size,
        float(created_at),
    )
