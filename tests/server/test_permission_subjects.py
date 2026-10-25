from server.permissions.subjects import subjects_for_user


def test_subjects_default_to_user(monkeypatch):
    monkeypatch.delenv("TRADERESEARCH_KEYCLOAK_URL", raising=False)
    monkeypatch.delenv("FACTORTESTER_KEYCLOAK_URL", raising=False)
    assert subjects_for_user("alice") == ["user:alice"]
