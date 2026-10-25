from server.services.nautilus_bridge import runtime_status


def test_missing_runtime_is_reported(monkeypatch):
    monkeypatch.setattr(runtime_status.util, "find_spec", lambda name: None)
    status = runtime_status.nautilus_runtime_status()
    assert status["available"] is False
    assert status["compatible"] is False


def test_matching_version_is_compatible(monkeypatch):
    monkeypatch.setattr(runtime_status.util, "find_spec", lambda name: object())
    monkeypatch.setattr(runtime_status.metadata, "version", lambda name: runtime_status.NAUTILUS_VERSION)
    status = runtime_status.nautilus_runtime_status()
    assert status["available"] is True
    assert status["compatible"] is True
