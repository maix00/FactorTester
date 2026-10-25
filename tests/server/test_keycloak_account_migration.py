import sqlite3
from scripts.migrations.keycloak_accounts import export_accounts


def test_export_accounts_without_password(tmp_path):
    db = tmp_path / "unified.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE accounts (
            username TEXT PRIMARY KEY, alias TEXT, salt TEXT, hash TEXT,
            role TEXT, is_admin INTEGER, organization_id TEXT,
            organization_name TEXT, level_id TEXT, parent_username TEXT,
            updated_at REAL)""")
        conn.execute("INSERT INTO accounts VALUES ('alice','A','s','h','user',0,'o','Org','l','',0)")
    rows = export_accounts(db)
    assert rows == [{"username": "alice", "alias": "A", "role": "user",
                     "is_admin": False, "organization": "Org",
                     "parent_username": ""}]


def test_case_collisions_are_reported():
    from scripts.migrations.keycloak_accounts import case_collisions
    assert case_collisions([
        {"username": "Alice"}, {"username": "alice"}, {"username": "bob"},
    ]) == {"alice": ["Alice", "alice"]}
