from __future__ import annotations

import pandas as pd
import pytest
from flask import Flask

from server.manager.http.page_assistance_routes import validate_document
from server.modules.single_factor_test import sft_bp
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES
from tools.testers.settings import backtest_setting_registry, resolve_group_settings


def test_retired_single_factor_html_entry_is_not_registered() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)

    response = app.test_client().get("/single_factor_test")

    assert response.status_code == 404


def test_backtest_strategy_contract_is_backend_registered() -> None:
    manifest = backtest_setting_registry.get("group_test").manifest()
    assert manifest["research_configuration_schema_version"] == 3
    contract = manifest[
        "configuration_item_contract"
    ]
    assert contract["schema_version"] == 1
    assert contract["item_kind"] == "strategy"
    assert contract["schema"]["required"] == [
        "id", "batchId", "name", "factor_candidate_refs", "product_path_selection",
        "splitCount", "groupIndex",
    ]
    assert contract["schema"]["properties"]["groupIndex"] == {
        "type": "integer", "minimum": 1, "title": "分组序号",
    }
    assert contract["create_template"] == {
        "id": "<unique-strategy-id>",
        "batchId": "<shared-addition-batch-id>",
        "name": "<strategy-name>",
        "factor_candidate_refs": ["<factor-ref>"],
        "product_path_selection": {
            "product_path_selection_id": "<product-group-ref>",
        },
        "splitCount": 5,
        "groupIndex": 1,
    }
    assert contract["field_sources"] == {
        "factor_candidate_refs": "field:factor_candidates",
        "product_path_selection": "field:product_path_selection",
    }
    assert contract["batch_contract"] == {
        "identity_field": "batchId",
        "semantics": "one_addition_event",
        "shared_for_partition_members": True,
        "partition_fields": ["splitCount", "groupIndex"],
        "instruction": (
            "Strategies created as the members of one N-group partition "
            "must share one batchId; vary groupIndex from 1 through splitCount."
        ),
    }
    item = {
        **contract["create_template"],
        "id": "strategy-agent-1",
        "batchId": "batch:agent-1",
        "name": "Agent strategy 1",
        "factor_candidate_refs": [f"factor:v2:{'a' * 43}"],
        "product_path_selection": {
            "product_path_selection_id": "product-group:agent-1",
        },
    }
    validate_document(contract["schema"], item)
    with pytest.raises(ValueError, match="batchId"):
        validate_document(contract["schema"], {
            key: value for key, value in item.items() if key != "batchId"
        })


def test_ic_configuration_group_contract_teaches_canonical_creation() -> None:
    contract = backtest_setting_registry.get("ic_test").manifest()[
        "configuration_item_contract"
    ]

    assert contract["create_template"]["entry_delay_bars"] == 0
    assert contract["create_template"]["horizon"] == {"sampling": "scale_aware"}
    assert contract["create_template"]["methods"] == ["rank"]
    assert contract["create_template"]["return_price_basis"] == (
        "next_open_to_open_adjusted"
    )
    assert contract["field_sources"] == {
        "factor_ref": "field:factor_candidates",
        "product_scope_ref": "field:product_path_selection",
    }
    assert "batch_contract" not in contract
    item = {
        **contract["create_template"],
        "config_group_id": "icg-agent-1",
        "batch_id": "icb-agent-1",
        "name": "Agent IC configuration",
        "factor_ref": f"factor:v2:{'a' * 43}",
        "product_scope_ref": "product-group:agent-1",
    }
    validate_document(contract["schema"], item)
    for mode in ("none", "fixed", "auto"):
        validate_document(contract["schema"], {**item, "warmup_mode": mode})
    with pytest.raises(ValueError, match="not an allowed value"):
        validate_document(contract["schema"], {**item, "warmup_mode": "unknown"})



def test_run_fields_are_backend_registered_outside_reusable_templates() -> None:
    ic_fields = {
        item["key"]: item
        for item in backtest_setting_registry.get("ic_test").manifest()["run_fields"]
    }
    backtest_fields = {
        item["key"]: item
        for item in backtest_setting_registry.get("group_test").manifest()["run_fields"]
    }

    assert list(ic_fields) == [
        "task_name", "acting_profile_ref", "service_port", "retention_mode",
        "output_requests",
    ]
    assert list(backtest_fields) == [
        "task_name", "acting_profile_ref", "service_port", "retention_mode",
        "step_mode", "output_requests",
        "performance_profile", "margin_execution_profile",
    ]
    for fields in (ic_fields, backtest_fields):
        assert all("chip_group" not in field for field in fields.values())
        assert fields["task_name"]["default"] == ""
        assert fields["task_name"]["placement"] == "run_identity"
        assert fields["acting_profile_ref"]["default"] == ""
        assert fields["acting_profile_ref"]["value_descriptor"]["editor"] == "profile"
        assert fields["acting_profile_ref"]["placement"] == "run_identity"
    assert backtest_setting_registry.get("ic_test").manifest()["run_settings"] == {
        "key": "run_context",
        "label": "任务提交",
        "description": "本次任务的名称、提交身份、结果保留和生成物选择",
        "order": 0,
        "default_mounted": True,
    }
    assert ic_fields["service_port"] == {
        "key": "service_port",
        "label": "服务端口",
        "default": "",
        "request_location": "query",
        "freeze_target": "job.server_context.port",
        "placement": "global_settings",
        "template_policy": "exclude",
        "order": 10,
        "help_text": "可填写固定端口；留空时由 Manager 自动选择可用服务端口",
        "enabled_payload": None,
        "rules": {
            "visible_if": {},
            "editable_if": {},
            "default_if": {},
            "disabled_values": {},
            "engine_defaults": {},
        },
        "value_descriptor": {
            "value_type": "reference",
            "cardinality": "one",
            "editor": "service_port",
            "format": "",
            "unit": "",
            "option_source": "",
            "resolver": "",
            "item_type": "",
            "ref_kind": "service_port",
            "schema": {},
            "options": [],
            "minimum": None,
            "maximum": None,
            "step": None,
        },
    }
    swift_fields = {
        item["key"]: item
        for item in backtest_setting_registry.get("ic_test").manifest(client="swift")["run_fields"]
    }
    assert swift_fields["execution_target"]["value_descriptor"]["editor"] == "select"
    assert swift_fields["execution_target"]["client_targets"] == ["swift"]
    assert swift_fields["local_runtime_server_ref"]["value_descriptor"]["editor"] == "server_picker"
    assert swift_fields["local_runtime_bundle_ref"]["value_descriptor"]["editor"] == "runtime_bundle_picker"
    assert swift_fields["local_runtime_server_ref"]["rules"]["visible_if"] == {
        "execution_target": ["local"],
    }
    assert ic_fields["retention_mode"]["freeze_target"] == "run_spec.retention_mode"
    assert ic_fields["retention_mode"]["template_policy"] == "exclude"
    assert ic_fields["output_requests"]["freeze_target"] == "run_spec.output_requests"
    assert ic_fields["output_requests"]["template_policy"] == "include"
    assert ic_fields["output_requests"]["value_descriptor"]["editor"] == "output_picker"
    assert ic_fields["output_requests"]["value_descriptor"]["cardinality"] == "many"
    assert ic_fields["output_requests"]["placement"] == "outputs"
    assert backtest_fields["step_mode"]["freeze_target"] == "run_spec.step_mode"
    assert backtest_fields["performance_profile"]["freeze_target"] == (
        "job.job_spec.performance_profile"
    )
    assert backtest_fields["performance_profile"]["enabled_payload"] == {
        "kind": "cumulative_flow", "min_total_ms": 1000.0,
    }
    assert backtest_fields["margin_execution_profile"]["enabled_payload"] == {
        "kind": "cumulative", "min_total_ms": 0.0,
    }
    assert all(
        field["template_policy"] == "exclude"
        for key, field in backtest_fields.items()
        if key != "output_requests"
    )


@pytest.mark.parametrize(
    ("application", "expected"),
    (
        ("group_test", ["test_template", "engine", "time"]),
        (
            "ic_test",
            ["test_template", "time"],
        ),
        (
            "factor_evaluation",
            ["product_path_selection", "time", "factor"],
        ),
        (
            "factor_type_analysis",
            ["product_path_selection", "time", "factor", "method"],
        ),
    ),
)
def test_time_range_is_always_mounted_by_default(
    application: str,
    expected: list[str],
) -> None:
    manifest = backtest_setting_registry.get(application).manifest()

    assert manifest["default_mounted_tabs"]["local-settings"] == expected


def test_every_mountable_tab_audits_every_registered_field() -> None:
    """Do not let a lazy tab or adapter-managed field bypass the contract."""
    for client in ("web", "swift"):
        errors = backtest_setting_registry.audit_mounts(client=client)
        assert errors == [], "\n".join(errors)

    single = backtest_setting_registry.get("factor_evaluation").manifest()
    tabs = {
        tab["key"]: tab
        for tab in single["tab_lists"]["local-settings"]
    }
    assert tabs["factor"]["content_adapter"] == "factor_selection"
    assert tabs["product_path_selection"]["content_adapter"] == (
        "product_path_selection"
    )


def test_setting_manifest_loads_tabs_before_tab_controls() -> None:
    application = backtest_setting_registry.get("group_test")

    index = application.manifest()
    engine_tab = application.tab_manifest("engine")

    assert "settings" not in index
    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "test_template", "engine", "category", "factor", "product_path_selection", "data_source", "frequency",
        "delivery_force_close", "time", "rollover", "capital", "target_allocation", "rebalance_trigger",
        "position_policy", "term_carry_strategy", "group_strategy", "cost", "order", "volume_capacity", "strategy_book", "margin",
        "accounting", "run_inputs", "calendar",
    ]
    assert index["default_mounted_tabs"] == {
        "local-settings": ["test_template", "engine", "time"],
        "group-settings": [],
    }
    assert index["run_settings"]["key"] == "run_context"
    assert index["run_settings"]["default_mounted"] is True
    tabs = {tab["key"]: tab for tab in index["tab_lists"]["local-settings"]}
    assert tabs["test_template"]["content_adapter"] == "test_templates"
    assert tabs["factor"]["content_adapter"] == "factor_selection"
    assert tabs["product_path_selection"]["content_adapter"] == (
        "product_path_selection"
    )
    assert tabs["run_inputs"]["content_adapter"] == "run_inputs"
    assert [
        item["kind"] for item in tabs["run_inputs"]["content_options"]["inputs"]
    ] == ["run_dependency"]
    assert tabs["factor"].get("content_options") == {}
    assert [tab["key"] for tab in index["tab_lists"]["group-settings"]] == [
        "engine", "factor", "product_path_selection", "data_source", "frequency",
        "delivery_force_close", "time", "rollover", "capital", "target_allocation",
        "rebalance_trigger", "position_policy", "term_carry_strategy",
        "group_strategy", "cost", "order", "volume_capacity", "strategy_book", "margin",
        "accounting", "calendar",
    ]
    assert index["defaults"]["engine"]["value"] == "native"
    assert index["defaults"]["engine"]["execution_policy"] == "include"
    assert index["defaults"]["setting_template"]["execution_policy"] == (
        "authoring_only"
    )
    for key in (
        "factor_candidates",
        "factor_source_selections",
        "product_path_candidates",
        "product_path_selection",
    ):
        assert index["defaults"][key]["execution_policy"] == "authoring_only"
    assert index["defaults"]["factor_role_bindings"]["execution_policy"] == (
        "include"
    )
    assert index["defaults"]["factor_role_bindings"]["adapter_managed"] is True
    assert index["defaults"]["factor_role_bindings"]["serialization"]["visible_when"] == {
        "min_items": {"factor_candidates": 2},
    }
    assert index["defaults"]["engine"]["tab_key"] == "engine"
    assert [section["key"] for section in index["settings_sections"]] == [
        "authoring", "scope", "portfolio", "execution", "risk", "inputs",
    ]
    assert {
        tab["key"]: tab["section_key"]
        for tab in index["tab_lists"]["local-settings"]
    }["group_strategy"] == "portfolio"
    assert index["defaults"]["engine"]["scope_policy"] == "local_only"
    assert index["defaults"]["engine"]["chip_template"] == "引擎: {value}"
    assert index["defaults"]["engine_mode"]["scope_policy"] == "overridable"
    assert index["defaults"]["start_date"]["scope_policy"] == "overridable"
    assert index["defaults"]["start_date"]["label"] == "开始日期"
    assert index["defaults"]["end_date"]["label"] == "结束日期"
    assert index["defaults"]["time_precision"]["label"] == "时间精度"
    assert index["defaults"]["start_time"]["label"] == "开始时间"
    assert index["defaults"]["end_time"]["label"] == "结束时间"
    assert index["defaults"]["timezone"]["label"] == "时区"
    assert index["defaults"]["evaluation_split"]["tab_key"] == "time"
    assert index["defaults"]["equity_compute_live"]["label"] == "净值实时计算"
    assert index["defaults"]["equity_compute_live"]["module"] == "equity_curve"
    assert index["defaults"]["equity_compute_live"]["tab_key"] == "engine"
    assert index["defaults"]["engine"]["value_descriptor"]["options"][0] == {
        "value": "native",
        "label": "Native 事件驱动回测工具",
    }
    assert index["defaults"]["order_type"]["value"] == "market"
    assert index["defaults"]["matching_model"]["value"] == "auto"
    assert index["defaults"]["quantity_rounding_policy"]["value"] == "floor_to_lot"
    assert index["defaults"]["volatility_lookback"]["rules"]["visible_if"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["volatility_warmup"]["rules"]["visible_if"] == {
        "allocation_policy": ["inverse_volatility"],
    }
    assert index["defaults"]["engine_mode"]["value"] == "auto"
    assert index["defaults"]["engine_mode"]["scope_policy"] == "overridable"
    assert index["defaults"]["force_close_before_expiry"]["value"] == "2d"
    assert index["defaults"]["rollover_policy"]["value"] == "date_before_expiry"
    assert index["defaults"]["rollover_before_expiry"]["value"] == "5d"
    assert index["defaults"]["rollover_before_expiry"]["rules"]["visible_if"] == {
        "rollover_policy": ["date_before_expiry"],
    }
    assert index["defaults"]["fee_mode"]["rules"]["editable_if"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["fee_mode"]["rules"]["default_if"] == {
        "engine_mode": {"basic": "zero", "auto": "auto", "exact": "exact"},
        "counterparty_profile": {"exchange_base": "auto", "openctp_broker": "auto"},
    }
    assert {option["value"] for option in index["defaults"]["fee_mode"]["value_descriptor"]["options"]} == {
        "auto", "exact", "custom", "close_yesterday", "close_today", "fixed", "zero",
    }
    assert index["defaults"]["transaction_fee_source"]["label"] == "交易费来源"
    assert index["defaults"]["transaction_fee_source"]["chip_template"] == "交易费来源: {value}"
    assert index["defaults"]["transaction_fee_source"]["rules"]["default_if"] == {
        "counterparty_profile": {"exchange_base": "exchange", "openctp_broker": "openctp"},
    }
    assert {option["value"] for option in index["defaults"]["transaction_fee_source"]["value_descriptor"]["options"]} == {
        "auto", "exchange", "openctp",
    }
    assert index["defaults"]["fixed_fee_rate"]["rules"]["visible_if"] == {
        "fee_mode": ["fixed"],
    }
    assert index["defaults"]["slippage_bps"]["rules"]["visible_if"] == {
        "slippage_mode": ["fixed_bps"],
    }
    assert index["defaults"]["participation_rate"]["rules"]["visible_if"] == {
        "liquidity_mode": ["volume_participation"],
    }
    assert index["defaults"]["collateral_fraction"]["rules"]["visible_if"] == {
        "margin_mode": ["fixed", "auto", "exact", "custom"],
    }
    assert index["defaults"]["margin_mode"]["value"] == "auto"
    assert index["defaults"]["margin_mode"]["label"] == "保证金模式"
    assert index["defaults"]["margin_mode"]["chip_template"] == "保证金模式: {value}"
    assert index["defaults"]["margin_mode"]["rules"]["editable_if"] == {
        "engine_mode": ["auto", "custom"],
    }
    assert index["defaults"]["margin_mode"]["rules"]["default_if"] == {
        "engine_mode": {"basic": "none", "auto": "auto", "exact": "exact"},
        "counterparty_profile": {"exchange_base": "auto", "openctp_broker": "auto"},
    }
    assert index["defaults"]["target_margin_utilization"]["value"] == 0.30
    assert index["defaults"]["max_margin_utilization"]["value"] == 0.40
    assert index["defaults"]["target_margin_utilization"]["rules"]["visible_if"] == {
        "margin_mode": ["auto", "exact", "custom", "fixed"],
    }
    assert index["defaults"]["accounting_mode"]["rules"]["editable_if"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["custom_product_fields"]["label"] == "自定义字段"
    assert index["defaults"]["custom_product_fields"]["rules"]["visible_if"] == {
        "engine_mode": ["custom"],
    }
    assert index["defaults"]["custom_product_fields"]["chip_template"] == "自定义字段: {value}"
    assert index["defaults"]["custom_product_fields"]["serialization"]["kind"] == "custom_product_overrides"
    custom_fields = index["defaults"]["custom_product_fields"]["serialization"]["fields"]
    assert {field["value"] for field in custom_fields} >= {
        "LongMarginRatioByMoney",
        "ShortMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByVolume",
        "OpenRatioByMoney",
        "CostBasisMethod",
    }
    assert index["defaults"]["historical_field_policy"]["value_descriptor"]["options"][0] == {
        "value": "auto",
        "label": "按执行模式自动选择",
    }
    assert index["defaults"]["historical_field_policy"]["value_descriptor"]["options"][2] == {
        "value": "latest_available",
        "label": "缺失历史数据由时间差最近的数据向后填充",
    }
    assert index["defaults"]["fee_custom_product_fields"]["tab_key"] == "cost"
    assert index["defaults"]["fee_custom_product_fields"]["chip_template"] is None
    assert index["defaults"]["fee_custom_product_fields"]["rules"]["visible_if"] == {
        "engine_mode": ["custom"],
        "fee_mode": ["custom"],
    }
    assert index["defaults"]["fee_custom_product_fields"]["serialization"]["storage_key"] == "custom_product_fields"
    assert index["defaults"]["fee_custom_product_fields"]["serialization"]["module_filter"] == "fee"
    assert index["defaults"]["fee_custom_product_fields"]["serialization"]["module_editor"] == {
        "tab": "cost",
        "mode_when": {"fee_mode": ["custom"]},
    }
    assert index["defaults"]["margin_custom_product_fields"]["tab_key"] == "margin"
    assert index["defaults"]["margin_custom_product_fields"]["chip_template"] is None
    assert index["defaults"]["margin_custom_product_fields"]["rules"]["visible_if"] == {
        "engine_mode": ["custom"],
        "margin_mode": ["custom"],
    }
    assert index["defaults"]["margin_custom_product_fields"]["serialization"]["module_filter"] == "margin"
    margin_fields = index["defaults"]["margin_custom_product_fields"]["serialization"]["fields"]
    assert {field["value"] for field in margin_fields} == {
        "LongMarginRatioByMoney",
        "ShortMarginRatioByMoney",
        "LongMarginRatioByVolume",
        "ShortMarginRatioByVolume",
    }
    assert index["defaults"]["trading_rule_custom_product_fields"]["tab_key"] == "accounting"
    assert index["defaults"]["trading_rule_custom_product_fields"]["chip_template"] is None
    assert index["defaults"]["trading_rule_custom_product_fields"]["rules"]["visible_if"] == {
        "engine_mode": ["custom"],
        "accounting_mode": ["Custom"],
    }
    assert index["defaults"]["trading_rule_custom_product_fields"]["serialization"]["module_filter"] == "trading_rule"
    # money_unit_policy (with per-engine override: rqalpha forces
    # "engine_native", disabling "minor_units") was an execution-engine
    # dispatch concern spanning native/backtrader/qlib/rqalpha -- replaced
    # by MinorUnitModule.use_minor_units, a tri-state intent scoped to the
    # native engine only (other engines' money-precision handling is their
    # own concern, not modeled here).
    assert index["defaults"]["use_minor_units"]["value"] == "auto"
    assert all(item.get("module") for item in index["defaults"].values())
    assert all(chip.get("module") for chip in index["chip_fields"])
    assert all(chip.get("target_tab") for chip in index["chip_fields"])
    assert {
        chip["module"] for chip in index["chip_fields"]
    } >= {"factor_execution", "product_selection", "group_strategy"}
    assert {chip["key"] for chip in index["chip_fields"]} >= {
        "factor_candidates",
        "product_path_selection",
        "group_index",
        "run_inputs",
    }
    chips = {chip["key"]: chip for chip in index["chip_fields"]}
    assert chips["split_count"]["display_scope"] == "strategy"
    assert chips["group_index"]["display_scope"] == "strategy"
    assert "product_mask" not in chips
    assert chips["factor_candidates"]["source_keys"] == ("factorCandidateLabel",)
    assert chips["factor_candidates"]["detail_overlay"] == {
        "kind_source_key": "factorCandidateDetailKind", "mode": "view",
        "source_key": "factor_candidate_detail", "ref_key": "target_ref",
    }
    assert chips["product_path_selection"]["label"] == "产品组"
    assert chips["product_path_selection"]["source_keys"] == ("product_group",)
    assert chips["product_path_selection"]["detail_overlay"] == {
        "kind": "product_group", "mode": "view", "source_key": "product_group",
    }
    run_input_chip = next(
        chip for chip in index["chip_fields"] if chip["key"] == "run_inputs"
    )
    assert run_input_chip["source_adapter"] == "run_inputs"
    assert run_input_chip["target_tab"] == "run_inputs"
    assert [setting["key"] for setting in engine_tab["settings"]] == [
        "engine", "engine_mode", "counterparty_profile", "bar_open_visibility_delay",
        "bar_end_visibility_delay", "historical_field_policy", "equity_compute_live",
        "custom_product_fields",
    ]
    executable_public_fields = {
        key
        for cls in _ALL_MODULE_CLASSES
        for key, field in getattr(cls, "fields", {}).items()
        if field.public
    }
    missing_public_labels = [
        f"{cls.__name__}.{key}"
        for cls in _ALL_MODULE_CLASSES
        for key, field in getattr(cls, "fields", {}).items()
        if field.public and not field.label
    ]
    assert missing_public_labels == []
    assert set(index["defaults"]) - {
        "setting_template", "category_candidates", "category",
    } <= executable_public_fields
    assert index["defaults"]["calendar_frequency"]["module"] == "factor_execution"
    assert index["defaults"]["warmup_mode"]["module"] == "factor_execution"
    assert index["defaults"]["warmup_mode"]["rules"]["default_if"]["engine_mode"]["basic"] == "none"
    assert index["defaults"]["warmup_window"]["rules"]["visible_if"] == {"warmup_mode": ["fixed"]}
    assert index["defaults"]["evaluation_split"]["module"] == "run_window"
    assert "execution_price_basis" not in index["defaults"]
    assert {
        key: index["defaults"][key]["module"]
        for key in ("order_type", "matching_model")
    } == {
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
        "test_template", "factor", "category", "product_path_selection", "time", "data_source", "frequency",
        "summary", "quantile_portfolio_statistics",
    ]
    assert [tab["key"] for tab in index["tab_lists"]["group-settings"]] == [
        "return_frequency", "delay", "ic_method",
    ]
    assert index["configuration_item_contract"]["owned_tabs"] == [
        "return_frequency", "delay", "ic_method",
    ]
    assert index["defaults"]["setting_template"]["serialization"] == {
        "kind": "setting_template",
        "template_scope": "ic_test",
    }
    for key in (
        "setting_template",
        "factor_candidates",
        "factor_source_selections",
        "category_candidates",
        "product_path_candidates",
        "product_path_selections",
    ):
        assert index["defaults"][key]["execution_policy"] == "authoring_only"
    assert index["defaults"]["category"]["execution_policy"] == "include"
    assert index["defaults"]["ic_lags"]["execution_policy"] == "include"
    assert [
        key for key in (
            "factor_owner_ref", "factor_git_commit", "factor_family_ref",
            "factor_params", "factor_candidates", "factor_selections",
            "factor_source_selections",
        ) if key in index["defaults"]
        ] == ["factor_candidates", "factor_selections", "factor_source_selections"]
    assert index["defaults"]["factor_selections"]["execution_policy"] == "authoring_only"
    assert index["defaults"]["factor_selections"]["serialization"] == {
        "kind": "factor_selection_list", "display_order": 30,
        "item_kind": "factor", "multi": True,
        "candidate_field": "factor_candidates", "fallback": "candidates",
        "id_keys": ("ref",),
        "label_keys": ("alias",),
        "item_fields": (
            "schema_version", "ref", "alias", "owner_ref", "identity",
            "source_kind", "transient_factor_id",
        ),
    }
    item_fields = index["defaults"]["factor_candidates"]["serialization"]["item_fields"]
    assert {"schema_version", "ref", "alias", "owner_ref", "identity"}.issubset(
        item_fields
    )
    assert not {
        "factor_git_commit", "git_commit", "git_blob", "relative_path",
        "factor_family_ref", "family_ref",
    }.intersection(item_fields)
    assert index["default_mounted_tabs"] == {
        "local-settings": ["test_template", "time"],
        "group-settings": [],
    }
    tabs = {tab["key"]: tab for tab in index["tab_lists"]["local-settings"]}
    assert tabs["test_template"]["content_adapter"] == "test_templates"
    assert tabs["factor"]["content_adapter"] == "factor_selection"
    assert tabs["category"]["content_adapter"] == "category_selection"
    assert tabs["product_path_selection"]["content_adapter"] == (
        "product_path_selection"
    )
    assert tabs["factor"].get("content_options") == {}
    chips = {chip["key"]: chip for chip in index["chip_fields"]}
    assert chips["factor_candidates"]["source_adapter"] == "selected_factor_candidates"
    assert chips["product_path_selection"]["source_keys"] == ("product_group",)
    backtest_chips = {
        chip["key"]: chip
        for chip in backtest_setting_registry.get("group_test").manifest()["chip_fields"]
    }
    for key in ("factor_candidates", "product_path_selection"):
        assert chips[key] == backtest_chips[key]
    assert chips["factor_candidates"]["detail_overlay"] == {
        "kind_source_key": "factorCandidateDetailKind", "mode": "view",
        "source_key": "factor_candidate_detail", "ref_key": "target_ref",
    }
    assert chips["product_path_selection"]["source_adapter"] == (
        "selected_product_paths"
    )
    assert chips["product_path_selection"]["label"] == "产品组"
    assert chips["product_path_selection"]["detail_overlay"] == {
        "kind": "product_group", "mode": "view", "source_key": "product_group",
    }
    assert index["defaults"]["product_path_selections"]["module"] == "product_selection"
    horizon_field = index["defaults"]["forward_return_horizons"]
    assert horizon_field["value"] == {"sampling": "scale_aware"}
    assert horizon_field["value_descriptor"]["editor"] == "ic_horizon_grid"
    assert horizon_field["module"] == "return_frequency"
    assert index["defaults"]["return_price_basis"]["value"] == "next_open_to_open_adjusted"
    assert index["defaults"]["ic_lags"]["value"] == [0]
    assert index["defaults"]["ic_lags"]["value_descriptor"]["editor"] == "ic_delay_grid"
    assert index["defaults"]["ic_lags"]["tab_key"] == "delay"
    assert [section["key"] for section in index["settings_sections"]] == [
        "authoring", "scope", "data", "core", "analysis",
    ]
    assert {
        tab["key"]: tab["section_key"]
        for tab in index["tab_lists"]["group-settings"]
    }["delay"] == "core"
    assert "信号 bar" in index["defaults"]["ic_lags"]["help_text"]
    assert index["defaults"]["ic_decay_lags"]["value"] == [5]
    assert index["defaults"]["ic_decay_lags"]["value_descriptor"]["editor"] == "ic_decay_grid"
    assert index["defaults"]["ic_decay_lags"]["label"] == "IC 重采样间隔"
    assert "重采样" in index["defaults"]["ic_decay_lags"]["help_text"]
    assert "自相关阶数" in index["defaults"]["ic_decay_lags"]["help_text"]
    assert index["defaults"]["ic_correlation"]["value"] == "rank"
    assert {
        "group_adjust", "by_group", "min_cross_section_count",
    }.isdisjoint(index["defaults"])
    assert index["defaults"]["start_time"]["rules"]["visible_if"] == {
        "time_precision": ["exact"],
    }
    assert {chip["key"] for chip in index["chip_fields"]} >= {
        "factor_candidates",
        "product_path_selection",
    }
    assert [tab["key"] for tab in index["result_tabs"]][:3] == [
        "cross_sectional_rank_ic",
        "cross_sectional_pearson_ic",
        "ic_summary",
    ]
    assert index["result_tabs"][0]["default"] is True
    assert index["result_tabs"][0]["requires"] == {"ic_correlation": ["rank", "both"]}
    assert {"by_group_ic", "coverage_missing"}.isdisjoint(
        tab["key"] for tab in index["result_tabs"]
    )
    assert [setting["key"] for setting in product_tab["settings"]] == [
        "product_path_candidates", "product_path_selections",
    ]
    assert [setting["key"] for setting in time_tab["settings"]] == [
        "start_date", "end_date", "start_time", "end_time", "time_precision", "timezone",
        "evaluation_split",
    ]


def test_ic_prepare_uses_registered_settings_for_both_methods() -> None:
    from server.modules.single_factor_test.ic import _parse_ic_params, _prepare_ic_compute
    from tools.factors.Parameters import FactorNextPeriodReturns

    from tools.data.types import DataFreq

    class FakeFreq:
        _real = DataFreq("1m")
        name = _real.name
        value = _real.value

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
        "ic_correlation": "both",
        "return_price_basis": "next_close_to_close_adjusted",
    }

    parsed = _parse_ic_params(data)
    assert parsed[-4] == "both"
    assert parsed[-3] is FactorNextPeriodReturns.THIS_CLOSE_TO_CLOSE_ADJUSTED
    assert parsed[-2:] == (["__scale_aware__"], [1])

    display_columns, _paths_hash, _products, ic_param_map, payloads, *_rest = _prepare_ic_compute(
        data,
        FakeTester(),
        FakeFamily(FakeFactor()),
    )

    assert display_columns == ["F1 · Rank IC", "F1 · Pearson IC"]
    assert {key[-2] for key in ic_param_map} == {"rank", "pearson"}
    assert {key[3] for key in ic_param_map} == {"CLOSE_ADJUSTED"}
    assert {payload["_ic_method"] for payload in payloads.values()} == {"rank", "pearson"}
    resolved_horizons = _rest[-2]
    assert resolved_horizons[0] == "MIN1"
    assert "HOUR1" in resolved_horizons
    assert "DAY1" in resolved_horizons


def test_ic_registered_decay_default_reaches_execution_as_a_lag_list() -> None:
    from server.modules.single_factor_test.ic import _parse_ic_params

    defaults = backtest_setting_registry.get("ic_test").manifest()["defaults"]
    parsed = _parse_ic_params({
        "product_path_selection_id": "manual",
        "factors": [{"alias": "F1"}],
        "ic_decay_lags": defaults["ic_decay_lags"]["value"],
    })

    assert parsed[4] == [5]


def test_ic_prepare_expands_signal_and_explicit_forward_horizons_once() -> None:
    from server.modules.single_factor_test.ic import _prepare_ic_compute
    from tools.data.types import DataFreq

    class FakeFactor:
        alias = "F1"
        name = "F1"
        freq = DataFreq("5m")

        def _structural_key(self):
            return ("fake-factor", self.alias)

    class FakeFamily:
        def get_factor_by_alias(self, alias):
            return FakeFactor() if alias == "F1" else None

    class FakeTester:
        products = []

    data = {
        "product_path_selection_id": "manual",
        "factor_family_alias": "Family",
        "factors": [{"alias": "F1"}],
        "forward_return_horizons": {
            "bases": ["signal", "1m"],
            "multipliers": [1, 5],
        },
    }

    *_prefix, param_map, payloads, _decay, _rolling, _lags, _primary_lag, horizons, primary = _prepare_ic_compute(
        data, FakeTester(), FakeFamily(),
    )

    # signal×1 and explicit 1m×5 coincide at 5m and must not run twice.
    assert horizons == ["MIN5", "MIN25", "MIN1"]
    assert primary == {"F1": "MIN5"}
    assert {key[4] for key in param_map} == {"MIN1", "MIN5", "MIN25"}
    return_aliases = {payload["RE"].alias for payload in payloads.values()}
    assert {"RF:1m", "RF:5m", "RF:25m"} == {
        next(token for token in ("RF:1m", "RF:5m", "RF:25m") if token in alias)
        for alias in return_aliases
    }


def test_scale_aware_horizons_scale_with_signal_frequency() -> None:
    from server.modules.single_factor_test.ic_params import (
        SCALE_AWARE_HORIZON_BASE,
        resolve_forward_horizons,
    )
    from tools.data.types import DataFreq

    one_minute = resolve_forward_horizons(
        DataFreq.MIN1, [SCALE_AWARE_HORIZON_BASE], [1],
    )
    five_minute = resolve_forward_horizons(
        DataFreq.MIN5, [SCALE_AWARE_HORIZON_BASE], [1],
    )

    assert one_minute[0].name == "MIN1"
    assert five_minute[0].name == "MIN5"
    assert "DAY1" in {item.name for item in one_minute}
    assert "DAY1" in {item.name for item in five_minute}
    assert all(
        left.value < right.value
        for left, right in zip(one_minute, one_minute[1:])
    )
    assert all(
        left.value < right.value
        for left, right in zip(five_minute, five_minute[1:])
    )
    assert five_minute[0].value == one_minute[0].value * 5


def test_horizon_sampling_policy_is_explicitly_described() -> None:
    from server.modules.single_factor_test.ic_params import describe_forward_horizon_sampling

    assert describe_forward_horizon_sampling({}) == {
        "mode": "scale_aware", "source": "default_direct_request",
    }
    assert describe_forward_horizon_sampling({
        "forward_return_horizons": {"sampling": "scale_aware"},
    }) == {"mode": "scale_aware", "source": "request"}
    assert describe_forward_horizon_sampling({
        "return_frequency_mode": "factor_frequency",
    }) == {
        "mode": "legacy", "source": "return_frequency_mode",
        "return_frequency_mode": "factor_frequency",
    }


def test_forward_ic_half_life_uses_first_half_amplitude_crossing() -> None:
    from server.modules.single_factor_test.ic_response import _forward_ic_half_life

    stats = {
        "MIN1": {0: pd.Series({"mean": 0.04})},
        "MIN5": {0: pd.Series({"mean": 0.03})},
        "MIN10": {0: pd.Series({"mean": 0.01})},
    }

    result = _forward_ic_half_life(stats, entry_delay_bars=0)

    assert result["status"] == "estimated"
    assert result["duration"] == "MIN7SECOND30"
    assert result["seconds"] == 450.0
    assert result["curve_monotonic_nonincreasing"] is True


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


def test_factor_evaluation_reuses_product_path_selection_setting() -> None:
    application = backtest_setting_registry.get("factor_evaluation")

    index = application.manifest()
    product_tab = application.tab_manifest("product_path_selection")

    assert [tab["key"] for tab in index["tab_lists"]["local-settings"]] == [
        "product_path_selection", "category", "time", "data_source",
        "frequency", "price_type", "factor",
    ]
    category_tab = application.tab_manifest("category")
    assert category_tab["tab"]["content_adapter"] == "category_selection"
    assert [setting["key"] for setting in product_tab["settings"]] == [
        "product_path_candidates", "product_path_selection",
    ]
    assert index["defaults"]["product_path_selection"]["serialization"]["kind"] == "product_path_selection"
    assert list(index["defaults"]["product_path_selection"]["serialization"]["manual_fields"]) == [
        "product_path_selection_id",
        "paths",
    ]
    assert "product" not in index["defaults"]
    assert index["defaults"]["warmup_mode"]["value"] == "none"
    assert index["defaults"]["warmup_window"]["rules"]["visible_if"] == {
        "warmup_mode": ["fixed"],
    }


def test_setting_routes_reject_unknown_tabs_instead_of_falling_back() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)
    client = app.test_client()

    index = client.get("/api/test-authoring/modules/group_test")
    tab = client.get("/api/test-authoring/modules/group_test/tabs/engine")
    missing = client.get("/api/test-authoring/modules/group_test/tabs/legacy")

    assert index.status_code == 200
    assert "settings" not in index.get_json()
    assert tab.status_code == 200
    assert [setting["key"] for setting in tab.get_json()["settings"]] == [
        "engine", "engine_mode", "counterparty_profile", "bar_open_visibility_delay",
        "bar_end_visibility_delay", "historical_field_policy", "equity_compute_live",
        "custom_product_fields",
    ]
    assert missing.status_code == 404


def test_setting_manifest_does_not_read_page_runtime_time() -> None:
    app = Flask(__name__)
    app.register_blueprint(sft_bp)

    payload = app.test_client().get(
        "/api/test-authoring/modules/group_test?page_uuid=page-1"
    ).get_json()

    assert payload["defaults"]["start_date"]["value"] == ""
    assert payload["defaults"]["start_time"]["value"] == "00:00"
    assert payload["defaults"]["end_date"]["value"] == ""
    assert payload["defaults"]["end_time"]["value"] == "23:59"
    assert payload["defaults"]["time_precision"]["value_descriptor"]["options"] == [
        {"value": "exact", "label": "精确时间"},
        {"value": "trading_day", "label": "交易日"},
    ]
    assert payload["defaults"]["start_time"]["rules"]["visible_if"] == {
        "time_precision": ["exact"],
    }
    assert payload["defaults"]["end_time"]["rules"]["visible_if"] == {
        "time_precision": ["exact"],
    }
    assert payload["defaults"]["timezone"]["rules"]["visible_if"] == {
        "time_precision": ["exact"],
    }


def test_execution_settings_supplies_run_defaults_without_flat_frontend_values() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    resolved = _resolve_flat_backtest_settings(
        {
            "execution": {"settings": {
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "start_time": "09:00",
                "end_time": "15:00",
                "time_precision": "exact",
                "timezone": "Asia/Shanghai",
            }},
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
    assert settings["allocation_policy"] == "equal_notional"


def test_sparse_run_reports_silent_strategy_defaults_for_frontend_notice() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _silent_default_settings_for_run,
    )

    payload = {
        "execution": {"settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }},
    }
    groups = [{"id": "group-1"}]
    resolved = _resolve_flat_backtest_settings(payload, groups, [])

    defaults = _silent_default_settings_for_run(payload, groups, [], resolved)

    by_key = {item["setting_key"]: item for item in defaults}
    assert by_key["allocation_policy"]["value"] == "equal_notional"
    assert by_key["allocation_policy"]["value_label"] == "等名义敞口"
    assert "execution_timing" not in by_key
    assert "execution_price_basis" not in by_key


def test_explicit_group_allocation_is_not_reported_as_silent_default() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _silent_default_settings_for_run,
    )

    payload = {
        "execution": {"settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }},
    }
    groups = [{"id": "group-1", "allocation_policy": "equal_notional"}]
    resolved = _resolve_flat_backtest_settings(payload, groups, [])

    defaults = _silent_default_settings_for_run(payload, groups, [], resolved)

    assert "allocation_policy" not in {item["setting_key"] for item in defaults}


def test_execution_settings_dict_is_the_only_run_settings_source() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    resolved = _resolve_flat_backtest_settings(
        {
            "execution": {"settings": {
                "allocation_policy": "equal_notional",
                "initial_capital_major": 12_345_678,
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            }},
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
                "execution": {"settings": {
                    "allocation_policy": "equal_notional",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                }},
                "allocation_policy": "inverse_volatility",
            },
            [{"id": "group-1"}],
            [],
        )


def test_runtime_execution_projection_reads_nested_execution_settings() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    execution_settings = {
        "allocation_policy": "equal_notional",
        "initial_capital_major": 12_345_678,
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
    }
    resolved = _resolve_flat_backtest_settings(
        {
            "run_spec": {
                "configuration": {
                    "analyses": {"backtest": {"execution": {"settings": execution_settings}}},
                },
            },
            "execution": {"settings": execution_settings},
            **execution_settings,
        },
        [{"id": "group-1"}],
        [],
    )

    assert resolved["group-1"]["allocation_policy"] == "equal_notional"
    assert resolved["group-1"]["initial_capital_major"] == 12_345_678


def test_conflicting_runtime_execution_projection_is_rejected() -> None:
    from server.modules.single_factor_test.group import _resolve_flat_backtest_settings

    with pytest.raises(ValueError, match="registered settings must be nested"):
        _resolve_flat_backtest_settings(
            {
                "run_spec": {"configuration": {}},
                "execution": {"settings": {
                    "allocation_policy": "equal_notional",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                }},
                "allocation_policy": "inverse_volatility",
            },
            [{"id": "group-1"}],
            [],
        )


def test_runtime_datetime_reads_time_values_from_execution_settings() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    start_dt, end_dt = _runtime_datetimes({
        "execution": {"settings": {
            "start_date": "2025-02-03",
            "end_date": "2025-02-28",
            "start_time": "10:15",
            "end_time": "14:45",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        }},
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


def test_execution_settings_builds_explicit_start_and_end_datetimes() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    start_dt, end_dt = _runtime_datetimes({
        "execution": {"settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "start_time": "09:00",
            "end_time": "15:00",
            "time_precision": "exact",
            "timezone": "Asia/Shanghai",
        }},
    })

    assert start_dt.is_set
    assert end_dt.is_set
    assert start_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-01 09:00"
    assert end_dt.ts.strftime("%Y-%m-%d %H:%M") == "2026-01-31 15:00"


def test_execution_settings_builds_trading_day_datetimes_without_time_or_timezone() -> None:
    from server.modules.single_factor_test.group import (
        _resolve_flat_backtest_settings,
        _runtime_datetimes,
    )

    payload = {
        "execution": {"settings": {
            "start_date": "2025-04-01",
            "end_date": "2025-04-30",
            "start_time": "11:23",
            "end_time": "14:56",
            "time_precision": "trading_day",
            "timezone": "Asia/Shanghai",
        }},
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
                "execution": {"settings": {
                    "start_date": "2025-04-01",
                    "end_date": "2025-04-30",
                    "time_precision": "day",
                }},
            },
            [{"id": "group-1"}],
            [],
        )


def test_execution_settings_reports_missing_dates_before_dataindex_slice() -> None:
    from server.modules.single_factor_test.group import _runtime_datetimes

    with pytest.raises(ValueError, match="运行时间范围缺失: start_date, end_date"):
        _runtime_datetimes({
            "execution": {"settings": {
                "time_precision": "exact",
                "timezone": "Asia/Shanghai",
            }},
        })


def test_group_run_resolves_window_from_payload_execution_settings() -> None:
    """_resolve_run_datetimes (called directly by run_group_test_stream's
    flattened pipeline, before groups/ls_configs are resolved) must read the
    run window from payload execution settings, not from any page-runtime-owned
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
    payload = app.test_client().get("/api/test-authoring/modules/group_test").get_json()

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
            "historical_field_policy": "latest_available",
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


def test_invalid_explicit_numeric_setting_is_rejected() -> None:
    application = backtest_setting_registry.get("group_test")

    with pytest.raises(
        ValueError,
        match="setting initial_capital_major requires a number",
    ):
        resolve_group_settings(
            application,
            local_values={},
            group_values={"group-1": {"initial_capital_major": ""}},
            group_ids=("group-1",),
        )


# money_unit_policy's per-engine override behavior (qlib keeps default,
# rqalpha forces engine_native) was specific to that old field's
# engine_defaults/disabled_values mechanism. MinorUnitModule.
# use_minor_units (its replacement) is a plain per-strategy boolean scoped
# to the native engine only -- other engines' money-precision handling
# isn't modeled here, so there's no equivalent cross-engine fallback to test.


def test_order_execution_price_basis_is_not_a_public_setting() -> None:
    application = backtest_setting_registry.get("group_test")

    with pytest.raises(ValueError, match="unknown backtest settings"):
        resolve_group_settings(
            application,
            local_values={
                "engine": "native",
                "execution_timing": "same_bar",
                "execution_price_basis": "close",
            },
            group_values={"group-1": {}},
            group_ids=("group-1",),
        )


def test_setting_summary_preserves_defaults_but_defers_tab_control_metadata() -> None:
    application = backtest_setting_registry.get("group_test")
    summary = application.summary()
    full = application.manifest()

    assert summary["manifest_mode"] == "summary"
    assert summary["full_manifest_url"] == "/api/test-authoring/modules/group_test"
    assert set(summary["defaults"]) == set(full["defaults"])
    for key, field in summary["defaults"].items():
        assert field["value"] == full["defaults"][key]["value"]
        assert field["tab_key"] == full["defaults"][key]["tab_key"]
        if "value_descriptor" in full["defaults"][key]:
            assert field["value_descriptor"] == full["defaults"][key]["value_descriptor"]
        assert "help_text" not in field

    tab = application.tab_manifest("engine")
    assert tab["defaults"]
    assert any(
        field.get("value_descriptor", {}).get("options")
        for field in tab["defaults"].values()
    )


def test_nested_strategy_editor_contract_is_shared_by_backtest_and_ic() -> None:
    expected_by_application = {
        "group_test": ["__strategy__", "factor", "product_path_selection"],
        "ic_test": ["__configuration__", "factor", "product_path_selection"],
    }
    for application_name, expected in expected_by_application.items():
        contract = backtest_setting_registry.get(application_name).manifest()["strategy_editor"]
        assert [item["key"] for item in contract["inner_default_tabs"]] == expected
        assert [item["key"] for item in contract["outer_pre_mounted_tabs"]] == expected
        assert [item["key"] for item in contract["pre_mounted_tabs"]] == expected
        labels = {item["key"]: item["label"] for item in contract["inner_default_tabs"]}
        assert labels["factor"] == (
            "因子" if application_name == "ic_test" else "因子执行"
        )
        assert not set(expected).intersection(contract["outer_only_tabs"])
        manual_keys = [item["key"] for item in contract["inner_manual_tabs"]]
        if application_name == "ic_test":
            assert manual_keys == ["delay"]
            assert "category" not in manual_keys
            assert "trading_product_filter" not in manual_keys
            delay = next(item for item in contract["inner_manual_tabs"] if item["key"] == "delay")
            assert delay["field"] == "ic_lags"
            assert delay["cardinality"] == "one"
            assert delay["minimum"] == 0
            assert delay["item_field"] == "entry_delay_bars"
            assert delay["item_default"] == 0
            assert delay["registration_source"] == {
                "tab": "delay", "field": "ic_lags",
            }
        else:
            assert "delay" not in manual_keys
            product_filter = next(
                item for item in contract["inner_manual_tabs"]
                if item["key"] == "trading_product_filter"
            )
            assert product_filter["item_field"] == "productMask"
            assert product_filter["item_default"] == {}

        assert contract["outer_scope_tabs"]["factor"]["selection_fields"] == [
            "factor_candidates",
        ]
        assert contract["factor_scope"]["strategy_selection_field"] == (
            "factor_candidate_refs"
        )
        assert contract["outer_scope_tabs"]["factor"]["scope_fields"] == [
            "factor_candidates",
        ]
        assert contract["factor_candidate_sources"]["inner"] == {
            "source_when_outer_mounted": "factor_candidates",
            "selection_mode_when_outer_mounted": "filter",
            "sources_when_outer_unmounted": [
                "factor_set_selections", "factor_source_selections",
            ],
            "selection_mode_when_outer_unmounted": "build_candidate_pool",
            "editor": "shared_object_multi_select",
        }
        inner_factor = contract["inner_factor_fields"]
        assert inner_factor["candidate_selection"]["cardinality"] == "many"
        assert inner_factor["candidate_selection"]["filter_only_when_outer_mounted"] is True
        assert inner_factor["combination_mode"]["key"] == "factor_combination_mode"
        assert inner_factor["combination_mode"]["options"] == []
        assert inner_factor["combination_mode"]["required_when"] == {
            "min_items": {"factor_candidates": 2},
        }
        assert inner_factor["shared_overridable_fields"] == [
            "factor_role_bindings", "factor_mode", "warmup_mode", "warmup_window",
        ]
        scoped = contract["scoped_fields"]
        assert scoped["factor_candidates"]["outer"]["selection_mode"] == (
            "build_candidate_pool"
        )
        assert scoped["factor_candidates"]["inner"]["selection_mode"] == (
            "filter_or_build_candidates"
        )
        assert scoped["factor_candidates"]["inner"]["source_when_outer_mounted"] == (
            "outer_candidate_pool"
        )
        assert "factor" not in scoped
        assert scoped["factor_role_bindings"]["outer"]["visible_when"] == {
            "min_items": {"factor_candidates": 2},
        }
        assert scoped["factor_role_bindings"]["inner"]["visible_when"] == {
            "min_items": {"factor_candidates": 2},
        }
        assert scoped["warmup_window"]["inner"]["visible_when"] == {
            "field_values": {"warmup_mode": ["fixed"]},
        }
        for key in ("factor_mode", "warmup_mode", "warmup_window"):
            assert scoped[key]["inner"]["override_control"] == "direct"
        assert scoped["product_path_candidates"]["inner"][
            "source_when_outer_unmounted"
        ] == "visible_product_group_catalog"
        assert scoped["category_candidates"]["inner"] == {
            "source_when_outer_mounted": "outer_category_pool",
            "source_when_outer_unmounted": "visible_category_catalog",
            "cardinality": "many",
            "selection_mode": "filter_or_build_candidates",
            "filter_only_when_outer_mounted": True,
            "allow_inline_create_when_outer_unmounted": True,
            "editable": True,
        }
        assert contract["outer_scope_tabs"]["category"]["candidate_kind"] == "category"
        index = backtest_setting_registry.get(application_name).manifest()
        if "factor" in index["defaults"]:
            assert index["defaults"]["factor"]["serialization"]["resolution"] == {
                "kind": "automatic",
                "source": "factor_candidates",
                "resolver": "primary_item",
                "editable": False,
            }
        assert "time" in contract["outer_only_tabs"]
        assert "data_source" in contract["outer_only_tabs"]
        data_source = backtest_setting_registry.get(application_name).manifest()["defaults"]["data_source"]
        if application_name == "group_test":
            assert data_source["value_descriptor"]["cardinality"] == "many"
        else:
            assert data_source["value"] == "auto"
            assert data_source["value_descriptor"]["cardinality"] == "one"
            assert data_source["value_descriptor"]["editor"] == "select"
        assert contract["candidate_constraints"]["category_candidates"] == {
            "source_field": "data_source",
            "mode_field": "data_source_mode",
            "automatic_mode": "auto",
            "coverage": "complete_path_coverage",
            "side": "outer",
        }
        assert contract["candidate_constraints"]["product_path_candidates"] == {
            "source_field": "data_source",
            "mode_field": "data_source_mode",
            "automatic_mode": "auto",
            "coverage": "complete_product_coverage",
            "side": "outer",
        }

    ic_manifest = backtest_setting_registry.get("ic_test").manifest()
    ic_chips = {item["key"]: item for item in ic_manifest["chip_fields"]}
    assert ic_chips["configuration_name"] == {
        "key": "configuration_name",
        "label": "配置",
        "category": "identity",
        "chip_template": "配置: {configurationName}",
        "source_keys": ("configurationName",),
        "module": "ic_configuration_group",
        "target_tab": "__configuration__",
        "order": 5,
        "inherit_from_root": False,
        "value_resolvers": {},
        "clickable": False,
        "batch_owned": False,
        "source_adapter": "primary_ic_configuration_group",
        "display_scope": "strategy",
        "detail_overlay": None,
    }
    category_chip = next(
        item for item in ic_manifest["chip_fields"] if item["key"] == "category"
    )
    assert category_chip["source_adapter"] == "selected_category"
    assert category_chip["detail_overlay"]["kind"] == "category"
    assert ic_manifest["defaults"]["category"]["show_chip"] is False
