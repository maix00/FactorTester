import pytest

from server.identity.federation_identity_sync import (
    DESTINATION_ALLOWED_ATTRIBUTE,
    PUBLIC_LOGIN_ROLE,
    SOURCE_ENABLED_ATTRIBUTE,
    IdentitySyncTransitionError,
    assert_destination_sync_can_be_disabled,
    group_sync_value,
    identity_sync_disable_signature,
    organization_group_from_admin_scope,
    organization_group_paths,
    public_identity_sync_eligible,
    set_group_sync_value,
    verify_identity_sync_disable_signature,
)
from server.identity.keycloak import KeycloakAdminAdapter
from server.identity.realm_groups import (
    organization_admin_group_path,
    organization_group_path,
)


class FakeKeycloakAdmin(KeycloakAdminAdapter):
    def __init__(self, groups):
        super().__init__("http://keycloak", "traderesearch")
        self.groups = {row["id"]: dict(row) for row in groups}
        self.put_calls = []

    def _all_groups(self, parent=""):
        if parent:
            return []
        return list(self.groups.values())

    def _get(self, path):
        if path.startswith("groups/"):
            return dict(self.groups[path.split("/", 1)[1]])
        raise AssertionError(path)

    def _put(self, path, payload):
        group_id = path.split("/", 1)[1]
        self.put_calls.append((group_id, payload))
        self.groups[group_id] = dict(payload)
        return 204


def test_organization_directory_only_returns_root_groups():
    org = organization_group_path("Org A")
    assert organization_group_paths([
        {"path": org},
        {"path": org + "/levels/level-1"},
        {"path": "/traderesearch/other/org-a"},
    ]) == [org]


def test_org_admin_scope_resolves_only_its_exact_organization():
    group_path = organization_group_path("Org A")
    assert organization_group_from_admin_scope(
        organization_admin_group_path("Org A"),
    ) == group_path
    assert organization_group_from_admin_scope(
        organization_admin_group_path("Org A") + "/nested",
    ) == ""
    assert organization_group_from_admin_scope("/traderesearch/organizations/org-a") == ""


def test_sync_policy_writes_only_the_selected_keycloak_group_attribute():
    path = organization_group_path("Org A")
    adapter = FakeKeycloakAdmin([{
        "id": "group-1", "path": path, "name": "Org A",
        "attributes": {"external_ref": ["keep-me"]},
    }])

    updated = set_group_sync_value(
        adapter, group_path=path, attribute=SOURCE_ENABLED_ATTRIBUTE, enabled=True,
    )

    assert group_sync_value(updated, SOURCE_ENABLED_ATTRIBUTE)
    assert updated["attributes"] == {
        "external_ref": ["keep-me"], SOURCE_ENABLED_ATTRIBUTE: ["true"],
    }
    assert adapter.put_calls[0][0] == "group-1"
    assert not group_sync_value(updated, DESTINATION_ALLOWED_ATTRIBUTE)


def test_keycloak_group_update_rejects_missing_or_ambiguous_paths():
    path = organization_group_path("Org A")
    duplicate = FakeKeycloakAdmin([
        {"id": "one", "path": path}, {"id": "two", "path": path},
    ])
    with pytest.raises(LookupError, match="missing or ambiguous"):
        duplicate.update_group_attributes(path, {SOURCE_ENABLED_ATTRIBUTE: ["true"]})

    missing = FakeKeycloakAdmin([])
    with pytest.raises(LookupError, match="missing or ambiguous"):
        missing.update_group_attributes(path, {SOURCE_ENABLED_ATTRIBUTE: ["true"]})


def test_sync_policy_rejects_unknown_attributes():
    adapter = FakeKeycloakAdmin([])
    with pytest.raises(ValueError, match="unsupported"):
        set_group_sync_value(adapter, group_path="/x", attribute="other", enabled=True)


class FakeRoleHolders:
    def __init__(self, users):
        self.users = users
        self.calls = []

    def client_role_users(self, client_id, role_name, **bounds):
        self.calls.append((client_id, role_name, bounds))
        return [dict(user) for user in self.users]

    def user_group_paths(self, user_id, **bounds):
        del bounds
        user = next(user for user in self.users if user["id"] == user_id)
        return set(user["groups"])


def _superadmin(user_id, organization, *, enabled=True):
    return {
        "id": user_id,
        "username": user_id,
        "enabled": enabled,
        "groups": [organization_group_path(organization) + "/levels/root"],
    }


def test_sync_disable_requires_an_active_superadmin_in_another_organization():
    target = organization_group_path("ResearchOrg")
    adapter = FakeRoleHolders([_superadmin("org-admin", "ResearchOrg")])

    with pytest.raises(IdentitySyncTransitionError, match="another organization"):
        assert_destination_sync_can_be_disabled(
            adapter,
            group_path=target,
            roles_client_id="manager-api",
        )

    assert adapter.calls == [(
        "manager-api", "admin_console:manage", {"page_size": 100, "max_users": 1000},
    )]


def test_sync_disable_requires_removing_target_org_superadmin_after_handoff():
    target = organization_group_path("ResearchOrg")
    adapter = FakeRoleHolders([
        _superadmin("org-admin", "ResearchOrg"),
        _superadmin("replacement-admin", "OperationsOrg"),
    ])

    with pytest.raises(IdentitySyncTransitionError, match="remove the public super administrator"):
        assert_destination_sync_can_be_disabled(
            adapter,
            group_path=target,
            roles_client_id="manager-api",
        )


def test_sync_disable_is_allowed_after_role_handoff_for_any_organization():
    target = organization_group_path("ResearchOrg")
    adapter = FakeRoleHolders([
        _superadmin("replacement-admin", "OperationsOrg"),
    ])
    assert_destination_sync_can_be_disabled(
        adapter,
        group_path=target,
        roles_client_id="manager-api",
    )


def test_sync_disable_fails_closed_if_superadmin_has_no_organization_membership():
    adapter = FakeRoleHolders([{
        "id": "admin", "username": "admin", "enabled": True, "groups": [],
    }])
    with pytest.raises(RuntimeError, match="no verifiable organization"):
        assert_destination_sync_can_be_disabled(
            adapter,
            group_path=organization_group_path("ResearchOrg"),
            roles_client_id="manager-api",
        )


def test_sync_disable_fails_closed_if_keycloak_omits_enabled_status():
    adapter = FakeRoleHolders([{
        "id": "admin", "username": "admin",
        "groups": [organization_group_path("OperationsOrg")],
    }])
    with pytest.raises(RuntimeError, match="omitted enabled status"):
        assert_destination_sync_can_be_disabled(
            adapter,
            group_path=organization_group_path("ResearchOrg"),
            roles_client_id="manager-api",
        )


def test_disabled_superadmin_does_not_block_sync_disable():
    adapter = FakeRoleHolders([
        _superadmin("disabled-org-admin", "ResearchOrg", enabled=False),
        _superadmin("active-admin", "OperationsOrg"),
    ])
    assert_destination_sync_can_be_disabled(
        adapter,
        group_path=organization_group_path("ResearchOrg"),
        roles_client_id="manager-api",
    )


def test_sync_disable_signature_is_bound_and_short_lived():
    signature = identity_sync_disable_signature(
        "peer-secret",
        requester_server_id="internal-1",
        group_path=organization_group_path("ResearchOrg"),
        issued_at=1000,
        request_id="0123456789abcdef",
    )
    common = {
        "secret": "peer-secret",
        "requester_server_id": "internal-1",
        "group_path": organization_group_path("ResearchOrg"),
        "issued_at": 1000,
        "request_id": "0123456789abcdef",
        "signature": signature,
        "now": 1010,
    }
    assert verify_identity_sync_disable_signature(**common)
    assert not verify_identity_sync_disable_signature(
        **{**common, "group_path": organization_group_path("OtherOrg")},
    )
    assert not verify_identity_sync_disable_signature(**{**common, "now": 1031})


@pytest.mark.parametrize(
    ("roles", "source_enabled", "destination_allowed", "expected"),
    [
        ([PUBLIC_LOGIN_ROLE], True, True, True),
        ([], True, True, False),
        ([PUBLIC_LOGIN_ROLE], False, True, False),
        ([PUBLIC_LOGIN_ROLE], True, False, False),
        ("malformed", True, True, False),
    ],
)
def test_public_identity_sync_is_gated_by_both_policies_and_public_login_role(
    roles, source_enabled, destination_allowed, expected,
):
    assert public_identity_sync_eligible(
        roles,
        source_enabled=source_enabled,
        destination_allowed=destination_allowed,
    ) is expected
