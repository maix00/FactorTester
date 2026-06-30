from __future__ import annotations

import pytest
from flask import Flask
import pandas as pd

from server.modules.single_factor_test import sft_bp
from tools.testers.settings import backtest_setting_registry, resolve_group_settings
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES


def test_setting_manifest_loads_tabs_before_tab_controls() -> None:
    application = backtest_setting_registry.get("group_test")

    index = application.manifest()
    engine_tab = application.tab_manifest("engine")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "engine", "factor", "product_path_selection", "data_source", "frequency",
        "time", "capital", "target_allocation", "rebalance_trigger",
        "position_policy", "cost", "order", "liquidity", "margin",
        "market_rules", "accounting", "calendar", "evaluation",
    ]
    assert index["default_mounted_tabs"] == {
        "local-settings": ["engine"],
        "group-settings": [],
    }
    assert [tab["key"] for tab in index["tab_lists"]["group-settings"]] == [
        "factor", "product_path_selection", "data_source", "frequency", "time",
        "capital", "target_allocation", "rebalance_trigger", "position_policy",
        "group_strategy", "cost", "order", "liquidity", "margin",
        "market_rules", "accounting", "calendar", "evaluation",
    ]
    assert index["defaults"]["engine"]["value"] == "native"
    assert index["defaults"]["engine"]["tab_key"] == "engine"
    assert index["defaults"]["engine"]["scope_policy"] == "local_only"
    assert index["defaults"]["engine"]["chip_template"] == "引擎: {value}"
    assert index["defaults"]["start_date"]["scope_policy"] == "overridable"
    assert index["defaults"]["engine"]["options"][0] == {
        "value": "native",
        "label": "Native 事件驱动回测工具",
    }
    assert index["defaults"]["order_type"]["value"] == "market"
    assert index["defaults"]["matching_model"]["value"] == "next_bar_full_fill"
    assert index["defaults"]["quantity_rounding_policy"]["value"] == "floor_to_lot"
    assert index["defaults"]["volatility_lookback"]["visible_when"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["volatility_warmup"]["visible_when"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["engine_mode"]["value"] == "auto"
    assert index["defaults"]["engine_mode"]["scope_policy"] == "overridable"
    assert index["defaults"]["fee_mode"]["editable_when"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["fee_mode"]["default_when"] == {
        "engine_mode": {"basic": "zero", "auto": "auto", "exact": "exact"},
    }
    assert index["defaults"]["fixed_fee_rate"]["visible_when"] == {
        "fee_mode": ["fixed"],
    }
    assert index["defaults"]["slippage_bps"]["visible_when"] == {
        "slippage_mode": ["fixed_bps"],
    }
    assert index["defaults"]["participation_rate"]["visible_when"] == {
        "liquidity_mode": ["volume_participation"],
    }
    assert index["defaults"]["collateral_fraction"]["visible_when"] == {
        "margin_mode": ["fixed", "auto", "exact", "custom"],
    }
    assert index["defaults"]["margin_mode"]["value"] == "auto"
    assert index["defaults"]["margin_mode"]["editable_when"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["margin_mode"]["default_when"] == {
        "engine_mode": {"basic": "none", "auto": "auto", "exact": "exact"},
    }
    assert index["defaults"]["accounting_mode"]["editable_when"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["custom_product_fields"]["label"] == "自定义字段"
    assert index["defaults"]["custom_product_fields"]["visible_when"] == {}
    assert index["defaults"]["custom_product_fields"]["editable_when"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["custom_product_fields"]["serialization"]["kind"] == "custom_product_overrides"
    # money_unit_policy (with per-engine override: rqalpha forces
    # "engine_native", disabling "minor_units") was an execution-engine
    # dispatch concern spanning native/backtrader/qlib/rqalpha -- replaced
    # by MinorUnitModule.use_minor_units, a plain boolean scoped to the
    # native engine only (other engines' money-precision handling is their
    # own concern, not modeled here).
    assert index["defaults"]["use_minor_units"]["value"] is True
    assert all(item.get("module") for item in index["defaults"].values())
    assert all(chip.get("module") for chip in index["chip_fields"])
    assert {
        chip["module"] for chip in index["chip_fields"]
    } >= {"factor_execution", "product_selection", "group_strategy"}
    assert {chip["key"] for chip in index["chip_fields"]} >= {
        "factor_alias",
        "product_path_selection",
        "group_index",
        "product_mask",
    }
    assert [setting["key"] for setting in engine_tab["settings"]] == [
        "engine", "engine_mode",
    ]
    executable_public_fields = {
        key
        for cls in _ALL_MODULE_CLASSES
        for key, field in getattr(cls, "fields", {}).items()
        if field.public
    }
    assert set(index["defaults"]) <= executable_public_fields
    assert index["defaults"]["calendar_frequency"]["module"] == "factor_execution"
    assert index["defaults"]["evaluation_split"]["module"] == "run_window"
    assert {
        key: index["defaults"][key]["module"]
        for key in ("execution_price_basis", "order_type", "matching_model")
    } == {
        "execution_price_basis": "order_execution",
        "order_type": "order_execution",
        "matching_model": "order_execution",
    }


def test_ic_setting_manifest_is_registered_and_lazy_loaded() -> None:
    application = backtest_setting_registry.get("ic_test")

    index = application.manifest()
    time_tab = application.tab_manifest("time")
    product_tab = application.tab_manifest("product_path_selection")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "factor", "category", "product_path_selection", "time", "data_source", "frequency",
        "return_frequency", "delay", "ic_method", "cross_section", "summary",
    ]
    assert index["default_mounted_tabs"] == {
        "local-settings": [],
        "group-settings": [],
    }
    assert index["defaults"]["product_path_selections"]["module"] == "product_selection"
    assert index["defaults"]["return_frequency_mode"]["module"] == "return_frequency"
    assert index["defaults"]["return_price_basis"]["value"] == "next_open_to_open_adjusted"
    assert index["defaults"]["ic_lag"]["tab_key"] == "delay"
    assert index["defaults"]["ic_correlation"]["value"] == "rank"
    assert index["defaults"]["group_adjust"]["value"] == "off"
    assert index["defaults"]["by_group"]["value"] == "off"
    assert index["defaults"]["start_time"]["visible_when"] == {
        "time_precision": ["exact"],
    }
    assert {chip["key"] for chip in index["chip_fields"]} >= {
        "factor_alias",
        "product_path_selection",
    }
    assert [tab["key"] for tab in index["result_tabs"]][:3] == [
        "cross_sectional_rank_ic",
        "cross_sectional_pearson_ic",
        "ic_summary",
    ]
    assert index["result_tabs"][0]["default"] is True
    assert index["result_tabs"][0]["requires"] == {"ic_correlation": ["rank", "both"]}
    assert [setting["key"] for setting in product_tab["settings"]] == [
        "product_path_candidates", "product_path_selections",
    ]
    assert [setting["key"] for setting in time_tab["settings"]] == [
        "start_date", "end_date", "start_time", "end_time", "time_precision", "timezone",
    ]


def test_ic_prepare_uses_registered_settings_for_both_methods() -> None:
    from server.modules.single_factor_test.ic import _parse_ic_params, _prepare_ic_compute
    from tools.factors.Parameters import FactorNextPeriodReturns

    class FakeFreq:
        name = "1min"
        value = "1min"

        def is_day_multiple(self):
            return False

    class FakeFactor:
        alias = "F1"
        name = "F1"
        freq = FakeFreq()

        def _structural_key(self):
            return ("fake-factor", self.alias)

    class FakeFamily:
        def __init__(self, factor):
            self.factor = factor

        def get_factor_by_alias(self, alias):
            return self.factor if alias == self.factor.alias else None

    class FakeTester:
        products = ["RB.SHF", "HC.SHF"]

    data = {
        "product_path_selection": {
            "product_path_selection_id": "manual-black",
            "paths": ["Product/Futures/CNFutures/黑色/RB.SHF"],
        },
        "factor_family_alias": "Family",
        "factors": [{"alias": "F1", "return_freq": ""}],
        "settings": {
            "ic_correlation": "both",
            "return_price_basis": "next_close_to_close_adjusted",
        },
    }

    parsed = _parse_ic_params(data)
    assert parsed[-2] == "both"
    assert parsed[-1] is FactorNextPeriodReturns.THIS_CLOSE_TO_CLOSE_ADJUSTED

    display_columns, _paths_hash, _products, ic_param_map, payloads, *_ = _prepare_ic_compute(
        data,
        FakeTester(),
        FakeFamily(FakeFactor()),
    )

    assert display_columns == ["F1 · Rank IC", "F1 · Pearson IC"]
    assert {key[-2] for key in ic_param_map} == {"rank", "pearson"}
    assert {key[3] for key in ic_param_map} == {"CLOSE_ADJUSTED"}
    assert {payload["_ic_method"] for payload in payloads.values()} == {"rank", "pearson"}


def test_factor_type_analysis_reuses_product_path_selection_setting() -> None:
    application = backtest_setting_registry.get("factor_type_analysis")

    index = application.manifest()
    product_tab = application.tab_manifest("product_path_selection")
    method_tab = application.tab_manifest("method")

    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "product_path_selection", "time", "data_source", "frequency", "factor", "method",
    ]
    assert [setting["key"] for setting in product_tab["settings"]] == [
        "product_path_candidates", "product_path_selection",
    ]
    assert index["defaults"]["product_path_selection"]["serialization"]["kind"] == "product_path_selection"
    assert list(index["defaults"]["product_path_selection"]["serialization"]["manual_fields"]) == [
        "product_path_selection_id",
        "paths",
    ]
    assert [setting["key"] for setting in method_tab["settings"]] == [
        "correlation_method",
        "min_periods",
    ]
    assert [tab["key"] for tab in index["result_tabs"]] == [
        "type_overview",
        "reference_factors",
        "product_profiles",
    ]


def test_single_factor_page_shared_defaults_are_registered_by_multiple_modules() -> None:
    application = backtest_setting_registry.get("single_factor_page")
    index = application.manifest()
    index["shared_global_default_keys"] = backtest_setting_registry.shared_global_default_keys(
        ("factor_evaluation", "ic_test", "group_test")
    )

    assert index["default_mounted_tabs"] == {
        "local-settings": ["setting_template"],
        "group-settings": [],
    }
    assert index["shared_global_default_keys"] == [
        "start_date",
        "end_date",
        "start_time",
        "end_time",
        "timezone",
        "time_precision",
        "product_path_candidates",
        "product_path_selection",
        "factor_candidates",
        "factor",
        "data_source",
        "frequency",
    ]


def test_setting_routes_reject_unknown_tabs_instead_of_falling_back() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    client = app.test_client()

    index = client.get("/api/backtest/settings/group_test")
    tab = client.get("/api/backtest/settings/group_test/tabs/engine")
    missing = client.get("/api/backtest/settings/group_test/tabs/legacy")

    assert index.status_code == 200
    assert "settings" not in index.get_json()
    assert tab.status_code == 200
    assert [setting["key"] for setting in tab.get_json()["settings"]] == ["engine", "engine_mode"]
    assert missing.status_code == 404


def test_setting_manifest_does_not_read_page_runtime_time() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)

    payload = app.test_client().get(
        "/api/backtest/settings/group_test?page_uuid=page-1"
    ).get_json()

    assert payload["defaults"]["start_date"]["value"] == ""
    assert payload["defaults"]["start_time"]["value"] == "00:00"
    assert payload["defaults"]["end_date"]["value"] == ""
    assert payload["defaults"]["end_time"]["value"] == "23:59"
    assert payload["defaults"]["time_precision"]["options"] == [
        {"value": "exact", "label": "精确时间"},
        {"value": "trading_day", "label": "交易日"},
    ]
    assert payload["defaults"]["start_time"]["visible_when"] == {
        "time_precision": ["exact"],
    }
    assert payload["defaults"]["end_time"]["visible_when"] == {
        "time_precision": ["exact"],
    }
    assert payload["defaults"]["timezone"]["visible_when"] == {
        "time_precision": ["exact"],
    }


def test_local_settings_supplies_run_defaults_without_flat_frontend_values() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    resolved = _resolve_flat_backtest_settings(
        {
            "local_settings": {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "start_time": "09:00",
                "end_time": "15:00",
                "time_precision": "exact",
                "timezone": "Asia/Shanghai",
            },
        },
        [{"id": "group-1"}],
        [],
    )

    settings = resolved["group-1"]
    assert settings["start_date"] == "2026-01-01"
    assert settings["end_date"] == "2026-01-31"
    assert settings["start_time"] == "09:00"
    assert settings["end_time"] == "15:00"
    assert settings["initial_capital_major"] == 100_000_000.0
    assert settings["allocation_policy"] == "inverse_volatility"


def test_sparse_run_reports_silent_strategy_defaults_for_frontend_notice() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _silent_default_settings_for_run,
    )

    payload = {
        "local_settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    }
    groups = [{"id": "group-1"}]
    resolved = _resolve_flat_backtest_settings(payload, groups, [])

    defaults = _silent_default_settings_for_run(payload, groups, [], resolved)

    by_key = {item["setting_key"]: item for item in defaults}
    assert by_key["allocation_policy"]["value"] == "inverse_volatility"
    assert by_key["allocation_policy"]["value_label"] == "等风险（波动率倒数）"
    assert by_key["execution_timing"]["value"] == "next_bar"


def test_explicit_group_allocation_is_not_reported_as_silent_default() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _silent_default_settings_for_run,
    )

    payload = {
        "local_settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
    }
    groups = [{"id": "group-1", "allocation_policy": "equal_notional"}]
    resolved = _resolve_flat_backtest_settings(payload, groups, [])

    defaults = _silent_default_settings_for_run(payload, groups, [], resolved)

    assert "allocation_policy" not in {item["setting_key"] for item in defaults}


def test_local_settings_dict_is_the_only_run_local_settings_source() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    resolved = _resolve_flat_backtest_settings(
        {
            "local_settings": {
                "allocation_policy": "equal_notional",
                "initial_capital_major": 12_345_678,
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            },
        },
        [{"id": "group-1"}],
        [],
    )

    settings = resolved["group-1"]
    assert settings["allocation_policy"] == "equal_notional"
    assert settings["initial_capital_major"] == 12_345_678


def test_new_run_payload_rejects_top_level_registered_settings() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    with pytest.raises(ValueError, match="registered settings must be nested"):
        _resolve_flat_backtest_settings(
            {
                "local_settings": {
                    "allocation_policy": "equal_notional",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                },
                "allocation_policy": "inverse_volatility",
            },
            [{"id": "group-1"}],
            [],
        )


def test_runtime_datetime_reads_time_values_from_local_settings() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    start_dt, end_dt = _runtime_datetimes({
        "local_settings": {
            "start_date": "2025-02-03",
            "end_date": "2025-02-28",
            "start_time": "10:15",
            "end_time": "14:45",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        },
    })

    assert start_dt.is_set
    assert end_dt.is_set
    assert start_dt.ts.strftime("%Y-%m-%d %H:%M") == "2025-02-03 10:15"
    assert end_dt.ts.strftime("%Y-%m-%d %H:%M") == "2025-02-28 14:45"


def test_local_time_window_takes_precedence_over_group_envelope() -> None:
    from server.modules.single_factor_test.group import _resolve_run_datetimes

    start_dt, end_dt = _resolve_run_datetimes(
        {
            "start_date": "2025-02-01",
            "end_date": "2025-02-28",
            "time_precision": "trading_day",
        },
        {
            "group-1": {
                "start_date": "2025-01-01",
                "end_date": "2025-03-31",
                "time_precision": "trading_day",
            },
        },
    )

    assert start_dt.ts.strftime("%Y-%m-%d") == "2025-02-01"
    assert end_dt.ts.strftime("%Y-%m-%d") == "2025-02-28"


def test_group_time_windows_do_not_form_run_envelope_without_local_time_window() -> None:
    from server.modules.single_factor_test.group import _resolve_run_datetimes

    with pytest.raises(ValueError, match="运行时间范围缺失: start_date, end_date"):
        _resolve_run_datetimes(
            {},
            {
                "group-1": {
                    "start_date": "2025-01-15",
                    "end_date": "2025-02-15",
                    "time_precision": "trading_day",
                },
                "group-2": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                    "time_precision": "trading_day",
                },
            },
        )


def test_local_settings_builds_explicit_start_and_end_datetimes() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    start_dt, end_dt = _runtime_datetimes({
        "local_settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "start_time": "09:00",
            "end_time": "15:00",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        },
    })

    assert start_dt.is_set
    assert end_dt.is_set
    assert start_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-01 09:00"
    assert end_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-31 15:00"


def test_local_settings_builds_trading_day_datetimes_without_time_or_timezone() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _runtime_datetimes,
    )

    payload = {
        "local_settings": {
            "start_date": "2025-04-01",
            "end_date": "2025-04-30",
            "start_time": "11:23",
            "end_time": "14:56",
            "time_precision": "trading_day",
            "timezone": "Asia/Shanghai",
        },
    }
    start_dt, end_dt = _runtime_datetimes(payload)
    resolved = _resolve_flat_backtest_settings(payload, [{"id": "group-1"}], [])

    assert start_dt.precision == "trading_day"
    assert end_dt.precision == "trading_day"
    assert start_dt.tz is None
    assert end_dt.tz is None
    assert start_dt.ts.strftime("%Y-%m-%d %H:%M") == "2025-04-01 00:00"
    assert end_dt.ts.strftime("%Y-%m-%d %H:%M") == "2025-04-30 00:00"
    assert resolved["group-1"]["time_precision"] == "trading_day"


def test_legacy_day_precision_is_rejected() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    with pytest.raises(ValueError, match="invalid value for time_precision"):
        _resolve_flat_backtest_settings(
            {
                "local_settings": {
                    "start_date": "2025-04-01",
                    "end_date": "2025-04-30",
                    "time_precision": "day",
                },
            },
            [{"id": "group-1"}],
            [],
        )


def test_local_settings_reports_missing_dates_before_dataindex_slice() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    with pytest.raises(ValueError, match="运行时间范围缺失: start_date, end_date"):
        _runtime_datetimes({
            "local_settings": {
                "time_precision": "exact",
                "timezone": "Asia/Shanghai",
            },
        })


def test_group_run_resolves_window_from_payload_local_settings() -> None:
    """_resolve_run_datetimes (called directly by run_group_test_stream's
    flattened pipeline, before groups/ls_configs are resolved) must read the
    run window from payload local_settings, not from any page-runtime-owned
    default -- the same contract the deleted per-selection FactorTester loop
    used to exercise indirectly via create_factor_tester_for_product_path_
    selection's start_dt/end_dt arguments."""
    from server.modules.single_factor_test import group as group_module

    start_dt, end_dt = group_module._resolve_run_datetimes(
        {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "start_time": "09:00",
            "end_time": "15:00",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        },
        {},
    )

    assert start_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-01 09:00"
    assert end_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-31 15:00"


def test_setting_index_is_a_real_lazy_loading_boundary() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    payload = app.test_client().get("/api/backtest/settings/group_test").get_json()

    assert payload["tab_url_template"].endswith("/tabs/{tab_key}")
    assert all(
        "settings" not in tab
        for tabs in payload["tab_lists"].values()
        for tab in tabs
    )
    assert "settings" not in payload


def test_group_settings_override_local_values_for_each_combination() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={
            "engine": "native",
            "factor_mode": "auto",
            "initial_capital_major": 1_000_000.0,
            "allocation_policy": "inverse_volatility",
            "volatility_lookback": 20,
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
            "engine_mode": "auto",
            "fee_mode": "auto",
            "liquidity_mode": "volume_participation",
            "participation_rate": 0.1,
            "market_rule_fallback": "latest_available",
        },
        group_values={
            "combination-a:group-1": {
            },
            "combination-b:group-1": {
                "factor_mode": "incremental",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "buy_and_hold",
                "engine_mode": "basic",
                "fee_mode": "zero",
                "liquidity_mode": "infinite",
                "participation_rate": 1.0,
            },
        },
        group_ids=("combination-a:group-1", "combination-b:group-1"),
    )

    assert resolved["combination-a:group-1"]["rebalance_trigger"] == "on_factor_signal"
    assert resolved["combination-a:group-1"]["factor_mode"] == "auto"
    assert resolved["combination-b:group-1"]["factor_mode"] == "incremental"
    assert resolved["combination-b:group-1"]["rebalance_trigger"] == "on_factor_signal"
    assert resolved["combination-b:group-1"]["position_policy"] == "buy_and_hold"
    assert resolved["combination-a:group-1"]["initial_capital_major"] == 1_000_000.0


def test_local_only_group_value_is_ignored_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={"engine": "native"},
        group_values={"group-1": {"engine": "backtrader"}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["engine"] == "native"
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "engine",
        "module": "execution_engine",
        "engine": "native",
        "requested_value": "backtrader",
        "applied_value": "native",
        "reason": "local_only_group_value_ignored",
    }]


def test_numeric_setting_strings_are_normalized() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={},
        group_values={"group-1": {"initial_capital_major": "123456.5"}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["initial_capital_major"] == 123456.5
    assert "_setting_fallbacks" not in resolved["group-1"]


def test_invalid_numeric_setting_falls_back_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={},
        group_values={"group-1": {"initial_capital_major": ""}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["initial_capital_major"] == 100_000_000.0
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "initial_capital_major",
        "module": "portfolio_capital",
        "engine": "native",
        "requested_value": "",
        "applied_value": 100_000_000.0,
        "reason": "invalid_setting_value",
    }]


# money_unit_policy's per-engine override behavior (qlib keeps default,
# rqalpha forces engine_native) was specific to that old field's
# engine_defaults/disabled_values_by_engine mechanism. MinorUnitModule.
# use_minor_units (its replacement) is a plain per-strategy boolean scoped
# to the native engine only -- other engines' money-precision handling
# isn't modeled here, so there's no equivalent cross-engine fallback to test.


def test_execution_price_basis_dependencies_fall_back_with_diagnostics() -> None:
    application = backtest_setting_registry.get("group_test")

    resolved = resolve_group_settings(
        application,
        local_values={
            "engine": "native",
            "execution_timing": "same_bar",
            "execution_price_basis": "open",
        },
        group_values={"group-1": {}},
        group_ids=("group-1",),
    )

    assert resolved["group-1"]["execution_price_basis"] == "close"
    assert resolved["group-1"]["_setting_fallbacks"] == [{
        "setting_key": "execution_price_basis",
        "module": "order_execution",
        "engine": "native",
        "requested_value": "open",
        "applied_value": "close",
        "reason": "incompatible_setting_value",
    }]
