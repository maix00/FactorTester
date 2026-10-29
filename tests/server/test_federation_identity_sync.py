import pytest

from server.identity.federation_identity_sync import (
    DESTINATION_ALLOWED_ATTRIBUTE,
    SOURCE_ENABLED_ATTRIBUTE,
    group_sync_value,
    organization_group_from_admin_scope,
    organization_group_paths,
    set_group_sync_value,
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
