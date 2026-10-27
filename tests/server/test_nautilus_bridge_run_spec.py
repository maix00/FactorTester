"""The frozen RunSpec follows Nautilus Venue account semantics."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from server.services.nautilus_bridge.config import (
    UnsupportedExecutionConfig,
    compile_frozen_execution_plan,
    freeze_instrument_execution_policy,
)
from server.services.nautilus_bridge.run_spec import freeze_execution_contract
from server.services.nautilus_bridge.native_configuration import native_configuration_schema
from server.services.nautilus_bridge.venues import (
    UnsupportedVenuePlan,
    freeze_native_venues,
)


def _settings(**overrides) -> dict:
    return {
        "data_source_mode": "list", "data_source": ["Local"],
        "freq_mode": "fixed", "freq_fixed": "MIN1",
        "start_date": "2025-04-01", "start_time": "09:00",
        "end_date": "2025-04-02", "end_time": "15:00",
        "time_precision": "exact", "timezone": "Asia/Shanghai",
        "order_type": "market", "matching_model": "auto",
        "liquidity_mode": "infinite", "fee_mode": "zero",
        "slippage_mode": "none", "initial_capital_major": "1000000",
        "base_currency": "CNY", **overrides,
    }


def _backtest(*, venues=None, routes=None, groups=None) -> dict:
    return {
        "groups": groups if groups is not None else [{
            "id": "strategy:a", "name": "A",
            "product_path_selection_id": "scope:a",
        }],
        "venues": venues if venues is not None else [{
            "name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
            "starting_balance": "1000000", "currency": "CNY",
        }],
        "strategy_venue_bindings": routes if routes is not None else [{
            "strategy_id": "strategy:a", "venue_ids": ["CFFEX"],
        }],
    }


def _compile(settings=None, backtest=None, instrument_execution_policy=None) -> dict:
    settings = settings or _settings()
    backtest = backtest or _backtest()
    venue_plan = freeze_native_venues(backtest, settings)
    return freeze_execution_contract(
        settings, product_scope_refs=["scope:a"], native_venue_plan=venue_plan,
        instrument_execution_policy=instrument_execution_policy or freeze_instrument_execution_policy(
            preset="basic",
        ).manifest(),
    )


def _execution_settings(contract: dict) -> dict:
    return contract["settings"]


def test_run_spec_freezes_one_native_account_per_venue_and_one_engine():
    contract = _compile()
    assert contract["blockers"] == []
    settings = _execution_settings(contract)
    venue = settings["venues"][0]
    assert {key: venue[key] for key in (
        "name", "account_type", "oms_type", "starting_balances", "base_currency",
    )} == {
        "name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
        "starting_balances": ["1000000 CNY"], "base_currency": "CNY",
    }
    assert venue["native_config"]["fee_model"] == {"type": "zero"}
    assert venue["native_config"]["book_type"] == "L1_MBP"
    assert settings["account_model"] == "one_account_per_venue"
    assert settings["execution_model"] == "one_backtest_engine_per_run"
    assert settings["shared_market_data"] is True
    assert settings["strategy_venue_bindings"] == [{
        "strategy_id": "strategy:a", "venue_ids": ["CFFEX"],
        "product_scope_refs": ["scope:a"],
    }]
    plan = compile_frozen_execution_plan(
        settings, feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
    )
    assert plan.manifest()["venues"] == settings["venues"]
    assert plan.manifest()["account_model"] == "one_account_per_venue"
    assert "account_hierarchy" not in plan.manifest()


def test_run_spec_projects_native_venue_schema_values_and_adapter_statuses():
    contract = _compile()
    rows = {item["path"]: item for item in contract["fields"]}
    schema = native_configuration_schema()
    venue = _execution_settings(contract)["venues"][0]
    for descriptor in schema["fields"]:
        path = f"venues.CFFEX.native_config.{descriptor['path']}"
        active = all(
            (venue["native_config"].get(condition) in (
                expected if isinstance(expected, list) else [expected]
            ))
            for condition, expected in descriptor.get("visible_if", {}).items()
        )
        if not active:
            assert rows[path]["value"] is None
            continue
        assert rows[path]["value"] is not None or descriptor.get("nullable") is True
        assert rows[path]["status"] == descriptor["status"]
    assert rows["venues.CFFEX.native_config.fee_model.type"]["status"] == "ft_adapter"
    assert venue["native_config"]["fee_model"] == {"type": "zero"}


def test_run_spec_exposes_timing_dmtm_and_position_cost_basis_branches():
    basic = _compile()
    basic_rows = {item["path"]: item for item in basic["fields"]}
    assert basic_rows["execution_timing"]["value"] == "next_bar_open"
    assert basic_rows["execution_timing"]["status"] == "ft_adapter"
    assert basic_rows["instrument_execution_policy.daily_settlement"]["status"] == "not_applicable"
    assert basic_rows[
        "instrument_execution_policy.position_cost_basis.default"
    ]["value"] == "WEIGHTED_AVERAGE"
    assert basic_rows[
        "instrument_execution_policy.position_cost_basis.default"
    ]["status"] == "nt_native"
    assert basic_rows[
        "instrument_execution_policy.position_cost_basis.scope_overrides/instrument_overrides"
    ]["status"] == "nt_native"

    auto_policy = freeze_instrument_execution_policy(preset="auto").manifest()
    automatic = _compile(instrument_execution_policy=auto_policy)
    automatic_rows = {item["path"]: item for item in automatic["fields"]}
    dmtm = automatic_rows["instrument_execution_policy.daily_settlement"]
    assert dmtm["value"]["default"] == "eligible_products"
    assert dmtm["status"] == "unsupported"
    assert any(
        item["path"] == "instrument_execution_policy.daily_settlement"
        for item in automatic["blockers"]
    )


def test_run_spec_freezes_physical_contract_day1_source_adapter():
    contract = _compile(_settings(freq_fixed="DAY1", data_source=["Local"]))
    assert contract["blockers"] == []
    assert contract["settings"]["data_source_ref"] == "LocalCNFuturesContractDAY1"
    assert contract["source_adapter"] == {
        "adapter_id": "local_cnfutures_contract_daily_term_structure_v1",
        "frequency": "DAY1", "feed_kind": "bar",
        "bar_time_semantics": "trading_day_label",
        "clock_policy": "frozen_exchange_session_close_for_trading_day_label",
        "supported_book_types": ["L1_MBP"],
    }
    plan = compile_frozen_execution_plan(
        contract["settings"], feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
    )
    assert plan.data_source_ref == "LocalCNFuturesContractDAY1"


def test_run_spec_rejects_source_frequency_pairing_from_different_adapters():
    contract = _compile(_settings(freq_fixed="DAY1", data_source=["LocalCNFuturesContractMIN1"]))
    assert any(row["path"] == "data_source" for row in contract["blockers"])


def test_run_spec_resolves_an_adapter_declared_by_a_different_source(monkeypatch):
    from server.services.nautilus_bridge import run_spec as run_spec_module
    from server.services.nautilus_bridge.source_registry import NautilusSourceRegistry
    from tools.data.source_catalog import (
        DataSourceMember,
        DataSourceMode,
    )

    from traderesearch_data.nautilus import NautilusAdapterContract

    adapter = NautilusAdapterContract(
        member_key="ExampleRatesContractMIN15",
        adapter_id="example_rates_contract_minute_parquet_v1",
        frequency="MIN15", sampling_mode="bar", data_kind="ohlcv_bar",
        market_depth="not_applicable", delivery_mode="historical_snapshot",
        timezone="UTC", layout="example_parquet", naming_scheme="example_uid_v1",
        required_time_columns=(("time", "MIN15"),),
        required_data_columns=(("open", "OPEN"), ("close", "CLOSE")),
        clock_policy="unix_seconds_interval_end", product_scope="physical_contract_only",
        instrument_scope="physical_contract", bar_time_semantics="interval_end",
        raw_timestamp_unit="s", supported_book_types=("L1_MBP",),
    )
    member = DataSourceMember(
        key=adapter.member_key, label="Example rates 15m",
        supports=lambda _product: True, available=lambda _product: True,
        mode=DataSourceMode(
            key="historical_min15", title_zh="历史15分钟K线",
            sampling_mode="bar", frequency="MIN15", data_kind="ohlcv_bar",
            market_depth="not_applicable", delivery_mode="historical_snapshot",
        ),
        timezone="UTC", time_columns={"time": "MIN15"},
        data_columns={"open": "OPEN", "close": "CLOSE"},
        execution_provider=SimpleNamespace(contract_data_layout="example_parquet"),
        naming_scheme="example_uid_v1", instrument_scope="physical_contract",
        bar_time_semantics="interval_end", raw_timestamp_unit="s",
        nautilus_adapter=adapter,
    )
    registry = NautilusSourceRegistry((SimpleNamespace(key="ExampleRates", members=(member,)),))
    monkeypatch.setattr(run_spec_module, "from_server_sources", lambda: registry)

    contract = _compile(_settings(
        data_source=["ExampleRates"], freq_fixed="MIN15", timezone="UTC",
    ))

    assert not [row for row in contract["blockers"] if row["path"] == "data_source"]
    assert contract["settings"]["data_source_ref"] == "ExampleRatesContractMIN15"
    assert contract["source_adapter"]["adapter_id"] == adapter.adapter_id


def test_bar_source_rejects_venue_book_type_without_source_depth():
    contract = _compile(_settings(), backtest=_backtest(venues=[{
        "name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
        "starting_balance": "1000000", "currency": "CNY",
        "native_config": {"book_type": "L2_MBP"},
    }]))
    assert any(
        row["path"] == "venues.CFFEX.native_config.book_type"
        and "未声明支持 Nautilus BookType L2_MBP" in row["reason"]
        for row in contract["blockers"]
    )


def test_multiple_strategies_can_share_one_venue_and_account():
    backtest = _backtest(groups=[
        {"id": "strategy:a", "product_path_selection_id": "scope:a"},
        {"id": "strategy:b", "product_path_selection_id": "scope:b"},
    ], routes=[
        {"strategy_id": "strategy:a", "venue_ids": ["CFFEX"]},
        {"strategy_id": "strategy:b", "venue_ids": ["cFfEx"]},
    ])
    contract = _compile(backtest=backtest)
    assert contract["blockers"] == []
    assert len(contract["settings"]["venues"]) == 1
    assert [row["strategy_id"] for row in contract["settings"]["strategy_venue_bindings"]] == [
        "strategy:a", "strategy:b",
    ]


def test_strategy_can_route_to_multiple_venues_with_explicit_balances():
    backtest = _backtest(
        venues=[
            {"name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
             "starting_balance": "600000", "currency": "CNY"},
            {"name": "SHFE", "account_type": "MARGIN", "oms_type": "NETTING",
             "starting_balance": "400000", "currency": "CNY"},
        ],
        routes=[{"strategy_id": "strategy:a", "venue_ids": ["CFFEX", "SHFE"]}],
    )
    contract = _compile(backtest=backtest)
    assert contract["blockers"] == []
    assert [row["name"] for row in contract["settings"]["venues"]] == ["CFFEX", "SHFE"]
    plan = compile_frozen_execution_plan(
        contract["settings"], feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
    )
    assert sum(
        float(item.split()[0])
        for venue in plan.venues for item in venue["starting_balances"]
    ) == 1_000_000


def test_run_spec_never_copies_total_capital_to_each_venue_or_implicitly_transfers():
    backtest = _backtest(
        venues=[
            {"name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
             "starting_balance": "600000", "currency": "CNY"},
            {"name": "SHFE", "account_type": "MARGIN", "oms_type": "NETTING",
             "starting_balance": "400000", "currency": "CNY"},
        ],
        routes=[{"strategy_id": "strategy:a", "venue_ids": ["CFFEX", "SHFE"]}],
    )
    frozen = freeze_native_venues(backtest, _settings())
    assert [item["starting_balances"] for item in frozen["venues"]] == [
        ["600000 CNY"], ["400000 CNY"],
    ]
    assert "transfer_policy" not in frozen


def test_venue_plan_rejects_balance_mismatch_and_unconfigured_routes():
    backtest = _backtest(venues=[{
        "name": "CFFEX", "starting_balance": "900000", "currency": "CNY",
    }])
    with pytest.raises(UnsupportedVenuePlan, match="sum to initial_capital_major"):
        freeze_native_venues(backtest, _settings())
    with pytest.raises(UnsupportedVenuePlan, match="unconfigured Venue"):
        freeze_native_venues(
            _backtest(routes=[{"strategy_id": "strategy:a", "venue_ids": ["SHFE"]}]),
            _settings(),
        )


def test_venue_plan_rejects_orphan_strategy_or_unused_venue():
    with pytest.raises(UnsupportedVenuePlan, match="bind every strategy"):
        freeze_native_venues(_backtest(routes=[]), _settings())
    backtest = _backtest(venues=[
        {"name": "CFFEX", "starting_balance": "500000", "currency": "CNY"},
        {"name": "SHFE", "starting_balance": "500000", "currency": "CNY"},
    ])
    with pytest.raises(UnsupportedVenuePlan, match="every configured Venue must be bound"):
        freeze_native_venues(backtest, _settings())


def test_compiler_rejects_legacy_subaccount_tree_as_unknown_settings():
    contract = _compile(_settings(account_hierarchy={"nodes": []}))
    assert any(item["path"] == "account_hierarchy" for item in contract["blockers"])


def test_run_spec_projection_does_not_guess_auto_source_or_auto_frequency():
    contract = _compile(_settings(data_source_mode="auto"))
    assert any(item["path"] == "data_source" for item in contract["blockers"])

    contract = _compile(_settings(freq_mode="auto"))
    assert any(item["path"] == "data_source" for item in contract["blockers"])


def test_run_spec_projection_reports_legacy_fee_slippage_and_matching_gaps():
    contract = _compile(_settings(
        fee_mode="auto", slippage_mode="fixed_bps", slippage_bps=5,
        matching_model="bar_volume_limited",
    ))
    paths = {item["path"] for item in contract["blockers"]}
    assert {
        "venues.native_config.fee_model", "slippage_mode", "matching_model/liquidity_mode",
    } <= paths


def test_run_spec_blocks_unreviewed_authoring_fields():
    contract = _compile(_settings(unreviewed_execution_option={"mode": "fast"}))
    assert any(
        item["path"] == "unreviewed_execution_option"
        and item["status"] == "unsupported"
        for item in contract["fields"]
    )
