from server.identity.auth_mode import auth_mode, keycloak_enabled, legacy_enabled


def test_auth_modes(monkeypatch):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "dual")
    assert auth_mode() == "dual"
    assert keycloak_enabled() and legacy_enabled()
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "bogus")
    assert auth_mode() == "legacy"
