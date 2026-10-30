from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import unquote

import pytest

from scripts.migrations import keycloak_server_admission as migration
from server.identity.realm_groups import organization_group_path
from server.identity.server_admission import manager_binding_group_path


class Groups:
    realm = "traderesearch"
    base_url = "https://identity.invalid"

    def __init__(self):
        self.groups = {
            organization_group_path("org-a"): {
                "id": "org-id", "attributes": {"unrelated": ["preserve"]},
            },
        }

    def _get(self, path):
        if not path.startswith("group-by-path/"):
            raise AssertionError(path)
        group_path = "/" + unquote(path.removeprefix("group-by-path/"))
        if group_path not in self.groups:
            raise HTTPError("fixture", 404, "not found", {}, None)
        return {"path": group_path, **self.groups[group_path]}

    def group_representations(self):
        return [{"path": path, "id": item["id"]} for path, item in self.groups.items()]


def test_internal_plan_is_read_only_and_idempotent_when_bound():
    adapter = Groups()
    plan = migration.inspect_internal(adapter, server_id="server-a", organization_id="org-a")
    assert plan["changes"] == ["create_manager_group_parent", "create_manager_binding_group",
                               "bind_organization_to_manager", "bind_manager_to_organization"]
    assert plan["conflicts"] == []
    assert len(adapter.groups) == 1
    org_path = organization_group_path("org-a")
    manager_path = manager_binding_group_path("server-a")
    adapter.groups[org_path]["attributes"]["tr_internal_manager_id"] = ["server-a"]
    adapter.groups[manager_path.rpartition("/")[0]] = {"id": "parent", "attributes": {}}
    adapter.groups[manager_path] = {"id": "manager", "attributes": {
        "tr_internal_manager_id": ["server-a"], "tr_organization_id": ["org-a"],
    }}
    again = migration.inspect_internal(adapter, server_id="server-a", organization_id="org-a")
    assert again["changes"] == []
    assert again["conflicts"] == []


def test_one_server_cannot_bind_multiple_organizations_and_vice_versa():
    adapter = Groups()
    adapter.groups[organization_group_path("other")] = {
        "id": "other", "attributes": {"tr_internal_manager_id": ["server-a"]},
    }
    adapter.groups[manager_binding_group_path("server-b")] = {
        "id": "server-b", "attributes": {"tr_organization_id": ["org-a"]},
    }
    plan = migration.inspect_internal(adapter, server_id="server-a", organization_id="org-a")
    assert plan["conflicts"] == ["organization_bound_to_another_server",
                                  "server_bound_to_another_organization"]
    with pytest.raises(ValueError, match="conflicts"):
        migration._validate(plan, plan["sha256"])


def test_malformed_binding_and_wrong_digest_are_rejected():
    adapter = Groups()
    adapter.groups[organization_group_path("org-a")]["attributes"]["tr_internal_manager_id"] = "server-a"
    with pytest.raises(ValueError, match="malformed"):
        migration.inspect_internal(adapter, server_id="server-a", organization_id="org-a")
    adapter.groups[organization_group_path("org-a")]["attributes"].pop("tr_internal_manager_id")
    plan = migration.inspect_internal(adapter, server_id="server-a", organization_id="org-a")
    plan["server_id"] = "other"
    with pytest.raises(ValueError, match="digest"):
        migration._validate(plan, plan["sha256"])


def test_rollback_restores_only_reviewed_fields_and_rejects_drift():
    before = {"unrelated": ["keep"]}
    intended = {"tr_internal_manager_id": ["server-a"]}
    current = {"attributes": {**before, **intended}}
    assert migration._restore_attrs(None, current, before, intended) == before
    current["attributes"]["unrelated"] = ["changed"]
    with pytest.raises(ValueError, match="other Keycloak group attributes"):
        migration._restore_attrs(None, current, before, intended)


def test_public_policy_cannot_target_a_different_client():
    with pytest.raises(ValueError, match="own login client"):
        migration.inspect_public(None, server_id="public", directory_client_id="directory",
                                 login_client_id="manager", roles_client_id="other")
