import sqlite3

import pytest

from server.permissions.migration_inventory import inventory


def test_inventory_counts_conflicts_without_disclosing_identity(tmp_path):
    path = tmp_path / "permissions.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE permission_entries (
            id INTEGER PRIMARY KEY, subject TEXT, resource_type TEXT,
            resource_ref TEXT, action TEXT, scope TEXT, effect TEXT
        )""")
        db.executemany(
            "INSERT INTO permission_entries VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "user:private", "report", "report:private", "read", "explicit", "allow"),
                (2, "user:private", "report", "report:private", "read", "explicit", "deny"),
                (3, "group:private", "report", "*", "read", "subtree", "allow"),
            ],
        )
    result = inventory(path)
    assert result["total"] == 3
    assert result["conflicting_exact_rules"] == 1
    assert result["wildcard_rules"] == 1
    assert "private" not in repr(result)


def test_inventory_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        inventory(path)
    assert not path.exists()
