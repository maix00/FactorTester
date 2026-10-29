import json

from scripts.migrations.keycloak_roles import (
    apply_role_mappings, main, role_mappings_for_accounts,
)


ORG = [{"id": "org-1", "name": "Org One"}]
LEVELS = [
    {"id": "root", "organization_id": "org-1", "parent_level_id": ""},
    {"id": "division", "organization_id": "org-1", "parent_level_id": "root"},
    {"id": "team", "organization_id": "org-1", "parent_level_id": "division"},
    {"id": "other", "organization_id": "org-1", "parent_level_id": "root"},
    {"id": "root-2", "organization_id": "org-2", "parent_level_id": ""},
]
ORGS = [*ORG, {"id": "org-2", "name": "Org Two"}]


def test_global_and_scoped_roles_map_without_global_promotion():
    plan = role_mappings_for_accounts([
        {"username": "root", "role": "super_admin", "is_admin": True},
        {"username": "org", "role": "org_admin", "organization_id": "org-1"},
        {"username": "level", "role": "level_admin", "organization_id": "org-1",
         "level_id": "division"},
        {"username": "dev", "role": "developer"},
        {"username": "dual", "role": "user", "is_developer": True},
        {"username": "alice", "role": "user", "organization_id": "org-1",
         "level_id": "team"},
        {"username": "unknown", "role": "operator"},
        {"username": "", "role": "super_admin"},
    ], ORGS, LEVELS)

    mappings = {item["username"]: item["client_roles"] for item in plan["mappings"]}
    assert mappings == {
        "root": ["admin_console:manage", "admin_console:read"],
        "dev": ["factor:develop"],
        "dual": ["factor:develop"],
    }
    scoped = {item["username"]: item for item in plan["scoped_admin_mappings"]}
    assert set(scoped) == {"org", "level"}
    assert scoped["org"]["managed_group_roots"] == [
        plan["realm_group_plan"]["level_paths"]["root"],
    ]
    assert set(scoped["org"]["managed_group_paths"]) == {
        plan["realm_group_plan"]["level_paths"][key]
        for key in ("root", "division", "team", "other")
    }
    assert set(scoped["level"]["managed_group_paths"]) == {
        plan["realm_group_plan"]["level_paths"][key]
        for key in ("division", "team")
    }
    level_assignable = set(scoped["level"]["assignable_administrator_groups"])
    assert len(level_assignable) == 2
    assert level_assignable <= set(scoped["org"]["assignable_administrator_groups"])
    assert {
        item["group_path"]
        for item in scoped["level"]["assignable_administrator_group_permissions"]
    } == level_assignable
    assert all(
        item["scopes"] == ["view", "view-members", "manage-members", "manage-membership"]
        for item in scoped["level"]["assignable_administrator_group_permissions"]
    )
    assert {
        item["group_path"] for item in scoped["level"]["managed_group_permissions"]
    } == set(scoped["level"]["managed_group_paths"])
    assert all(item["permission_model"] == "realm_group_fgaps" for item in scoped.values())
    assert all(item["subtree"] is True for item in scoped.values())
    assert plan["scoped_authorization_pending"] == [
        {"username": "level", "legacy_role": "level_admin",
         "reason": "realm_group_fgap_policy_not_provisioned_or_verified"},
        {"username": "org", "legacy_role": "org_admin",
         "reason": "realm_group_fgap_policy_not_provisioned_or_verified"},
    ]
    assert plan["unsupported_legacy_roles"] == {"operator": 1}
    assert plan["skipped_empty_usernames"] == 1
    memberships = {item["username"]: item["group_paths"]
                   for item in plan["realm_group_plan"]["account_memberships"]}
    assert memberships["alice"] == [plan["realm_group_plan"]["level_paths"]["team"]]
    assert any(path.endswith("administrators") for path in memberships["level"])
    assert not any(
        role.startswith("admin_console:")
        for mapping in plan["mappings"] if mapping["username"] in {"org", "level"}
        for role in mapping["client_roles"]
    )


def test_realm_group_plan_includes_every_parent_in_creation_order():
    plan = role_mappings_for_accounts(
        [{"username": "member", "role": "user", "organization_id": "org-1",
          "level_id": "team"}],
        ORGS,
        LEVELS,
    )
    paths = plan["realm_group_plan"]["paths"]
    path_set = set(paths)

    assert paths[0] == "/traderesearch"
    assert "/traderesearch/organizations" in path_set
    for leaf in plan["realm_group_plan"]["level_paths"].values():
        segments = [segment for segment in leaf.split("/") if segment]
        prefixes = ["/" + "/".join(segments[:index])
                    for index in range(1, len(segments) + 1)]
        assert set(prefixes) <= path_set
    assert paths == sorted(paths, key=lambda path: (path.count("/"), path))


def test_missing_scope_is_reported_not_guessed():
    plan = role_mappings_for_accounts([
        {"username": "org", "role": "org_admin", "organization_id": "missing"},
        {"username": "level", "role": "level_admin", "organization_id": "org-1",
         "level_id": "missing"},
    ], ORGS, LEVELS)

    assert plan["scoped_admin_mappings"] == []
    assert plan["scoped_legacy_roles_blocked"] == {
        "level_admin": [{"username": "level", "reason": "missing_level"}],
        "org_admin": [{"username": "org", "reason": "missing_organization"}],
    }


def test_invalid_hierarchy_blocks_apply_instead_of_partial_global_migration():
    class Adapter:
        def __init__(self):
            self.calls = []

        def add_client_roles(self, *args):
            self.calls.append(args)

    cyclic = [
        {"id": "a", "organization_id": "org-1", "parent_level_id": "b"},
        {"id": "b", "organization_id": "org-1", "parent_level_id": "a"},
    ]
    plan = role_mappings_for_accounts([
        {"username": "root", "role": "super_admin"},
    ], ORG, cyclic)
    adapter = Adapter()

    result = apply_role_mappings(plan, adapter, "manager-api")

    assert plan["hierarchy_errors"]
    assert result["applied"] == []
    assert "hierarchy_errors" in result["blocked"]
    assert adapter.calls == []


def test_role_apply_applies_only_global_roles_when_plan_has_no_blockers():
    class Adapter:
        def __init__(self):
            self.calls = []

        def add_client_roles(self, username, client_id, roles):
            assert client_id == "manager-api"
            if username == "alice":
                raise LookupError("missing user")
            self.calls.append((username, roles))
            return [role for role in roles if role.endswith(":manage")]

    plan = role_mappings_for_accounts([
        {"username": "root", "role": "super_admin"},
        {"username": "alice", "role": "developer"},
    ], [{"id": "default"}, *ORG], [
        {"id": "default__ROOT", "organization_id": "default"},
        {"id": "org-1__ROOT", "organization_id": "org-1"},
    ])
    adapter = Adapter()

    result = apply_role_mappings(plan, adapter, "manager-api")

    assert result["applied"] == [{
        "username": "root", "assigned_roles": ["admin_console:manage"],
    }]
    assert result["failures"] == [{"username": "alice", "error": "LookupError"}]


def test_migration_rejects_non_boolean_admin_and_developer_flags():
    plan = role_mappings_for_accounts([
        {"username": "alice", "role": "user", "is_admin": "false"},
        {"username": "bob", "role": "user", "is_admin": 1},
        {"username": "carol", "role": "user", "is_developer": "yes"},
    ], ORG, [{"id": "org-1__ROOT", "organization_id": "org-1"}])

    assert plan["mappings"] == []
    assert plan["invalid_admin_flags"] == ["alice", "bob"]
    assert plan["invalid_developer_flags"] == ["carol"]

    class Adapter:
        def __init__(self):
            self.calls = []

        def add_client_roles(self, *args):
            self.calls.append(args)

    adapter = Adapter()
    result = apply_role_mappings(plan, adapter, "manager-api")
    assert result["applied"] == []
    assert "invalid_admin_flags" in result["blocked"]
    assert "invalid_developer_flags" in result["blocked"]
    assert adapter.calls == []


def test_apply_cli_reports_scope_policy_blocker_without_connecting_to_keycloak(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "accounts.json"
    input_path.write_text(json.dumps({
        "accounts": [
            {"username": "root", "role": "super_admin"},
            {"username": "org", "role": "org_admin", "organization_id": "org-1"},
        ],
        "organizations": ORG,
        "levels": [{"id": "org-1__ROOT", "organization_id": "org-1"}],
    }))
    for name in (
        "TRADERESEARCH_KEYCLOAK_URL",
        "TRADERESEARCH_KEYCLOAK_REALM",
        "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID",
        "TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    assert main([
        "--input", str(input_path), "--roles-client-id", "manager-api", "--apply",
    ]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["apply_blocked"]["scoped_authorization_pending"][0]["username"] == "org"
