from server.jobs.storage.couchdb_authority import authority_enabled


def test_authority_defaults_on_when_couchdb_url_is_configured(monkeypatch):
    monkeypatch.delenv("TRADERESEARCH_COUCHDB_AUTHORITY", raising=False)
    monkeypatch.setenv("FACTORTESTER_COUCHDB_URL", "http://couch")
    assert authority_enabled() is True
    monkeypatch.setenv("TRADERESEARCH_COUCHDB_AUTHORITY", "0")
    assert authority_enabled() is False
