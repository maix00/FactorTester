from server.identity.keycloak import KeycloakAdminAdapter


class Fake(KeycloakAdminAdapter):
    def __init__(self): super().__init__("http://kc", "realm")
    def _post(self, path, payload):
        assert path == "users"
        assert payload["requiredActions"] == ["UPDATE_PASSWORD"]
        return 201, "http://kc/admin/realms/realm/users/u-1"


def test_create_user_requests_password_update():
    assert Fake().create_user(username="alice", email="alice@example.com") == "u-1"
