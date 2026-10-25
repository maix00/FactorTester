from server.identity.keycloak import KeycloakAdminAdapter


class Fake(KeycloakAdminAdapter):
    def __init__(self): super().__init__("http://keycloak", "realm")
    def _get(self, path):
        return {
            "users?username=alice&exact=true": [{"username": "alice", "id": "u1"}],
            "users/u1/groups": [{"path": "/team/a"}],
            "users/u1/organizations": [{"name": "org-a"}],
        }[path]


def test_admin_adapter_maps_user_groups_and_orgs():
    identity = Fake().user("alice")
    assert identity.username == "alice"
    assert identity.groups == ("/team/a",)
    assert identity.organizations == ("org-a",)
