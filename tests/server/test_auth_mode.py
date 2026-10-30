from server.identity.auth_mode import auth_mode, keycloak_enabled, legacy_enabled


def test_auth_modes(monkeypatch):
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "dual")
    # dual is retired as a mode switch; it must never re-enable local auth.
    assert auth_mode() == "keycloak"
    assert keycloak_enabled() and not legacy_enabled()
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "legacy")
    assert auth_mode() == "keycloak"
    assert keycloak_enabled() and not legacy_enabled()
    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "bogus")
    assert auth_mode() == "keycloak"
    assert keycloak_enabled() and not legacy_enabled()


def test_keycloak_is_the_default_authentication_mode(monkeypatch):
    monkeypatch.delenv("TRADERESEARCH_AUTH_MODE", raising=False)
    monkeypatch.delenv("FACTORTESTER_AUTH_MODE", raising=False)
    assert auth_mode() == "keycloak"
    assert keycloak_enabled() and not legacy_enabled()
