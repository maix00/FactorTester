from __future__ import annotations

import pytest

from server.permissions.entries import PermissionEntry, PermissionStore


def test_default_deny_and_explicit_allow(tmp_path):
    store = PermissionStore(tmp_path / "permissions.db")
    assert not store.allows(
        subject="user:alice", resource_type="report",
        resource_ref="report:r:1", action="read",
    )
    store.add(PermissionEntry(
        subject="user:alice", resource_type="report",
        resource_ref="report:r:1", action="read", created_by="admin:root",
    ))
    assert store.allows(
        subject="user:alice", resource_type="report",
        resource_ref="report:r:1", action="read",
    )


def test_invalid_permission_is_rejected():
    with pytest.raises(ValueError):
        PermissionEntry(
            subject="user:alice", resource_type="report",
            resource_ref="r", action="delete_all",
        )
