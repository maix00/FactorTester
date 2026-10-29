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


def test_admin_console_manage_permission(tmp_path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.add(PermissionEntry(
        subject="group:ops", resource_type="admin_console",
        resource_ref="dispatch", action="manage",
    ))
    assert store.allows(subject="group:ops", resource_type="admin_console",
                        resource_ref="dispatch", action="manage")


def test_subject_set_denies_any_matching_group_and_audits_changes(tmp_path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.set_entry(PermissionEntry(
        subject="group:research", resource_type="agent_assistant",
        resource_ref="global", action="use", created_by="admin:root",
        reason="Research team access",
    ))
    assert store.allows_any(
        subjects=("user:alice", "group:research"),
        resource_type="agent_assistant", resource_ref="global", action="use",
    )
    store.set_entry(PermissionEntry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use", effect="deny",
        created_by="admin:root", reason="Access paused",
    ))
    assert not store.allows_any(
        subjects=("user:alice", "group:research"),
        resource_type="agent_assistant", resource_ref="global", action="use",
    )
    audit = store.audit_for_resource(
        resource_type="agent_assistant", action="use",
    )
    assert [item["new_effect"] for item in audit] == ["deny", "allow"]
    assert audit[0]["actor"] == "admin:root"


def test_remove_permission_revokes_exact_rule_and_audits_it(tmp_path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.set_entry(PermissionEntry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use", created_by="admin:root",
        reason="Grant access",
    ))
    assert store.remove_entry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use", scope="explicit",
        actor="admin:root", reason="No longer needed",
    )
    assert not store.allows(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use",
    )
    assert not store.remove_entry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use", scope="explicit",
        actor="admin:root", reason="Already removed",
    )
    audit = store.audit_for_resource(
        resource_type="agent_assistant", action="use",
    )
    assert audit[0]["old_effect"] == "allow"
    assert audit[0]["new_effect"] == ""


def test_agent_assistant_permission_is_default_deny_and_supports_explicit_subjects(
    tmp_path, monkeypatch,
):
    from server.permissions import agent_assistant

    db = tmp_path / "permissions.db"
    monkeypatch.setenv("TRADERESEARCH_PERMISSIONS_DB", str(db))
    monkeypatch.delenv("FACTORTESTER_PERMISSIONS_DB", raising=False)
    monkeypatch.delenv("TRADERESEARCH_KEYCLOAK_URL", raising=False)
    monkeypatch.delenv("FACTORTESTER_KEYCLOAK_URL", raising=False)
    assert not agent_assistant.can_use_agent_assistant("alice")

    PermissionStore(db).set_entry(PermissionEntry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use",
    ))
    assert agent_assistant.can_use_agent_assistant("alice")
    assert agent_assistant.can_use_agent_assistant("root", "super_admin")
    assert not agent_assistant.can_use_agent_assistant("")


def test_agent_assistant_fails_closed_when_keycloak_subjects_cannot_be_resolved(
    tmp_path, monkeypatch,
):
    from server.permissions import agent_assistant

    db = tmp_path / "permissions.db"
    monkeypatch.setenv("TRADERESEARCH_PERMISSIONS_DB", str(db))
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_URL", "https://identity.example")
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_REALM", "research")
    monkeypatch.setattr(
        agent_assistant, "resolve_permission_subjects",
        lambda _username: (("user:alice",), False),
    )
    PermissionStore(db).set_entry(PermissionEntry(
        subject="user:alice", resource_type="agent_assistant",
        resource_ref="global", action="use",
    ))
    assert not agent_assistant.can_use_agent_assistant("alice")
