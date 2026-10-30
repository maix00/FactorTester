from __future__ import annotations

import pytest

from server.identity.keycloak import Identity
from server.identity.keycloak_directory import (
    clear_directory_cache,
    managed_users_for_claims,
    users_in_admin_scope,
)
from server.identity.realm_groups import (
    GROUP_ROOT,
    component,
    level_admin_group_path,
    organization_admin_group_path,
)


class DirectoryAdapter:
    base_url = "https://identity.example.test"
    realm = "trade"

    def __init__(self):
        self.calls: list[str] = []
        self.by_path = {
            f"{GROUP_ROOT}/organizations/{component('org', 'gtht')}": [
                Identity(
                    username="member-a", display_name="Member A", enabled=True,
                    subject="subject-a", attributes={
                        "tr_identity_id": ("identity-a",),
                        "tr_organization_id": ("gtht",),
                    },
                ),
                Identity(username="disabled", enabled=False, subject="subject-disabled"),
            ],
            GROUP_ROOT: [
                Identity(username="member-a", display_name="Member A", enabled=True, subject="subject-a"),
                Identity(username="member-b", display_name="Member B", enabled=True, subject="subject-b"),
            ],
        }

    def group_tree_members(self, path, *, max_groups, max_users):
        self.calls.append(path)
        return self.by_path.get(path, [])


def test_scoped_directory_uses_only_verified_admin_group_roots():
    clear_directory_cache()
    adapter = DirectoryAdapter()
    group = organization_admin_group_path("gtht")

    result = users_in_admin_scope(
        groups=(group,), roles=(), adapter=adapter, limit=10,
    )

    expected_path = f"{GROUP_ROOT}/organizations/{component('org', 'gtht')}"
    assert adapter.calls == [expected_path]
    assert [user["username"] for user in result["users"]] == ["member-a"]
    assert result["users"][0]["tr_identity_id"] == "identity-a"
    assert result["users"][0]["organization_id"] == "gtht"


def test_super_admin_can_page_realm_tree_and_filter_without_changing_scope():
    clear_directory_cache()
    adapter = DirectoryAdapter()

    result = users_in_admin_scope(
        groups=(), roles=("admin_console:manage",), adapter=adapter,
        query="member", offset=1, limit=1,
    )

    assert adapter.calls == [GROUP_ROOT]
    assert result["total"] == 2
    assert [user["username"] for user in result["users"]] == ["member-b"]
    assert result["has_more"] is False


def test_level_admin_scope_is_nested_member_subtree():
    clear_directory_cache()
    adapter = DirectoryAdapter()
    admin_group = level_admin_group_path("gtht", "level-2")

    result = users_in_admin_scope(
        groups=(admin_group,), roles=(), adapter=adapter,
    )

    expected = f"{GROUP_ROOT}/organizations/{component('org', 'gtht')}/levels/{component('level', 'level-2')}"
    assert adapter.calls == [expected]
    assert result["total"] == 0


def test_managed_claim_projection_is_bounded_and_excludes_inactive_members():
    clear_directory_cache()
    adapter = DirectoryAdapter()
    group = organization_admin_group_path("gtht")

    users = managed_users_for_claims(
        groups=(group,), roles=(), adapter=adapter,
    )

    assert adapter.calls == [
        f"{GROUP_ROOT}/organizations/{component('org', 'gtht')}"
    ]
    assert [user["username"] for user in users] == ["member-a"]


def test_unprivileged_or_invalid_pagination_fails_closed():
    with pytest.raises(PermissionError):
        users_in_admin_scope(groups=(), roles=(), adapter=DirectoryAdapter())
    with pytest.raises(ValueError):
        users_in_admin_scope(
            groups=(organization_admin_group_path("gtht"),), roles=(),
            adapter=DirectoryAdapter(), limit=201,
        )
