"""Nautilus capability responses project the same source registry as RunSpec."""

from types import SimpleNamespace

from server.services.nautilus_bridge.capabilities import (
    market_data_source_capabilities,
    nautilus_backtest_submission_capability,
    native_capabilities,
)


def test_market_data_capabilities_are_source_declared_without_product_probes(monkeypatch):
    from server.services.nautilus_bridge import source_registry

    row = SimpleNamespace(
        family_key="ExampleSource", member_key="ExampleMIN15", frequency="MIN15",
        sampling_mode="bar", data_kind="ohlcv_bar", market_depth="not_applicable",
        delivery_mode="historical_snapshot", mode_available=True, timezone="UTC",
        layout="arrow", naming_scheme="canonical", time_columns=(("time", "MIN15"),),
        data_columns=(("close", "CLOSE"),), instrument_scope="physical_contract",
        bar_time_semantics="interval_end", raw_timestamp_unit="s",
        adapter_id="example_adapter_v1", reason="",
        supported_book_types=("L1_MBP",),
    )
    registry = SimpleNamespace(capabilities=lambda: (row,))
    monkeypatch.setattr(source_registry, "from_server_sources", lambda: registry)

    projected = market_data_source_capabilities()
    assert projected == {
        "available": True,
        "members": [{
            "family_key": "ExampleSource", "member_key": "ExampleMIN15",
            "frequency": "MIN15", "sampling_mode": "bar",
            "data_kind": "ohlcv_bar", "market_depth": "not_applicable",
            "delivery_mode": "historical_snapshot", "mode_available": True,
            "timezone": "UTC", "layout": "arrow", "naming_scheme": "canonical",
            "time_columns": {"time": "MIN15"}, "data_columns": {"close": "CLOSE"},
            "instrument_scope": "physical_contract",
            "bar_time_semantics": "interval_end", "raw_timestamp_unit": "s",
            "adapter_id": "example_adapter_v1", "adapter_available": True,
            "supported_book_types": ["L1_MBP"], "reason": "",
        }],
    }


def test_native_capabilities_expose_source_owned_book_type_contracts(monkeypatch):
    monkeypatch.setattr(
        "server.services.nautilus_bridge.capabilities.market_data_source_capabilities",
        lambda: {"available": True, "members": [{
            "member_key": "LocalCNFuturesContractMIN1",
            "adapter_available": True,
            "supported_book_types": ["L1_MBP"],
        }]},
    )
    result = native_capabilities()
    assert result["market_data_sources"]["members"][0]["member_key"] == (
        "LocalCNFuturesContractMIN1"
    )
    assert result["market_data_sources"]["members"][0]["supported_book_types"] == ["L1_MBP"]


def test_backtest_submission_requires_explicit_runner_readiness(monkeypatch):
    import server.services.nautilus_bridge.capabilities as capabilities

    monkeypatch.setattr(
        capabilities.metadata, "version", lambda _name: "2.0.0rc7",
    )
    monkeypatch.setattr(
        capabilities, "native_configuration_schema",
        lambda: {"native_version": "2.0.0rc7"},
    )
    monkeypatch.setattr(
        "server.modules.single_factor_test.process_runners.nautilus_backtest_runner_status",
        lambda: SimpleNamespace(available=False, reason="worker dependencies missing"),
        raising=False,
    )

    unavailable = nautilus_backtest_submission_capability()
    assert unavailable["available"] is False
    assert unavailable["reason"] == "worker dependencies missing"
    assert unavailable["runner_path"] == (
        "server.modules.single_factor_test.process_runners:run_group"
    )

    monkeypatch.setattr(
        "server.modules.single_factor_test.process_runners.nautilus_backtest_runner_status",
        lambda: SimpleNamespace(available=True, reason=""),
        raising=False,
    )
    available = nautilus_backtest_submission_capability()
    assert available["available"] is True
    assert available["reason"] == ""


def test_native_capabilities_do_not_advertise_unregistered_backtest_runner(monkeypatch):
    import server.services.nautilus_bridge.capabilities as capabilities

    monkeypatch.setattr(
        capabilities.metadata, "version", lambda _name: "2.0.0rc7",
    )
    monkeypatch.setattr(
        capabilities, "native_configuration_schema",
        lambda: {"native_version": "2.0.0rc7", "available": True},
    )
    monkeypatch.setattr(
        capabilities, "market_data_source_capabilities",
        lambda: {"available": True, "members": []},
    )
    monkeypatch.setattr(
        "server.modules.single_factor_test.process_runners.nautilus_backtest_runner_status",
        lambda: SimpleNamespace(available=False, reason="runner not registered"),
        raising=False,
    )

    result = native_capabilities()
    assert result["backtest_submission"] == {
        "available": False,
        "runner_path": "server.modules.single_factor_test.process_runners:run_group",
        "reason": "runner not registered",
    }
