from urllib.parse import parse_qs, urlsplit

import pytest

from server.identity import manager_oidc


def test_manager_oidc_login_uses_pkce_and_safe_local_next(monkeypatch):
    monkeypatch.setattr(manager_oidc, "oidc_settings", lambda: {
        "base_url": "https://id.example", "realm": "research",
        "backchannel_base_url": "http://keycloak:8080",
        "client_id": "manager", "client_secret": "secret",
    })

    state, url = manager_oidc.start_login(
        redirect_uri="https://app.example/auth/oidc/callback",
        next_path="//evil.example/path",
    )
    assert url.startswith("https://id.example/realms/research/")
    query = parse_qs(urlsplit(url).query)
    flow = manager_oidc._FLOWS[state]
    expected = manager_oidc._challenge(flow.verifier)

    assert query["state"] == [state]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [expected]
    assert flow.next_path == "/app"


def test_manager_oidc_callback_consumes_state_and_verifies_token(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            assert args[0] == "http://keycloak:8080"
            self.kwargs = kwargs

        def exchange_code(self, code, redirect_uri, *, code_verifier=""):
            assert code == "one-time-code"
            assert redirect_uri == "https://app.example/auth/oidc/callback"
            assert code_verifier
            return {"access_token": "verified-token"}

    monkeypatch.setattr(manager_oidc, "oidc_settings", lambda: {
        "base_url": "https://id.example", "realm": "research",
        "backchannel_base_url": "http://keycloak:8080",
        "client_id": "manager", "client_secret": "secret",
    })
    monkeypatch.setattr(manager_oidc, "OIDCClient", Client)
    monkeypatch.setattr(manager_oidc, "keycloak_session", lambda token: {
        "username": "alice", "expires_in": 90,
    } if token == "verified-token" else None)
    state, _url = manager_oidc.start_login(
        redirect_uri="https://app.example/auth/oidc/callback", next_path="/app/jobs",
    )

    assert manager_oidc.finish_login(state=state, code="one-time-code") == (
        "verified-token", {"username": "alice", "expires_in": 90}, "/app/jobs", "",
    )
    with pytest.raises(ValueError):
        manager_oidc.finish_login(state=state, code="one-time-code")


def test_manager_oidc_callback_rejects_unverified_keycloak_session(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def exchange_code(self, *args, **kwargs):
            return {"access_token": "revoked"}

    monkeypatch.setattr(manager_oidc, "oidc_settings", lambda: {
        "base_url": "https://id.example", "realm": "research",
        "backchannel_base_url": "http://keycloak:8080",
        "client_id": "manager", "client_secret": "secret",
    })
    monkeypatch.setattr(manager_oidc, "OIDCClient", Client)
    monkeypatch.setattr(manager_oidc, "keycloak_session", lambda _token: None)
    state, _url = manager_oidc.start_login(
        redirect_uri="https://app.example/auth/oidc/callback",
    )

    with pytest.raises(PermissionError):
        manager_oidc.finish_login(state=state, code="one-time-code")


def test_admin_console_uses_manager_same_origin_proxy(monkeypatch):
    monkeypatch.setattr(manager_oidc, "oidc_settings", lambda: {
        "base_url": "https://id.example", "realm": "research",
    })
    assert manager_oidc.admin_console_url() == "/identity/admin/research/console/"


@pytest.mark.parametrize("requested, expected", [
    ("/app/jobs", "/app/jobs"), ("//evil.example", "/app"),
    ("/auth/oidc/start", "/app"),
])
def test_login_entry_always_uses_keycloak_without_password_fallback(requested, expected):
    from urllib.parse import urlencode
    from server.manager.http.core_get_routes import CoreGetRoutesMixin
    class Handler(CoreGetRoutesMixin):
        def _redirect_configured_ingress(self, *args, **kwargs):
            return False
        def _send_redirect(self, location):
            self.location = location
    handler = Handler()
    assert handler._get_entry_routes(urlsplit("/login?" + urlencode({"next": requested})))
    location = urlsplit(handler.location)
    assert location.path == "/auth/oidc/start"
    assert parse_qs(location.query)["next"] == [expected]
