"""Source-owned China futures meanings are visible without contract enumeration."""

from __future__ import annotations

from types import SimpleNamespace

from sources.registry import load_all_sources
from tools.data.source_catalog import data_source_declarations


def _members():
    load_all_sources()
    return {
        member.key: member
        for declaration in data_source_declarations()
        for member in declaration.members
    }


def test_all_four_local_futures_feeds_are_declared_without_contract_listing(monkeypatch):
    from sources.LocalCNFutures import CNFutures as source

    original_listdir = source.os.listdir

    def fail_contract_listing(path):
        if str(path).endswith("data_mink_product"):
            raise AssertionError("source declaration enumerated contract files")
        return original_listdir(path)

    monkeypatch.setattr(source.os, "listdir", fail_contract_listing)
    members = _members()
    assert {
        "LocalCNFuturesMIN1", "LocalCNFuturesDAY1",
        "LocalCNFuturesContractMIN1", "LocalCNFuturesContractDAY1",
    }.issubset(members)
    assert members["LocalCNFuturesMIN1"].instrument_scope == "continuous_signal"
    assert members["LocalCNFuturesContractMIN1"].instrument_scope == "physical_contract"
    assert members["LocalCNFuturesMIN1"].bar_time_semantics == "interval_end"
    assert members["LocalCNFuturesContractDAY1"].bar_time_semantics == "trading_day_label"
    assert all(members[key].raw_timestamp_unit == "ms" for key in (
        "LocalCNFuturesMIN1", "LocalCNFuturesContractMIN1",
    ))
    assert all(members[key].raw_timestamp_unit == "date_label" for key in (
        "LocalCNFuturesDAY1", "LocalCNFuturesContractDAY1",
    ))
    assert members["LocalCNFuturesContractDAY1"].data_columns[
        "SETTLEMENT_PRICE"
    ] == "SETTLEMENT_PRICE"


def test_asset_class_is_source_owned_and_unknowns_fail_closed():
    members = _members()
    for member in members.values():
        assert member.asset_class_for_product(SimpleNamespace(name="T.CFE")) == "DEBT"
        assert member.asset_class_for_product(SimpleNamespace(name="CFFEX|F|TL|2506")) == "DEBT"
        assert member.asset_class_for_product(SimpleNamespace(name="IF.CFE")) == "EQUITY"
        assert member.asset_class_for_product(SimpleNamespace(name="AU.SHF")) == "COMMODITY"
        assert member.asset_class_for_product(SimpleNamespace(name="SHFE|F|AU|2510")) == "COMMODITY"
        assert member.asset_class_for_product(SimpleNamespace(name="UNKNOWN.CFE")) is None
        assert member.asset_class_for_product(SimpleNamespace(name="UNKNOWN.XYZ")) is None


def test_registered_contract_day1_feed_has_a_verified_adapter_without_file_probes():
    from server.services.nautilus_bridge.source_registry import from_server_sources

    registry = from_server_sources()
    capabilities = {row.member_key: row for row in registry.capabilities()}
    daily = capabilities["LocalCNFuturesContractDAY1"]
    assert daily.adapter_id == "local_cnfutures_contract_daily_term_structure_v1"
    assert daily.raw_timestamp_unit == "date_label"
    assert daily.reason == ""


def test_field_history_is_lazy_strict_historical_and_preserves_raw_mapping(monkeypatch):
    from tools.data import field_history

    member = _members()["LocalCNFuturesContractMIN1"]
    assert member.trading_field_provider_ref == "FieldHistory:market_rules:exchange"
    assert member.trading_field_effective_clock == "effective_timestamp_or_trading_day"
    assert member.time_columns["trade_time"] == "MIN1"
    assert member.data_columns["trade_timestamp"] == "TIMESTAMP"
    calls = []
    sentinel = object()
    monkeypatch.setattr(field_history, "load_market_rule_field_provider", lambda **kwargs: (
        calls.append(kwargs), sentinel,
    )[-1])
    assert member.load_trading_field_provider() is sentinel
    assert calls == [{
        "include_openctp_latest": False, "transaction_fee_source": "exchange",
    }]


def test_new_server_source_is_projected_without_special_casing(monkeypatch):
    from tools.data.source_catalog import (
        DataSourceDeclaration,
        DataSourceMember,
        DataSourceMode,
        register_data_source,
    )

    member = DataSourceMember(
        key="SyntheticQUOTE", label="Synthetic quote",
        supports=lambda product: True, available=lambda product: False,
        mode=DataSourceMode(
            key="quote", title_zh="行情报价", sampling_mode="event",
            frequency=None, data_kind="quote", market_depth="l1",
            delivery_mode="historical_snapshot",
        ),
    )
    declaration = DataSourceDeclaration(
        key="SyntheticForTest", label="Synthetic", provider_kind="test",
        member_loader=lambda: (member,),
    )
    register_data_source(declaration)
    try:
        assert "SyntheticQUOTE" in _members()
    finally:
        # Existing registry has no unregister API; restore only this test key.
        from tools.data import source_catalog
        source_catalog._DECLARATIONS.pop("SyntheticForTest", None)
