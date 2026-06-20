from __future__ import annotations

import json
import sqlite3

import settings as Settings
from tools.data.sqlite.account_manager import user_template


def test_legacy_collection_is_migrated_to_template_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "templates.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    payload = [
        {"id": "a", "name": "A", "snapshot": {"large": [1, 2, 3]}},
        {"id": "b", "name": "B", "snapshot": {"large": [4, 5, 6]}},
    ]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE account_template_collections (
                username TEXT, kind TEXT, scope_key TEXT, ff_alias TEXT,
                payload_json TEXT, updated_at REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO account_template_collections VALUES (?, ?, ?, ?, ?, ?)",
            ("alice", "global", "MmRet", "", json.dumps(payload), 123.0),
        )

    assert user_template.load_user_templates("alice", "global", scope_key="MmRet") == payload

    with sqlite3.connect(db_path) as conn:
        old_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_template_collections'"
        ).fetchone()
        rows = conn.execute(
            "SELECT template_id, sort_order FROM account_templates ORDER BY sort_order"
        ).fetchall()
    assert old_table is None
    assert rows == [("a", 0), ("b", 1)]


def test_metadata_query_does_not_select_payload_json(monkeypatch, tmp_path):
    db_path = tmp_path / "templates.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", db_path)
    user_template.save_user_templates(
        "alice",
        "global",
        [{"id": "a", "name": "A", "ff_alias": "MmRet", "snapshot": {"large": list(range(1000))}}],
        scope_key="MmRet",
    )

    statements = []
    original_connect = user_template.connect_sqlite

    def traced_connect(path):
        conn = original_connect(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(user_template, "connect_sqlite", traced_connect)
    result = user_template.list_user_template_metadata("alice", "global", scope_key="MmRet")

    assert result[0]["id"] == "a"
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert selects
    assert all("payload_json" not in sql.lower() for sql in selects)


def test_single_template_load_is_scoped_by_user_and_family(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "templates.sqlite")
    user_template.save_user_templates(
        "alice", "global", [{"id": "same", "name": "Alice"}], scope_key="MmRet"
    )
    user_template.save_user_templates(
        "bob", "global", [{"id": "same", "name": "Bob"}], scope_key="MmRet"
    )
    user_template.save_user_templates(
        "alice", "global", [{"id": "same", "name": "Other"}], scope_key="VlATR"
    )

    assert user_template.load_user_template("alice", "global", "same", scope_key="MmRet")["name"] == "Alice"
    assert user_template.load_user_template("bob", "global", "same", scope_key="MmRet")["name"] == "Bob"
    assert user_template.load_user_template("alice", "global", "same", scope_key="VlATR")["name"] == "Other"
