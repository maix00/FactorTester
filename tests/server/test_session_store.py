"""Manager-local SQLite session lifecycle tests."""

from __future__ import annotations

import sqlite3
import hashlib

from server.manager.storage.session_store import ManagerSessionStore


def _session(
    *,
    expires_at: float,
    created_at: float = 100.0,
    last_seen_at: float = 100.0,
) -> tuple[object, ...]:
    return (
        "GTHT@MaxJJW@1",
        "user",
        expires_at,
        "device",
        "https://101.133.144.27:7998",
        "MaxJJW",
        created_at,
        last_seen_at,
    )


def test_session_store_persists_metadata_without_raw_token(tmp_path) -> None:
    path = tmp_path / "state" / "sessions.sqlite"
    store = ManagerSessionStore(path)
    raw_token = "raw-session-token"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    store.upsert(token_hash, _session(expires_at=500.0), now=100.0)

    restarted = ManagerSessionStore(path)
    loaded = restarted.load(now=200.0, idle_ttl=1000.0)

    assert loaded[token_hash][:6] == _session(expires_at=500.0)[:6]
    assert loaded[token_hash][6:] == (100.0, 100.0)
    assert path.stat().st_mode & 0o777 == 0o600
    assert b"GTHT@MaxJJW@1" in path.read_bytes()
    assert raw_token.encode() not in path.read_bytes()


def test_session_store_cleanup_removes_expired_and_long_idle_rows(tmp_path) -> None:
    store = ManagerSessionStore(tmp_path / "sessions.sqlite")
    store.upsert("e" * 64, _session(expires_at=99.0), now=100.0)
    store.upsert(
        "i" * 64,
        _session(expires_at=10_000.0, last_seen_at=1.0),
        now=100.0,
    )
    store.upsert(
        "a" * 64,
        _session(expires_at=10_000.0, last_seen_at=950.0),
        now=100.0,
    )

    removed = store.cleanup(now=1_000.0, idle_ttl=100.0)

    assert removed == 2
    assert set(store.load(now=1_000.0)) == {"a" * 64}


def test_session_store_schema_has_lifecycle_indexes(tmp_path) -> None:
    path = tmp_path / "sessions.sqlite"
    ManagerSessionStore(path)

    with sqlite3.connect(path) as database:
        indexes = {
            row[1]
            for row in database.execute(
                "PRAGMA index_list(manager_sessions)"
            ).fetchall()
        }

    assert "manager_sessions_expiry" in indexes
    assert "manager_sessions_idle" in indexes
    assert "manager_sessions_principal" in indexes
