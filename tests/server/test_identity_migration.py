"""One-time account identity migration behavior."""

from __future__ import annotations

import json
import sqlite3

from server.manager.storage.identity_migration import (
    apply_sqlite_identity_migration,
    backup_sqlite,
    migrate_local_device_json,
    migrate_local_session_json,
    apply_user_root_identity_migration,
    sqlite_identity_plan,
)


def _database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE accounts(
                username TEXT PRIMARY KEY, alias TEXT, salt TEXT, hash TEXT,
                role TEXT, is_admin INTEGER, is_developer INTEGER,
                organization_id TEXT, organization_name TEXT, level_id TEXT,
                parent_username TEXT, updated_at REAL NOT NULL
            );
            CREATE TABLE organizations(
                id TEXT PRIMARY KEY, name TEXT, description TEXT,
                updated_at REAL NOT NULL
            );
            CREATE TABLE levels(
                id TEXT PRIMARY KEY, organization_id TEXT, name TEXT,
                parent_level_id TEXT, manager_username TEXT, updated_at REAL NOT NULL
            );
            CREATE TABLE account_factor_sets(
                username TEXT NOT NULL, target_ref TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE pending_account_registrations(
                username TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE factor_source_workspace_settings(
                username TEXT PRIMARY KEY, git_enabled INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO accounts VALUES
                ('18717974771', '', 'salt', 'hash', 'super_admin', 1, 0,
                 'default', '默认机构', 'default__ROOT', '', 1),
                ('default@Other@2', 'Other', 'salt2', 'hash2', 'user', 0, 0,
                 'default', '默认机构', 'default__ROOT', '', 1);
            INSERT INTO account_factor_sets VALUES
                ('18717974771', 'factor:target', '{}'),
                ('default@Other@2', 'factor:other', '{}');
            INSERT INTO pending_account_registrations VALUES
                ('default@Other@2', '{}', 1, 1, '');
            INSERT INTO levels VALUES
                ('default__ROOT', 'default', '默认层级', '', '18717974771', 1),
                ('default__OTHER', 'default', '其他层级', '', 'orphan-user', 1);
            INSERT INTO factor_source_workspace_settings VALUES
                ('18717974771', 0), ('orphan-user', 0);
            """
        )


def test_identity_migration_keeps_target_credentials_and_cleans_other_rows(tmp_path):
    database = tmp_path / "unifieddata.sqlite"
    backup = tmp_path / "backup.sqlite"
    _database(database)
    new_username = "GTHT@MaxJJW@123456789012"

    plan = sqlite_identity_plan(
        database,
        old_username="18717974771",
        new_username=new_username,
        organization_id="GTHT",
        alias="MaxJJW",
    )
    assert plan["other_account_count"] == 1
    assert plan["referenced_rows"]["account_factor_sets.username"] == 1
    backup_sqlite(database, backup)

    counts = apply_sqlite_identity_migration(
        database,
        old_username="18717974771",
        new_username=new_username,
        organization_id="GTHT",
        organization_name="GTHT",
        alias="MaxJJW",
    )

    with sqlite3.connect(database) as connection:
        accounts = connection.execute(
            "SELECT username, alias, organization_id, salt, hash FROM accounts"
        ).fetchall()
        factors = connection.execute(
            "SELECT username, target_ref FROM account_factor_sets"
        ).fetchall()
        organizations = connection.execute(
            "SELECT id, name FROM organizations"
        ).fetchall()
        levels = connection.execute(
            "SELECT id, manager_username FROM levels ORDER BY id"
        ).fetchall()
        workspace_settings = connection.execute(
            "SELECT username FROM factor_source_workspace_settings"
        ).fetchall()
        pending = connection.execute(
            "SELECT username FROM pending_account_registrations"
        ).fetchall()
    assert accounts == [(new_username, "MaxJJW", "GTHT", "salt", "hash")]
    assert factors == [(new_username, "factor:target")]
    assert ("GTHT", "GTHT") in organizations
    assert ("default__ROOT", new_username) in levels
    assert ("default__OTHER", "orphan-user") not in levels
    assert workspace_settings == [(new_username,)]
    assert pending == []
    assert counts["deleted_accounts"] == 1
    assert backup.exists()


def test_local_browser_device_json_migrates_owner_and_removes_other_users(tmp_path):
    path = tmp_path / "device-authorizations.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "authorizations": {
            "target": {"username": "18717974771", "expires_at": 9999999999},
            "other": {"username": "default@Other@2", "expires_at": 9999999999},
        },
    }), encoding="utf-8")

    counts = migrate_local_device_json(
        path,
        old_username="18717974771",
        new_username="GTHT@MaxJJW@123456789012",
    )

    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["authorizations"] == {
        "target": {
            "username": "GTHT@MaxJJW@123456789012",
            "expires_at": 9999999999,
        },
    }
    assert counts == {"renamed": 1, "removed": 1}


def test_local_manager_sessions_migrate_principal_and_remove_other_users(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "sessions": {
            "target-token-hash": {
                "principal": "18717974771",
                "role": "super_admin",
                "expires_at": 9999999999,
                "authentication": "device",
            },
            "other-token-hash": {
                "principal": "default@Other@2",
                "role": "user",
                "expires_at": 9999999999,
            },
        },
    }), encoding="utf-8")

    counts = migrate_local_session_json(
        path,
        old_username="18717974771",
        new_username="GTHT@MaxJJW@123456789012",
    )

    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["sessions"] == {
        "target-token-hash": {
            "principal": "GTHT@MaxJJW@123456789012",
            "role": "super_admin",
            "expires_at": 9999999999,
            "authentication": "device",
        },
    }
    assert counts == {"renamed": 1, "removed": 1}


def test_user_root_migration_renames_target_and_archives_other_roots(tmp_path):
    parent = tmp_path / "users"
    parent.mkdir()
    (parent / "18717974771").mkdir()
    (parent / "18717974771" / "profile.json").write_text("{}")
    (parent / "other-user").mkdir()
    backup = tmp_path / "migration-backup"

    counts = apply_user_root_identity_migration(
        parent,
        old_username="18717974771",
        new_username="GTHT@MaxJJW@123456789012",
        backup_root=backup,
    )

    assert counts == {"renamed": 1, "archived_other_roots": 1}
    assert (parent / "GTHT@MaxJJW@123456789012" / "profile.json").exists()
    assert not (parent / "18717974771").exists()
    assert (backup / "user-roots" / "other-user").is_dir()
