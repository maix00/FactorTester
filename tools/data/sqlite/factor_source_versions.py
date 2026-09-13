"""Immutable formula versions for factor families.

Formula identity is semantic and deliberately independent of Git.  The
source snapshot is retained so a frozen formula can be inspected and
executed even when no workspace exists on the server.
"""

from __future__ import annotations

import hashlib
from contextlib import nullcontext
import json
import os
import re
import sqlite3
import time
from typing import Any

import settings as Settings

from .db import connect_sqlite
from .factor_source_store import canonical_factor_source_code

TABLE_NAME = "factor_family_formula_versions"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _owner(source_kind: str, owner_username: str) -> str:
    return "" if str(source_kind or "").strip() == "public" else str(
        owner_username or ""
    ).strip()


def _identity(
    source_kind: str,
    owner_username: str,
    factor_id: str,
) -> tuple[str, str, str]:
    kind = str(source_kind or "").strip()
    owner = _owner(kind, owner_username)
    factor = str(factor_id or "").strip()
    if kind not in {"custom", "public"} or not factor:
        raise ValueError("公式版本身份无效")
    return kind, owner, factor


def _fingerprint(value: str) -> str:
    fingerprint = str(value or "").strip().lower()
    if not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("family formula fingerprint must be 64 hexadecimal characters")
    return fingerprint


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            source_kind TEXT NOT NULL,
            owner_username TEXT NOT NULL DEFAULT '',
            factor_id TEXT NOT NULL,
            family_formula_fingerprint TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_code TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (
                source_kind, owner_username, factor_id,
                family_formula_fingerprint
            )
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_factor
        ON {TABLE_NAME}(
            source_kind, owner_username, factor_id, created_at DESC
        )
        """
    )


def ensure_factor_formula_versions_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def record_factor_formula_version(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    source_code: str,
    *,
    family_formula_fingerprint: str,
    subject: str = "",
    connection=None, mirror=None,
) -> dict[str, Any]:
    kind, owner, factor = _identity(source_kind, owner_username, factor_id)
    fingerprint = _fingerprint(family_formula_fingerprint)
    normalized = canonical_factor_source_code(source_code or "")
    if not normalized:
        raise ValueError("源码版本不能为空")
    source_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    created_at = time.time()
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    mirror = mirror or LocalAccountDomainStore(Settings.CACHE_DB_PATH)
    with (nullcontext(connection) if connection is not None else connect_sqlite(Settings.CACHE_DB_PATH)) as conn:
        _ensure_schema(conn)
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {TABLE_NAME} (
                source_kind, owner_username, factor_id,
                family_formula_fingerprint, source_sha256, source_code,
                subject, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                owner,
                factor,
                fingerprint,
                source_sha256,
                normalized,
                str(subject or ""),
                created_at,
            ),
        )
        row = conn.execute(
            f"""
            SELECT source_sha256, source_code, subject, created_at
            FROM {TABLE_NAME}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
              AND family_formula_fingerprint = ?
            """,
            (kind, owner, factor, fingerprint),
        ).fetchone()
        assert row is not None
        provider = os.environ.get("FACTORTESTER_SERVER_ID") or "local"
        mirror.upsert_local(
            principal=owner or "__public__", entity_type="factor_source_version",
            entity_id=f"{kind}:{factor}:{fingerprint}@{provider}",
            payload={"source_kind": kind, "owner_username": owner, "factor_id": factor,
                     "factor_name": factor, "family_formula_fingerprint": fingerprint,
                     "source_sha256": str(row["source_sha256"]),
                     "source_bytes": len(str(row["source_code"]).encode("utf-8")),
                     "created_at": float(row["created_at"]), "subject": str(row["subject"] or ""),
                     "storage_server_id": provider,
                     "visibility": "public" if kind == "public" else "private"},
            manager_id=provider, connection=conn,
        )
    assert row is not None
    return {
        "source_kind": kind,
        "owner_username": owner,
        "factor_id": factor,
        "family_formula_fingerprint": fingerprint,
        "source_sha256": str(row["source_sha256"]),
        "source_code": str(row["source_code"]),
        "subject": str(row["subject"] or ""),
        "created_at": float(row["created_at"]),
    }


def load_factor_formula_version(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    family_formula_fingerprint: str,
) -> dict[str, Any] | None:
    kind, owner, factor = _identity(source_kind, owner_username, factor_id)
    fingerprint = _fingerprint(family_formula_fingerprint)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            f"""
            SELECT source_sha256, source_code, subject, created_at
            FROM {TABLE_NAME}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
              AND family_formula_fingerprint = ?
            """,
            (kind, owner, factor, fingerprint),
        ).fetchone()
    if row is None:
        return None
    return {
        "source_kind": kind,
        "owner_username": owner,
        "factor_id": factor,
        "family_formula_fingerprint": fingerprint,
        "source_sha256": str(row["source_sha256"]),
        "source_code": str(row["source_code"]),
        "subject": str(row["subject"] or ""),
        "created_at": float(row["created_at"]),
    }


def list_factor_formula_versions(
    source_kind: str,
    owner_username: str,
    factor_id: str,
    *,
    current_fingerprint: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    kind, owner, factor = _identity(source_kind, owner_username, factor_id)
    current = (
        _fingerprint(current_fingerprint) if str(current_fingerprint or "").strip() else ""
    )
    bounded = min(200, max(1, int(limit)))
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT family_formula_fingerprint, source_sha256, subject, created_at
            FROM {TABLE_NAME}
            WHERE source_kind = ? AND owner_username = ? AND factor_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (kind, owner, factor, bounded),
        ).fetchall()
        remote = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_domain_entities'").fetchone():
            remote = conn.execute(
                "SELECT payload_json FROM account_domain_entities "
                "WHERE principal=? AND entity_type='factor_source_version' AND deleted=0 "
                "AND json_extract(payload_json,'$.factor_id')=? AND json_extract(payload_json,'$.source_kind')=? "
                "GROUP BY json_extract(payload_json,'$.family_formula_fingerprint') "
                "ORDER BY json_extract(payload_json,'$.created_at') DESC LIMIT ?",
                (owner or '__public__', factor, kind, bounded),
            ).fetchall()
    values = [
        {
            "family_formula_fingerprint": str(row["family_formula_fingerprint"]),
            "source_sha256": str(row["source_sha256"]),
            "subject": str(row["subject"] or ""),
            "created_at": float(row["created_at"]),
            "is_current": bool(
                current
                and current == str(row["family_formula_fingerprint"])
            ),
        }
        for row in rows
    ]
    by_fingerprint = {value['family_formula_fingerprint']: value for value in values}
    for row in remote:
        manifest = json.loads(row['payload_json'])
        fingerprint = manifest.get('family_formula_fingerprint')
        if fingerprint and fingerprint not in by_fingerprint:
            by_fingerprint[fingerprint] = {
                'family_formula_fingerprint': fingerprint,
                'source_sha256': manifest.get('source_sha256', ''),
                'subject': manifest.get('subject', ''), 'created_at': manifest.get('created_at', 0),
                'is_current': bool(current and current == fingerprint),
            }
    return sorted(by_fingerprint.values(), key=lambda value: value['created_at'], reverse=True)[:bounded]


__all__ = [
    "ensure_factor_formula_versions_sqlite_store",
    "list_factor_formula_versions",
    "load_factor_formula_version",
    "record_factor_formula_version",
]
