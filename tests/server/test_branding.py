from server import branding


def test_new_env_wins_and_legacy_still_reads(monkeypatch):
    monkeypatch.setenv("FACTORTESTER_X", "old")
    assert branding.env("X") == "old"
    monkeypatch.setenv("TRADERESEARCH_X", "new")
    assert branding.env("X") == "new"
    assert branding.PRODUCT_NAME == "TradeResearch"
