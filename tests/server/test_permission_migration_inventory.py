import sqlite3

import pytest

from server.permissions.entries import PermissionEntry, PermissionStore
from server.permissions.migration_inventory import inventory


def test_inventory_counts_conflicts_without_disclosing_identity(tmp_path):
    path = tmp_path / "permissions.db"
    store = PermissionStore(path)
    for effect in ("allow", "deny"):
        store.add(PermissionEntry("user:private", "report", "report:private",
                                  "read", effect=effect))
    store.add(PermissionEntry("group:private", "report", "*", "read",
                              scope="subtree"))
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
