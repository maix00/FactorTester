"""Immutable SQLite snapshots for factor-family source revisions."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from typing import Any

import settings as Settings

from .db import connect_sqlite
from .factor_source_store import normalize_factor_source_code

TABLE_NAME = "factor_family_source_versions"


def _owner(source_kind: str, owner_username: str) -> str:
    return "" if str(source_kind or "").strip() == "public" else str(
        owner_username or "",
    ).strip()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            source_code TEXT NOT NULL,
            relative_path TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (source_kind, owner_username, factor_id, commit_sha)
        )
        """,
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_factor
        ON {TABLE_NAME}(source_kind, owner_username, factor_id, created_at DESC)
        """,
    )


def ensure_factor_source_versions_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def record_factor_source_version(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    commit_sha: str,
    source_code: str,
    *,
    relative_path: str = "",
    subject: str = "",
) -> dict[str, Any]:
    commit = str(commit_sha or "").strip()
    if not commit:
        raise ValueError("源码版本必须包含 Git commit")
    normalized = normalize_factor_source_code(source_code or "")
    if not normalized:
        raise ValueError("源码版本不能为空")
    kind = str(source_kind or "").strip()
    owner = _owner(kind, owner_username)
    factor = str(factor_id or "").strip()
    if kind not in {"custom", "public"} or not factor:
        raise ValueError("源码版本身份无效")
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            f"""
            INSERT INTO {TABLE_NAME} (
                source_kind, owner_username, factor_id, commit_sha,
                source_hash, source_code, relative_path, subject, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, owner_username, factor_id, commit_sha)
            DO UPDATE SET
                source_hash = excluded.source_hash,
                source_code = excluded.source_code,
                relative_path = excluded.relative_path,
                subject = excluded.subject
            """,
            (
                kind, owner, factor, commit, source_hash, normalized,
                relative_path, subject, now,
            ),
        )
    return {
        "source_kind": kind,
        "owner_username": owner,
        "factor_id": factor,
        "commit": commit,
        "source_hash": source_hash,
        "source_code": normalized,
        "relative_path": relative_path,
        "subject": subject,
        "created_at": now,
    }


def _matches_commit(requested: str, stored: str) -> bool:
    left = str(requested or "").strip().lower()
    right = str(stored or "").strip().lower()
    return bool(left and right and (left == right or left.startswith(right) or right.startswith(left)))


def load_factor_source_version_snapshot(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    commit_sha: str,
) -> dict[str, Any] | None:
    kind = str(source_kind or "").strip()
    owner = _owner(kind, owner_username)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT source_kind, owner_username, factor_id, commit_sha,
                   source_hash, source_code, relative_path, subject, created_at
            FROM {TABLE_NAME}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            ORDER BY created_at DESC
            """,
            (kind, owner, str(factor_id or "").strip()),
        ).fetchall()
    row = next((item for item in rows if _matches_commit(commit_sha, item["commit_sha"])), None)
    if row is None:
        return None
    return {
        "source_kind": row["source_kind"],
        "owner_username": row["owner_username"],
        "factor_id": row["factor_id"],
        "commit": row["commit_sha"],
        "source_hash": row["source_hash"],
        "source_code": normalize_factor_source_code(str(row["source_code"] or "")),
        "relative_path": row["relative_path"] or "",
        "subject": row["subject"] or "",
        "created_at": float(row["created_at"] or 0.0),
        "branches": [],
    }


def list_factor_source_version_snapshots(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    *,
    current_hash: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    kind = str(source_kind or "").strip()
    owner = _owner(kind, owner_username)
    bounded = min(200, max(1, int(limit)))
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT source_kind, owner_username, factor_id, commit_sha,
                   source_hash, relative_path, subject, created_at
            FROM {TABLE_NAME}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (kind, owner, str(factor_id or "").strip(), bounded),
        ).fetchall()
    result: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for row in rows:
        source_hash = str(row["source_hash"] or "")
        if not source_hash or source_hash in seen_hashes:
            continue
        seen_hashes.add(source_hash)
        result.append({
            "commit": row["commit_sha"],
            "short_commit": str(row["commit_sha"] or "")[:12],
            "committed_at": int(float(row["created_at"] or 0.0)),
            "author": "",
            "subject": row["subject"] or "源码快照",
            "branches": [],
            "relative_path": row["relative_path"] or "",
            "source_hash": source_hash,
            "is_current": bool(current_hash and source_hash == current_hash),
            "workspace": "server-db",
        })
    return result


__all__ = [
    "ensure_factor_source_versions_sqlite_store",
    "list_factor_source_version_snapshots",
    "load_factor_source_version_snapshot",
    "record_factor_source_version",
]
