"""Durable SQLite idempotency receipts for finalized report submissions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .submission_lease import ReportSubmission


def load_matching_receipt(
    paths: dict[str, Path], *, sequence: int,
    logical_digest: str, payload_hash: str,
) -> dict[str, Any] | None:
    """Find one receipt by its complete idempotency identity."""
    _validate_identity(sequence, logical_digest)
    path = paths["submission_db"]
    if not path.is_file():
        return None
    try:
        with _connect(path) as db:
            _create_schema(db)
            row = db.execute(
                "SELECT payload_hash,value_json FROM receipt "
                "WHERE submission_sequence=? AND logical_digest=?",
                (sequence, logical_digest),
            ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("report submission receipt store is invalid") from exc
    if row is None or str(row[0]) != payload_hash:
        return None
    return _validate_receipt(json.loads(str(row[1])), sequence)


def write_receipt(
    paths: dict[str, Path], *, submission: ReportSubmission,
    head: dict[str, Any], finalize_result: dict[str, Any],
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "submission_sequence": submission.sequence,
        "logical_digest": submission.logical_digest,
        "payload_hash": submission.payload_hash,
        "attempt": submission.attempt,
        "published_generation": head["generation"],
        "published_root_ref": head["root_ref"],
        "finalize_result": finalize_result,
    }
    value = _validate_receipt(value, submission.sequence)
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    path = paths["submission_db"]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _connect(path) as db:
            _create_schema(db)
            existing = db.execute(
                "SELECT value_json FROM receipt WHERE submission_sequence=? "
                "AND logical_digest=?",
                (submission.sequence, submission.logical_digest),
            ).fetchone()
            if existing is not None:
                current = _validate_receipt(
                    json.loads(str(existing[0])), submission.sequence,
                )
                if current != value:
                    raise ValueError(
                        "report submission receipt conflicts with finalized state"
                    )
                return current
            db.execute(
                "INSERT INTO receipt(submission_sequence,logical_digest,"
                "payload_hash,value_json) VALUES(?,?,?,?)",
                (
                    submission.sequence, submission.logical_digest,
                    submission.payload_hash, payload,
                ),
            )
            db.commit()
    except sqlite3.DatabaseError as exc:
        raise ValueError("report submission receipt store is invalid") from exc
    return value


def receipt_count(paths: dict[str, Path], *, sequence: int | None = None) -> int:
    """Return a compact diagnostic count without exposing storage details."""
    path = paths["submission_db"]
    if not path.is_file():
        return 0
    with _connect(path) as db:
        _create_schema(db)
        if sequence is None:
            row = db.execute("SELECT count(*) FROM receipt").fetchone()
        else:
            row = db.execute(
                "SELECT count(*) FROM receipt WHERE submission_sequence=?",
                (sequence,),
            ).fetchone()
    return int(row[0])


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("PRAGMA synchronous=FULL")
    return db


def _create_schema(db: sqlite3.Connection) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS receipt("
        "submission_sequence INTEGER NOT NULL,"
        "logical_digest TEXT NOT NULL,"
        "payload_hash TEXT NOT NULL,"
        "value_json TEXT NOT NULL,"
        "PRIMARY KEY(submission_sequence,logical_digest)"
        ") WITHOUT ROWID"
    )


def _validate_identity(sequence: int, logical_digest: str) -> None:
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError("report submission receipt sequence is invalid")
    if (
        len(logical_digest) != 64
        or any(character not in "0123456789abcdef" for character in logical_digest)
    ):
        raise ValueError("report submission receipt digest is invalid")


def _validate_receipt(value: Any, sequence: int) -> dict[str, Any]:
    required = {
        "schema_version", "submission_sequence", "logical_digest",
        "payload_hash", "attempt", "published_generation",
        "published_root_ref", "finalize_result",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("report submission receipt schema is invalid")
    _validate_identity(sequence, value.get("logical_digest"))
    if (
        value.get("schema_version") != 1
        or value["submission_sequence"] != sequence
        or value["published_generation"] != sequence
        or not isinstance(value["attempt"], int)
        or value["attempt"] < 1
        or not isinstance(value["payload_hash"], str)
        or not value["payload_hash"]
        or not isinstance(value["published_root_ref"], str)
        or not value["published_root_ref"]
        or not isinstance(value["finalize_result"], dict)
    ):
        raise ValueError("report submission receipt is invalid")
    return value
