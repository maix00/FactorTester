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


def test_subtree_and_deny_override(tmp_path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.add(PermissionEntry(
        subject="group:team/a", resource_type="report",
        resource_ref="report:job", action="read", scope="subtree",
    ))
    store.add(PermissionEntry(
        subject="group:team/a", resource_type="report",
        resource_ref="report:job:secret", action="read", effect="deny",
    ))
    assert store.allows(subject="group:team/a", resource_type="report",
                        resource_ref="report:job:ok", action="read")
    assert not store.allows(subject="group:team/a", resource_type="report",
                           resource_ref="report:job:secret", action="read")
