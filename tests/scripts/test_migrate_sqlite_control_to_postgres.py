from __future__ import annotations

import json
import sqlite3

from scripts.migrate_sqlite_control_to_postgres import (
    backup_sqlite,
    load_profile_metadata,
    load_sqlite_control_snapshot,
    migrate,
    profile_metadata,
)


def _make_source(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE accounts (
            username TEXT PRIMARY KEY, alias TEXT, salt TEXT, hash TEXT,
            role TEXT, is_admin INTEGER, is_developer INTEGER,
            organization_id TEXT, organization_name TEXT, level_id TEXT,
            parent_username TEXT, updated_at REAL
        );
        CREATE TABLE organizations (id TEXT PRIMARY KEY, name TEXT, description TEXT, updated_at REAL);
        CREATE TABLE levels (
            id TEXT PRIMARY KEY, organization_id TEXT, name TEXT,
            parent_level_id TEXT, manager_username TEXT, updated_at REAL
        );
        CREATE TABLE user_storage_policies (owner TEXT PRIMARY KEY, quota_bytes INTEGER, updated_at REAL);
        CREATE TABLE factor_family_sources (
            source_kind TEXT, owner_username TEXT, factor_id TEXT,
            factor_name TEXT, source_code TEXT, updated_at REAL,
            PRIMARY KEY (source_kind, owner_username, factor_id)
        );
        INSERT INTO accounts VALUES ('org$alice@1', 'Alice', 'salt', 'hash', 'user', 0, 0, 'org', 'Org', 'root', '', 1);
        INSERT INTO organizations VALUES ('org', 'Org', 'desc', 1);
        INSERT INTO levels VALUES ('root', 'org', 'Root', '', 'org$alice@1', 1);
        INSERT INTO user_storage_policies VALUES ('org$alice@1', 4096, 1);
        INSERT INTO factor_family_sources VALUES ('custom', 'org$alice@1', 'alpha', 'Alpha', 'SECRET SOURCE', 1);
        """
    )
    connection.commit()
    connection.close()


def test_sqlite_snapshot_reads_control_rows_without_source_body() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "unified.sqlite"
        _make_source(source)
        value = load_sqlite_control_snapshot(source)

    assert len(value["accounts"]) == 1
    assert len(value["organizations"]) == 1
    assert len(value["levels"]) == 1
    assert value["quotas"][0]["quota_bytes"] == 4096
    assert value["source_rows"][0]["factor_id"] == "alpha"
    assert "source_code" not in value["source_rows"][0]


def test_profile_metadata_removes_local_paths_and_secrets() -> None:
    value = profile_metadata({
        "profile_id": "research",
        "display_name": "Research",
        "session_binding": {"principal_ref": "alice", "session_ref": "secret-ref"},
        "workspace_root": "/Users/alice/private",
        "factor_workspace_binding": {
            "canonical_repo_ref": "repo",
            "worktree_path": "/private/worktree",
        },
        "server": {"base_url": "http://server:7998"},
    })

    assert value is not None
    assert value["principal"] == "alice"
    payload = value["payload"]
    assert "server" not in payload
    assert "workspace_root" not in payload
    assert "worktree_path" not in json.dumps(payload)
    assert "session_ref" not in payload["session_binding"]


def test_profile_loader_reads_only_bound_json_profiles(tmp_path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "research.json").write_text(json.dumps({
        "profile_id": "research",
        "display_name": "Research",
        "session_binding": {"principal_ref": "alice"},
    }), encoding="utf-8")
    (profiles / "unbound.json").write_text(json.dumps({
        "profile_id": "unbound",
        "display_name": "Unbound",
    }), encoding="utf-8")

    result = load_profile_metadata(tmp_path)

    assert [item["profile_id"] for item in result] == ["research"]


def test_sqlite_backup_uses_a_separate_consistent_file(tmp_path) -> None:
    source = tmp_path / "source.sqlite"
    backup = tmp_path / "backup.sqlite"
    _make_source(source)

    created = backup_sqlite(source, backup)

    assert created == backup.resolve()
    connection = sqlite3.connect(backup)
    assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    connection.close()


def test_dry_run_never_requires_postgres_or_writes_backup(tmp_path) -> None:
    source = tmp_path / "source.sqlite"
    _make_source(source)

    result = migrate(
        source_db=source,
        client_root=None,
        database_url="",
        apply=False,
        backup_path=None,
        no_backup=False,
    )

    assert result["mode"] == "dry-run"
    assert result["snapshot"]["accounts"] == 1
    assert result["backup"] is None
