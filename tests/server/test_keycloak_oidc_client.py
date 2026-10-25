from server.identity.keycloak import OIDCClient


class Fake(OIDCClient):
    def __init__(self): super().__init__("http://kc", "realm", "web")
    def _token(self, form):
        return {"form": form, "access_token": "a"}


def test_code_exchange_includes_verifier():
    result = Fake().exchange_code("c", "https://app/cb", code_verifier="v")
    assert result["form"]["grant_type"] == "authorization_code"
    assert result["form"]["code_verifier"] == "v"


def test_refresh_uses_refresh_grant():
    assert Fake().refresh("r")["form"]["grant_type"] == "refresh_token"
