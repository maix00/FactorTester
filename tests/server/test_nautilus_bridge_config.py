"""Capacity policy must not silently change execution meaning at cutover."""

from __future__ import annotations

import pytest

from server.services.nautilus_bridge.config import (
    UnsupportedExecutionConfig,
    compile_capacity_plan,
    compile_frozen_execution_plan,
    freeze_instrument_execution_policy,
    parse_frozen_instrument_execution_policy,
    resolve_instrument_execution_settings,
)


@pytest.mark.parametrize("feed", ["bar", "quote", "trade", "l2", "l3"])
def test_legacy_bar_participation_never_maps_to_nt_consumption(feed):
    with pytest.raises(UnsupportedExecutionConfig, match="not equivalent"):
        compile_capacity_plan(
            {"liquidity_mode": "volume_participation", "participation_rate": 0.25},
            feed_kind=feed,
        )


def test_nt_recorded_depth_requires_real_l2_or_l3():
    with pytest.raises(UnsupportedExecutionConfig, match="requires real L2/L3"):
        compile_capacity_plan(
            {"nt_capacity_policy": "recorded_depth"}, feed_kind="bar",
        )
    for feed in ("l2", "l3"):
        plan = compile_capacity_plan(
            {"nt_capacity_policy": "recorded_depth", "nt_matching_policy": "recorded_book",
             "nt_price_protection_points": 4},
            feed_kind=feed,
        )
        assert plan.venue_options() == {
            "liquidity_consumption": True,
            "price_protection_points": 4,
        }
        assert plan.manifest()["feed_kind"] == feed


def test_nt_bar_volume_uses_native_bar_allocation_and_shares_open_capacity():
    plan = compile_capacity_plan(
        {"nt_capacity_policy": "bar_volume", "nt_matching_policy": "bar_volume"},
        feed_kind="bar",
    )
    assert plan.kind == "bar_volume"
    assert plan.venue_options() == {
        "liquidity_consumption": True,
        "price_protection_points": 0,
    }
    assert "native OHLC Bar-volume allocation" in plan.assumptions[0]
    assert "only sees the open-leg allocation" in plan.assumptions[1]


def test_custom_ohlc_volume_split_is_frozen_and_forwarded_to_nautilus():
    plan = compile_capacity_plan(
        {
            "nt_capacity_policy": "bar_volume",
            "nautilus_venue": {
                "bar_volume_weights_bps": [10_000, 0, 0, 0],
                "bar_volume_remainder_to": "close",
            },
        },
        feed_kind="bar",
    )
    assert plan.venue_options() == {
        "liquidity_consumption": True,
        "price_protection_points": 0,
        "bar_volume_weights_bps": [10_000, 0, 0, 0],
        "bar_volume_remainder_to": "close",
    }
    assert plan.manifest()["ohlc_volume_allocation"] == {
        "bar_volume_weights_bps": [10_000, 0, 0, 0],
        "bar_volume_remainder_to": "close",
    }


def test_frozen_runspec_uses_nautilus_venue_parameter_names():
    plan = compile_frozen_execution_plan(
        _minimal_frozen(
            nt_capacity_policy="bar_volume",
            nautilus_venue={
                "bar_volume_weights_bps": [0, 0, 0, 10_000],
                "bar_volume_remainder_to": "open",
            },
        ),
        feed_kind="bar",
        adapter_capabilities=frozenset({
            "native_bar_open_market_orders", "native_bar_volume_consumption", "daily_settlement",
        }),
    )
    manifest = plan.manifest()
    assert manifest["nautilus_venue"] == {
        "bar_volume_weights_bps": [0, 0, 0, 10_000],
        "bar_volume_remainder_to": "open",
    }
    assert manifest["capacity"]["venue_options"]["bar_volume_weights_bps"] == [
        0, 0, 0, 10_000,
    ]


@pytest.mark.parametrize("allocation", [
    {"bar_volume_weights_bps": [25, 25, 25], "bar_volume_remainder_to": "close"},
    {"bar_volume_weights_bps": [2_500, 2_500, 2_500, 2_499], "bar_volume_remainder_to": "close"},
    {"bar_volume_weights_bps": [2_500, 2_500, True, 2_500], "bar_volume_remainder_to": "close"},
    {"bar_volume_weights_bps": [2_500, 2_500, 2_500, 2_500], "bar_volume_remainder_to": "vwap"},
])
def test_custom_ohlc_volume_split_rejects_ambiguous_values(allocation):
    with pytest.raises(UnsupportedExecutionConfig, match="nautilus_venue"):
        compile_capacity_plan(
            {"nt_capacity_policy": "bar_volume", "nautilus_venue": allocation},
            feed_kind="bar",
        )


def test_custom_ohlc_volume_split_requires_bar_volume_policy():
    with pytest.raises(UnsupportedExecutionConfig, match="requires nt_capacity_policy=bar_volume"):
        compile_capacity_plan(
            {"nt_capacity_policy": "unconstrained", "nautilus_venue": {
                "bar_volume_weights_bps": [2_500, 2_500, 2_500, 2_500],
                "bar_volume_remainder_to": "close",
            }},
            feed_kind="bar",
        )


def test_nt_bar_volume_rejects_non_bar_feed_and_legacy_full_fill():
    with pytest.raises(UnsupportedExecutionConfig, match="requires Nautilus OHLC Bar"):
        compile_capacity_plan({"nt_capacity_policy": "bar_volume"}, feed_kind="quote")
    with pytest.raises(UnsupportedExecutionConfig, match="conflicts"):
        compile_capacity_plan(
            {"nt_capacity_policy": "bar_volume", "matching_model": "next_bar_full_fill"},
            feed_kind="bar",
        )


def test_nt_bar_volume_requires_its_native_matching_policy():
    with pytest.raises(UnsupportedExecutionConfig, match="native Bar-volume matching policy"):
        compile_capacity_plan(
            {"nt_capacity_policy": "bar_volume", "nt_matching_policy": "recorded_book"},
            feed_kind="bar",
        )


def test_frozen_bar_volume_requires_verified_adapter_capability():
    settings = _minimal_frozen(nt_capacity_policy="bar_volume")
    base_capabilities = frozenset({"native_bar_open_market_orders", "daily_settlement"})
    with pytest.raises(UnsupportedExecutionConfig, match="Bar-volume allocation"):
        compile_frozen_execution_plan(
            settings, feed_kind="bar", adapter_capabilities=base_capabilities,
        )
    plan = compile_frozen_execution_plan(
        settings, feed_kind="bar",
        adapter_capabilities=base_capabilities | {"native_bar_volume_consumption"},
    )
    assert plan.capacity.kind == "bar_volume"


def test_old_full_fill_cannot_be_mislabeled_as_depth_partial_fill():
    with pytest.raises(UnsupportedExecutionConfig, match="conflicts"):
        compile_capacity_plan(
            {"matching_model": "next_bar_full_fill", "nt_capacity_policy": "recorded_depth"},
            feed_kind="l2",
        )


def test_legacy_auto_cannot_silently_become_depth_matching():
    with pytest.raises(UnsupportedExecutionConfig, match="legacy auto means next-bar full fill"):
        compile_capacity_plan(
            {"matching_model": "auto", "nt_capacity_policy": "recorded_depth"}, feed_kind="l2",
        )


def test_unconstrained_bar_policy_has_no_fake_capacity_limit():
    plan = compile_capacity_plan(
        {"matching_model": "auto", "liquidity_mode": "infinite"}, feed_kind="bar",
    )
    assert plan.venue_options() == {
        "liquidity_consumption": False,
        "price_protection_points": 0,
    }
    assert "No participation cap" in plan.assumptions[0]


@pytest.mark.parametrize("value", [0, -0.1, 1.1, float("nan"), float("inf"), True, "nope"])
def test_invalid_legacy_participation_is_rejected(value):
    with pytest.raises(UnsupportedExecutionConfig, match="participation_rate"):
        compile_capacity_plan(
            {"liquidity_mode": "volume_participation", "participation_rate": value},
            feed_kind="bar",
        )


@pytest.mark.parametrize("value", [-1, 1.5, True, "oops"])
def test_invalid_price_protection_is_rejected(value):
    with pytest.raises(UnsupportedExecutionConfig, match="nt_price_protection_points"):
        compile_capacity_plan(
            {"nt_capacity_policy": "recorded_depth", "nt_matching_policy": "recorded_book",
             "nt_price_protection_points": value},
            feed_kind="l2",
        )


def _policy(**overrides):
    return freeze_instrument_execution_policy(
        preset=overrides.pop("preset", "auto"),
        settlement_rule_set_ref=overrides.pop(
            "settlement_rule_set_ref", "ExchangeRules:CFFEX@sha256:abc",
        ),
        **overrides,
    ).manifest()


def _minimal_frozen(**overrides):
    return {
        "data_source_ref": "LocalCNFuturesMIN1@revision-1",
        "source_version": "sha256:abc",
        "product_scope_refs": ["product-group:treasuries"],
        "instrument_execution_policy": _policy(),
        "start_utc": "2025-04-01T01:00:00Z",
        "end_utc": "2025-05-01T07:15:00Z",
        "bar_end_timestamps": True,
        "execution_price_basis": "open",
        "execution_timing": "next_bar_open",
        "fee_mode": "zero",
        "initial_capital_major": "1000000",
        "base_currency": "CNY",
        "account_model": "one_account_per_venue",
        "execution_model": "one_backtest_engine_per_run",
        "shared_market_data": True,
        "venues": [{
            "name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
            "starting_balances": ["1000000 CNY"], "base_currency": "CNY",
        }],
        "strategy_venue_bindings": [{
            "strategy_id": "strategy:treasuries", "venue_ids": ["CFFEX"],
            "product_scope_refs": ["product-group:treasuries"],
        }],
        **overrides,
    }


def test_frozen_plan_records_data_and_execution_assumptions():
    plan = compile_frozen_execution_plan(
        _minimal_frozen(fee_mode="per_contract", fee_per_contract="3.5", fee_currency="CNY"),
        feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
    )
    manifest = plan.manifest()
    assert manifest["start_utc"] == "2025-04-01T01:00:00+00:00"
    assert manifest["source_versioned"] is True
    assert manifest["fee"] == {
        "mode": "per_venue", "venue_models": {"CFFEX": "per_contract"},
    }
    assert manifest["venues"][0]["native_config"]["fee_model"] == {
        "type": "per_contract", "commission": "3.5 CNY",
    }
    assert manifest["capacity"]["venue_options"]["liquidity_consumption"] is False
    assert manifest["nautilus_venue"] == {
        "bar_volume_weights_bps": None,
        "bar_volume_remainder_to": "close",
    }
    assert manifest["timing"] == "next_bar_open"
    assert manifest["account_model"] == "one_account_per_venue"
    assert manifest["execution_model"] == "one_backtest_engine_per_run"
    assert manifest["shared_market_data"] is True
    assert manifest["venues"][0]["starting_balances"] == ["1000000 CNY"]
    assert "open_proxy" not in manifest
    assert manifest["daily_settlement"]["policy"] == "eligible_products"
    assert manifest["daily_settlement"]["eligibility_source"] == "immutable_rule_set"
    policy = manifest["instrument_execution_policy"]
    assert policy["settlement_rule_set_ref"] == "ExchangeRules:CFFEX@sha256:abc"
    assert policy["position_cost_basis"]["default"] == "WEIGHTED_AVERAGE"
    assert "instrument_ids" not in manifest


def test_native_venue_accounts_split_run_capital_explicitly():
    plan = compile_frozen_execution_plan(
        _minimal_frozen(
            venues=[
                {"name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
                 "starting_balances": ["700000 CNY"], "base_currency": "CNY"},
                {"name": "SHFE", "account_type": "MARGIN", "oms_type": "NETTING",
                 "starting_balances": ["300000 CNY"], "base_currency": "CNY"},
            ],
            strategy_venue_bindings=[{
                "strategy_id": "strategy:treasuries", "venue_ids": ["CFFEX", "SHFE"],
                "product_scope_refs": ["product-group:treasuries"],
            }],
            instrument_execution_policy=_policy(preset="basic"),
        ),
        feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
    )
    assert [row["starting_balances"] for row in plan.venues] == [
        ["700000 CNY"], ["300000 CNY"],
    ]


@pytest.mark.parametrize("venue_funding, error", [
    ([{"venue_id": "CFFEX", "starting_balance": "999999", "currency": "CNY"}], "sum"),
    ([{"venue_id": "CFFEX", "starting_balance": "1000000", "currency": "USD"}], "cross-currency"),
    ([{"venue_id": "CFFEX", "starting_balance": "1000000", "currency": "CNY"},
      {"venue_id": "cffex", "starting_balance": "1", "currency": "CNY"}], "duplicate"),
])
def test_invalid_frozen_venue_balances_are_rejected(venue_funding, error):
    with pytest.raises(UnsupportedExecutionConfig, match=error):
        compile_frozen_execution_plan(
            _minimal_frozen(
                venues=[{
                    "name": "CFFEX", "account_type": "MARGIN", "oms_type": "NETTING",
                    "base_currency": "CNY", "starting_balances": [
                        f"{row['starting_balance']} {row['currency']}" for row in venue_funding
                    ],
                }],
                instrument_execution_policy=_policy(preset="basic"),
            ),
            feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("cost_basis_method", "WeightAverage", "WEIGHTED_AVERAGE"),
    ("cost_basis_method", "FIFO", "FIFO"),
    ("cost_basis_method", "LIFO", "LIFO"),
    ("cost_basis_method", "HIFO", "HIFO"),
    ("position_cost_basis", "WEIGHTED_AVERAGE", "WEIGHTED_AVERAGE"),
])
def test_frozen_plan_maps_registered_cost_basis_to_nautilus_enum(field, value, expected):
    policy = _policy(
        preset="custom", daily_settlement_default="disabled",
        cost_basis_default=value,
    )
    plan = compile_frozen_execution_plan(
        _minimal_frozen(instrument_execution_policy=policy), feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
    )

    result = plan.instrument_execution_policy.resolve_for_instrument(
        "T2506.CFFEX", product_scope_refs=("product-group:treasuries",),
        daily_settlement_eligible=False,
    )
    assert result["position_cost_basis"] == expected


def test_auto_uses_compact_default_and_custom_supports_sparse_exceptions():
    auto = freeze_instrument_execution_policy(
        preset="auto", settlement_rule_set_ref="ExchangeRules:CFFEX@sha256:abc",
    )
    custom = freeze_instrument_execution_policy(
        preset="custom", settlement_rule_set_ref="ExchangeRules:CFFEX@sha256:abc",
        cost_basis_instrument_overrides={"T2506.CFFEX": "FIFO"},
        daily_settlement_instrument_overrides={"T2506.CFFEX": False},
    )
    assert auto.daily_settlement_default == "eligible_products"
    assert auto.cost_basis_default == "WEIGHTED_AVERAGE"
    assert custom.cost_basis_instrument_overrides == (("T2506.CFFEX", "FIFO"),)
    assert custom.daily_settlement_instrument_overrides == (("T2506.CFFEX", False),)


def test_conflicting_cost_basis_settings_are_rejected():
    with pytest.raises(UnsupportedExecutionConfig, match="unmapped execution fields"):
        compile_frozen_execution_plan(
            _minimal_frozen(cost_basis_method="FIFO"),
            feed_kind="bar",
            adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
        )


def test_native_venue_account_and_strategy_routes_are_required():
    settings = _minimal_frozen()
    settings.pop("venues")
    with pytest.raises(UnsupportedExecutionConfig, match="venues"):
        compile_frozen_execution_plan(
            settings, feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
        )


def test_next_bar_open_is_not_claimed_without_native_matching_support():
    with pytest.raises(UnsupportedExecutionConfig, match="pinned Nautilus matching engine"):
        compile_frozen_execution_plan(_minimal_frozen(), feed_kind="bar")


def test_next_bar_open_requires_ohlc_bars():
    with pytest.raises(UnsupportedExecutionConfig, match="requires native OHLC Bar"):
        compile_frozen_execution_plan(
            _minimal_frozen(), feed_kind="quote",
            adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )


@pytest.mark.parametrize("field,value", [
    ("start_utc", "2025-04-01"),
    ("bar_end_timestamps", False),
    ("product_scope_refs", []),
    ("fee_mode", "auto"),
    ("strategy_book_mode", "independent"),
])
def test_frozen_plan_rejects_ambiguous_legacy_contract(field, value):
    with pytest.raises(UnsupportedExecutionConfig, match=field):
        compile_frozen_execution_plan(
            _minimal_frozen(**{field: value}), feed_kind="bar",
            adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
        )


def test_historical_fee_requires_adapter():
    with pytest.raises(UnsupportedExecutionConfig, match="effective-time adapter"):
        compile_frozen_execution_plan(
            _minimal_frozen(fee_mode="historical_schedule", fee_schedule_ref="fees@v1"),
            feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )


@pytest.mark.parametrize("mode", ["auto", "custom"])
def test_daily_settlement_defaults_on_for_eligible_products_in_auto_and_custom(mode):
    policy = _policy(preset=mode)
    plan = compile_frozen_execution_plan(
        _minimal_frozen(instrument_execution_policy=policy), feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
    )
    assert plan.instrument_execution_policy.daily_settlement_default == "eligible_products"


def test_runspec_can_disable_daily_settlement_or_enable_only_exchange_eligible_products():
    disabled_policy = _policy(preset="custom", daily_settlement_default="disabled")
    enabled_policy = _policy(preset="custom", daily_settlement_default="eligible_products")
    disabled = compile_frozen_execution_plan(
        _minimal_frozen(instrument_execution_policy=disabled_policy),
        feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
    )
    enabled = compile_frozen_execution_plan(
        _minimal_frozen(instrument_execution_policy=enabled_policy),
        feed_kind="bar",
        adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
    )
    assert disabled.instrument_execution_policy.daily_settlement_default == "disabled"
    assert enabled.instrument_execution_policy.daily_settlement_default == "eligible_products"


def test_daily_settlement_auto_requires_the_optional_nautilus_event_adapter():
    with pytest.raises(UnsupportedExecutionConfig, match="eligible-product DMTM is frozen"):
        compile_frozen_execution_plan(
            _minimal_frozen(), feed_kind="bar",
            adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )


def test_daily_settlement_requires_a_registered_versioned_rule_source():
    policy = freeze_instrument_execution_policy(preset="auto")
    with pytest.raises(UnsupportedExecutionConfig, match="no versioned exchange settlement-rule source"):
        compile_frozen_execution_plan(
            _minimal_frozen(instrument_execution_policy=policy.manifest()),
            feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders", "daily_settlement"}),
        )


def test_basic_preset_freezes_dmtm_off_and_rejects_overrides():
    policy = freeze_instrument_execution_policy(preset="basic")
    assert policy.daily_settlement_default == "disabled"
    assert policy.cost_basis_default == "WEIGHTED_AVERAGE"
    with pytest.raises(UnsupportedExecutionConfig, match="Basic fixes DMTM off"):
        freeze_instrument_execution_policy(
            preset="basic", daily_settlement_instrument_overrides={"T2506.CFFEX": True},
        )


def test_run_policy_stays_compact_and_expands_mixed_settings_only_at_runtime():
    policy = freeze_instrument_execution_policy(
        preset="custom", settlement_rule_set_ref="ExchangeRules:CFFEX@sha256:abc",
        daily_settlement_scope_overrides={"product-group:treasuries": True},
        daily_settlement_instrument_overrides={"T2506.CFFEX": False},
        cost_basis_scope_overrides={"product-group:treasuries": "FIFO"},
        cost_basis_instrument_overrides={"TL2506.CFFEX": "HIFO"},
    )
    restored = parse_frozen_instrument_execution_policy(policy.manifest())
    assert restored.manifest() == policy.manifest()
    runtime = resolve_instrument_execution_settings(
        restored,
        product_scopes_by_instrument={
            "T2506.CFFEX": ("product-group:treasuries",),
            "TL2506.CFFEX": ("product-group:treasuries",),
            "AU2612.SHFE": (),
            "000001.SZSE": ("product-group:china-stocks",),
        },
        daily_settlement_eligibility={
            "T2506.CFFEX": True, "TL2506.CFFEX": True,
            "AU2612.SHFE": False, "000001.SZSE": False,
        },
    )
    assert runtime["daily_settlement_instrument_ids"] == ["TL2506.CFFEX"]
    assert runtime["position_cost_basis_by_instrument"] == {
        "T2506.CFFEX": "FIFO", "TL2506.CFFEX": "HIFO",
    }
    assert runtime["resolved_instrument_count"] == 4
    assert "resolved_instruments" not in runtime
    # RunSpec carries only the explicitly selected exceptions; it does not
    # expand the default/group rules into a row for every resolved contract.
    assert policy.manifest()["daily_settlement"]["instrument_overrides"] == {
        "T2506.CFFEX": False,
    }
    assert policy.manifest()["position_cost_basis"]["instrument_overrides"] == {
        "TL2506.CFFEX": "HIFO",
    }
    assert len(policy.manifest()["position_cost_basis"]["instrument_overrides"]) == 1


def test_conflicting_overlapping_scope_overrides_require_instrument_exception():
    policy = freeze_instrument_execution_policy(
        preset="custom", daily_settlement_default="disabled",
        settlement_rule_set_ref="ExchangeRules:CFFEX@sha256:abc",
        daily_settlement_scope_overrides={"scope:a": True, "scope:b": False},
        cost_basis_scope_overrides={"scope:a": "FIFO", "scope:b": "LIFO"},
    )
    with pytest.raises(UnsupportedExecutionConfig, match="overlapping product scopes conflict"):
        policy.resolve_for_instrument(
            "T2506.CFFEX", product_scope_refs=("scope:a", "scope:b"),
            daily_settlement_eligible=True,
        )


def test_unmapped_legacy_effects_are_rejected_instead_of_dropped():
    with pytest.raises(UnsupportedExecutionConfig, match="fee_custom_product_fields"):
        compile_frozen_execution_plan(
            _minimal_frozen(fee_custom_product_fields={"CloseTodayRatioByVolume": 3}),
            feed_kind="bar", adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
        )
