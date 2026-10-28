"""NT admission follows source-owned declarations without inventing data sources."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from sources.LocalCNFutures.nautilus_adapter import CONTRACT_DAY1, CONTRACT_MIN1
from server.services.nautilus_bridge.source_registry import (
    NautilusSourceRegistry,
    UnsupportedNautilusSource,
    from_server_sources,
)


class FakeMember:
    def __init__(self, *, key="LocalCNFuturesContractMIN1", available=True):
        self.key = key
        self.frequency = "MIN1"
        self.timezone = "Asia/Shanghai"
        self.naming_scheme = CONTRACT_MIN1.naming_scheme
        self.time_columns = {"trade_time": "MIN1", "trading_day": "DAY1"}
        self.data_columns = dict(CONTRACT_MIN1.required_data_columns)
        self.execution_provider = SimpleNamespace(contract_data_layout="parquet_ohlcv")
        self.nautilus_adapter = (
            CONTRACT_MIN1 if key == CONTRACT_MIN1.member_key else None
        )
        self.instrument_scope = "physical_contract"
        self.bar_time_semantics = "interval_end"
        self.raw_timestamp_unit = "ms"
        self.mode = SimpleNamespace(as_dict=lambda: {
            "sampling_mode": "bar", "data_kind": "ohlcv_bar",
            "market_depth": "not_applicable", "delivery_mode": "historical_snapshot",
            "available": True,
        })
        self.available = available
        self.probes = 0

    def supports_product(self, product):
        self.probes += 1
        return getattr(product, "kind", "") == "contract"

    def has_available_data(self, product):
        self.probes += 1
        return self.available


class FakeDailyMember(FakeMember):
    def __init__(self, *, available=True):
        super().__init__(key=CONTRACT_DAY1.member_key, available=available)
        self.frequency = "DAY1"
        self.naming_scheme = CONTRACT_DAY1.naming_scheme
        self.time_columns = dict(CONTRACT_DAY1.required_time_columns)
        self.data_columns = dict(CONTRACT_DAY1.required_data_columns)
        self.execution_provider = SimpleNamespace(contract_data_layout="term_structure_snapshot")
        self.bar_time_semantics = "trading_day_label"
        self.raw_timestamp_unit = "date_label"
        self.nautilus_adapter = CONTRACT_DAY1


def _registry(*members, adapters=()):
    declaration = SimpleNamespace(key="Local", members=members)
    return NautilusSourceRegistry((declaration,), adapters)


def test_discovery_does_not_probe_files_and_unknown_feed_fails_closed():
    known = FakeMember()
    future = FakeMember(key="NewSourceSECOND5")
    registry = _registry(known, future)
    assert {row.member_key for row in registry.capabilities()} == {
        known.key, future.key,
    }
    assert known.probes == future.probes == 0
    assert registry.capabilities()[0].adapter_id == CONTRACT_MIN1.adapter_id
    assert registry.capabilities()[1].adapter_id is None
    with pytest.raises(UnsupportedNautilusSource, match="no verified"):
        registry.resolve(future.key, frequency="MIN1", product=SimpleNamespace(kind="contract"))
    assert future.probes == 0


def test_exact_declared_source_frequency_and_available_contract_are_required():
    member = FakeMember()
    registry = _registry(member)
    product = SimpleNamespace(kind="contract")
    resolved = registry.resolve(member.key, frequency="MIN1", product=product)
    assert resolved.execution_provider is member.execution_provider
    assert resolved.member is member
    assert resolved.adapter.clock_policy == CONTRACT_MIN1.clock_policy
    with pytest.raises(UnsupportedNautilusSource, match="declared MIN1"):
        registry.resolve(member.key, frequency="DAY1", product=product)
    with pytest.raises(UnsupportedNautilusSource, match="outside source catalog"):
        registry.resolve(member.key, frequency="MIN1", product=SimpleNamespace(kind="continuous"))
    with pytest.raises(UnsupportedNautilusSource, match="unavailable"):
        _registry(FakeMember(available=False)).resolve(
            member.key, frequency="MIN1", product=product,
        )
    with pytest.raises(UnsupportedNautilusSource, match="unknown server source"):
        registry.resolve("LocalCNFuturesDAY1", frequency="DAY1", product=product)


def test_daily_term_structure_adapter_requires_calendar_label_contract():
    member = FakeDailyMember()
    registry = _registry(member)
    product = SimpleNamespace(kind="contract")
    resolved = registry.resolve(member.key, frequency="DAY1", product=product)
    assert resolved.adapter.adapter_id == CONTRACT_DAY1.adapter_id
    assert resolved.adapter.clock_policy == CONTRACT_DAY1.clock_policy
    assert registry.capabilities()[0].raw_timestamp_unit == "date_label"
    member.raw_timestamp_unit = "ms"
    with pytest.raises(UnsupportedNautilusSource, match="differs from source declaration"):
        _registry(member).resolve(
            member.key, frequency="DAY1", product=product,
        )


@pytest.mark.parametrize("drift", [
    {"timezone": "UTC"},
    {"naming_scheme": "changed"},
    {"frequency": "MIN5"},
    {"time_columns": {"trade_time": "MIN1"}},
    {"data_columns": {"open_price": "OPEN"}},
    {"execution_provider": SimpleNamespace(contract_data_layout="unknown")},
    {"instrument_scope": "continuous_signal"},
    {"bar_time_semantics": "bar_start"},
    {"raw_timestamp_unit": "s"},
])
def test_source_semantic_drift_revokes_adapter(drift):
    member = FakeMember()
    for name, value in drift.items():
        setattr(member, name, value)
    registry = _registry(member)
    capability, = registry.capabilities()
    assert capability.adapter_id is None
    assert capability.reason == "adapter contract differs from source declaration"
    with pytest.raises(UnsupportedNautilusSource):
        registry.resolve(member.key, frequency=member.frequency,
                         product=SimpleNamespace(kind="contract"))


def test_duplicate_and_orphan_bindings_are_rejected():
    with pytest.raises(ValueError, match="duplicate or empty source member"):
        _registry(FakeMember(), FakeMember())
    with pytest.raises(ValueError, match="duplicate or empty adapter key"):
        _registry(FakeMember(), adapters=(CONTRACT_MIN1, CONTRACT_MIN1))
    with pytest.raises(ValueError, match="no declared source"):
        _registry(FakeMember(), adapters=(
            CONTRACT_MIN1,
            replace(CONTRACT_MIN1, member_key="NoSuchSource"),
        ))


def test_declared_mode_unavailable_cannot_stage_even_with_an_adapter():
    member = FakeMember()
    member.mode = SimpleNamespace(as_dict=lambda: {
        "sampling_mode": "bar", "data_kind": "ohlcv_bar",
        "market_depth": "not_applicable", "delivery_mode": "historical_snapshot",
        "available": False,
    })
    registry = _registry(member)
    assert registry.capabilities()[0].adapter_id is None
    with pytest.raises(UnsupportedNautilusSource, match="differs from source declaration"):
        registry.resolve(member.key, frequency="MIN1", product=SimpleNamespace(kind="contract"))


def test_runtime_projection_discovers_a_new_source_without_a_hardcoded_list(monkeypatch):
    from sources import registry as source_registry
    from tools.data import source_catalog

    new_member = FakeMember(key="UserProvidedMIN1")
    new_member.naming_scheme = "user_source_v1"
    loaded = []
    monkeypatch.setattr(source_registry, "load_all_sources", lambda: loaded.append(True))
    monkeypatch.setattr(source_catalog, "data_source_declarations", lambda: (
        SimpleNamespace(key="UserProvided", members=(new_member,)),
    ))
    registry = from_server_sources()
    assert loaded == [True]
    assert registry.capabilities()[0].member_key == "UserProvidedMIN1"
    assert registry.capabilities()[0].adapter_id is None
