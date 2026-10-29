import sqlite3

from scripts.migrations.keycloak_accounts import export_accounts, export_directory


def _create_directory(db):
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE accounts (
                username TEXT PRIMARY KEY, alias TEXT, salt TEXT, hash TEXT,
                role TEXT, is_admin INTEGER, is_developer INTEGER,
                organization_id TEXT, organization_name TEXT, level_id TEXT,
                parent_username TEXT, updated_at REAL
            );
            CREATE TABLE organizations (
                id TEXT PRIMARY KEY, name TEXT, description TEXT, updated_at REAL
            );
            CREATE TABLE levels (
                id TEXT PRIMARY KEY, organization_id TEXT, name TEXT,
                parent_level_id TEXT, manager_username TEXT, updated_at REAL
            );
            INSERT INTO organizations VALUES ('org-1', 'Org One', '', 1);
            INSERT INTO levels VALUES ('root-1', 'org-1', 'Root', '', '', 1);
            INSERT INTO levels VALUES ('child-1', 'org-1', 'Child', 'root-1', 'alice', 1);
            INSERT INTO accounts VALUES (
                'alice', 'A', 'salt-secret', 'hash-secret', 'level_admin', 0, 0,
                'org-1', 'Org One', 'child-1', '', 1
            );
        """)


def test_export_accounts_preserves_nonsecret_hierarchy_without_password_material(tmp_path):
    db = tmp_path / "unified.db"
    _create_directory(db)

    rows = export_accounts(db)

    assert rows == [{
        "username": "alice", "alias": "A", "role": "level_admin",
        "is_admin": False, "is_developer": False,
        "organization_id": "org-1", "organization": "Org One",
        "level_id": "child-1", "parent_username": "",
    }]
    assert not {"salt", "hash", "password", "password_hash"} & rows[0].keys()


def test_export_directory_preserves_levels_and_does_not_mutate_source(tmp_path):
    db = tmp_path / "unified.db"
    _create_directory(db)

    directory = export_directory(db)

    assert directory["organizations"] == [{
        "id": "default", "name": "默认机构", "description": "系统默认机构",
        "synthetic": True,
    }, {"id": "org-1", "name": "Org One", "description": ""}]
    assert [row["id"] for row in directory["levels"]] == [
        "default__ROOT", "child-1", "org-1__ROOT", "root-1",
    ]
    assert directory["levels"][1]["parent_level_id"] == "root-1"
    assert directory["levels"][0]["synthetic"] is True
    assert directory["levels"][2]["synthetic"] is True

    with sqlite3.connect(db) as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert names == {"accounts", "organizations", "levels"}


def test_read_only_export_does_not_create_missing_tables(tmp_path):
    db = tmp_path / "partial.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")

    directory = export_directory(db)

    assert directory["accounts"] == []
    assert directory["organizations"][0]["synthetic"] is True
    assert directory["levels"][0]["synthetic"] is True
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [("unrelated",)]


def test_non_boolean_legacy_flags_are_preserved_for_safe_blocking(tmp_path):
    db = tmp_path / "unified.db"
    _create_directory(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE accounts SET is_admin = 2, is_developer = 3")

    account = export_accounts(db)[0]

    assert account["is_admin"] == 2
    assert account["is_developer"] == 3


def test_case_collisions_are_reported():
    from scripts.migrations.keycloak_accounts import case_collisions

    assert case_collisions([
        {"username": "Alice"}, {"username": "alice"}, {"username": "bob"},
    ]) == {"alice": ["Alice", "alice"]}
