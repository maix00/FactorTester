from server.identity.keycloak import KeycloakAdminAdapter


class Fake(KeycloakAdminAdapter):
    def __init__(self):
        super().__init__("http://keycloak", "realm")
        self.puts = []
    def _get(self, path):
        values = {
            "users?username=alice&exact=true": [{"username": "alice", "id": "u1"}],
            "users/u1/groups": [{"path": "/team/a"}],
            "organizations": [{"id": "o1", "name": "org-a"}],
            "organizations/o1/members": [{"username": "alice"}],
            "clients?clientId=manager-api": [{"clientId": "manager-api", "id": "c1"}],
            "users/u1/role-mappings/clients/c1": [{"name": "admin_console:read"}],
            "users/u1": {
                "id": "u1", "username": "alice", "enabled": True,
                "attributes": {"other": ["preserve"]},
            },
            "clients/c1/roles/admin_console%3Amanage": {
                "id": "r1", "name": "admin_console:manage", "clientRole": True,
            },
        }
        return values[path]
    def _put(self, path, payload):
        self.puts.append((path, payload))
        return 204
    def _post(self, path, payload):
        self.puts.append((path, payload))
        return 204, ""


def test_admin_adapter_maps_user_groups_and_orgs():
    identity = Fake().user("alice")
    assert identity.username == "alice"
    assert identity.groups == ("/team/a",)
    assert identity.organizations == ("org-a",)


def test_admin_adapter_adds_only_missing_existing_client_roles():
    adapter = Fake()
    assigned = adapter.add_client_roles(
        "alice", "manager-api", ["admin_console:manage", "admin_console:read"],
    )
    assert assigned == ["admin_console:manage"]
    assert adapter.puts == [(
        "users/u1/role-mappings/clients/c1",
        [{"id": "r1", "name": "admin_console:manage", "clientRole": True}],
    )]


def test_admin_adapter_resolves_stable_identity_exactly_and_rejects_ambiguity():
    from uuid import uuid4

    identity_id = str(uuid4())

    class ByIdentity(Fake):
        def _get(self, path):
            if path.startswith("users?q="):
                return [{
                    "id": "u1", "username": "alice",
                    "attributes": {"tr_identity_id": [identity_id]},
                }]
            return super()._get(path)

    adapter = ByIdentity()
    assert adapter.user_by_identity_id(identity_id)["id"] == "u1"

    class Ambiguous(ByIdentity):
        def _get(self, path):
            if path.startswith("users?q="):
                return [
                    {"id": "u1", "attributes": {"tr_identity_id": [identity_id]}},
                    {"id": "u2", "attributes": {"tr_identity_id": [identity_id]}},
                ]
            return super()._get(path)

    try:
        Ambiguous().user_by_identity_id(identity_id)
    except LookupError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous stable identity must fail closed")


def test_admin_adapter_migration_update_preserves_unrelated_attributes_and_credentials():
    from uuid import uuid4

    adapter = Fake()
    adapter.update_migrated_user(
        "u1", username="alice", email="alice@example.test",
        attributes={"tr_identity_id": (str(uuid4()),)}, enabled=False,
    )
    path, payload = adapter.puts[-1]
    assert path == "users/u1"
    assert payload["enabled"] is False
    assert payload["attributes"]["other"] == ["preserve"]
    assert "credentials" not in payload
    assert payload["email"] == "alice@example.test"
