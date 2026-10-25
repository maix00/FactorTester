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


def test_strategy_family_fails_fast_without_runtime(monkeypatch):
    from server.services.nautilus_bridge import strategy_backtest

    monkeypatch.setattr(
        "server.services.nautilus_bridge.runtime_status.nautilus_runtime_status",
        lambda: {"available": False, "version": "", "expected": "2.0.0rc8", "compatible": False},
    )
    try:
        strategy_backtest.run_strategy_family_run_spec(
            job_spec={}, plan={"strategy": {"kind": "threshold", "parameters": {}}},
            output_dir=__import__("pathlib").Path("."),
        )
    except ValueError as exc:
        assert "Nautilus runtime unavailable" in str(exc)
    else:
        raise AssertionError("expected a runtime error")
