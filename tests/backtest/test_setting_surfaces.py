"""Tests for the backend-declared settings surfaces + flows (the manifest-driven
list/panel infrastructure consumed by the neutral frontend common components)."""

from __future__ import annotations

from tools.testers.settings import backtest_setting_registry


def _surfaces(app: str) -> dict[str, dict]:
    return {s["key"]: s for s in backtest_setting_registry.get(app).manifest()["surfaces"]}


def _flows(app: str) -> dict[str, dict]:
    return {f["key"]: f for f in backtest_setting_registry.get(app).manifest()["flows"]}


def test_single_factor_page_has_a_single_panel_surface() -> None:
    surfaces = _surfaces("single_factor_page")
    assert set(surfaces) == {"local"}
    assert surfaces["local"]["kind"] == "panel"
    assert surfaces["local"]["mount"] == "local-settings"
    # a flat panel has no list flows
    assert _flows("single_factor_page") == {}


def test_group_test_declares_panel_and_multi_select_list() -> None:
    surfaces = _surfaces("group_test")
    assert surfaces["local"]["kind"] == "panel"
    groups = surfaces["groups"]
    assert groups["kind"] == "list"
    assert groups["mount"] == "group-settings"
    assert groups["selection"] == "multi"
    assert groups["run_mode"] == "run_all"
    assert groups["editable"] is True
    assert groups["content_adapter"] == "backtest_groups"
    assert groups["label"] == "分组策略"
    long_short = surfaces["long_short"]
    assert long_short["content_adapter"] == "backtest_long_short"
    assert long_short["selection"] == "single"
    assert long_short["label"] == "分组多空策略"
    custom = surfaces["custom_strategy"]
    assert custom["mount"] == "group-settings"
    assert custom["content_adapter"] == "backtest_custom_strategies"
    assert [item["kind"] for item in custom["content_options"]["inputs"]] == [
        "strategy_source", "strategy_spec",
    ]


def test_ic_declares_single_select_select_then_run_list() -> None:
    surfaces = _surfaces("ic_test")
    ic = surfaces["ic_configs"]
    assert ic["kind"] == "list"
    assert ic["selection"] == "single"
    assert ic["run_mode"] == "select_then_run"
    assert ic["editable"] is True
    assert ic["label"] == "配置组设置"
    assert ic["item_label"] == "配置组"
    assert ic["content_adapter"] == "ic_configuration_groups"


def test_group_test_flows_declared_with_selection_gating() -> None:
    flows = _flows("group_test")
    assert set(flows) == {
        "add_group", "create_derived", "create_ls", "edit", "delete",
        "rename", "rename_long_short", "add_long_short", "edit_long_short",
        "swap_long_short", "delete_long_short",
    }
    # kinds
    assert flows["add_group"]["kind"] == "create"
    assert flows["create_derived"]["kind"] == "derive"
    assert flows["create_ls"]["kind"] == "compose"
    assert flows["rename"]["kind"] == "rename"
    assert flows["rename_long_short"]["kind"] == "rename"
    assert flows["add_long_short"]["kind"] == "create"
    assert flows["edit_long_short"]["kind"] == "edit"
    assert (flows["edit_long_short"]["min_selected"],
            flows["edit_long_short"]["max_selected"]) == (1, 1)
    assert flows["swap_long_short"]["kind"] == "swap"
    # availability (min/max selected)
    assert flows["add_group"]["min_selected"] is None
    assert (flows["create_derived"]["min_selected"], flows["create_derived"]["max_selected"]) == (1, 1)
    assert (flows["create_ls"]["min_selected"], flows["create_ls"]["max_selected"]) == (2, 2)
    assert flows["create_derived"]["form_tab"] == "add-derived"
    assert flows["delete"]["min_selected"] == 1 and flows["delete"]["max_selected"] is None
    assert flows["delete_long_short"]["surface"] == "long_short"


def test_ic_flows_declared() -> None:
    flows = _flows("ic_test")
    assert set(flows) == {"add_config", "edit", "delete"}
    assert flows["add_config"]["kind"] == "create"
    assert flows["add_config"]["label"] == "新增配置组"
    assert (flows["edit"]["min_selected"], flows["edit"]["max_selected"]) == (1, 1)


def test_flows_only_reference_declared_list_surfaces() -> None:
    for app in ("group_test", "ic_test", "single_factor_page"):
        manifest = backtest_setting_registry.get(app).manifest()
        list_surface_keys = {s["key"] for s in manifest["surfaces"] if s["kind"] == "list"}
        for flow in manifest["flows"]:
            assert flow["surface"] in list_surface_keys, (
                f"{app}: flow {flow['key']} references non-list surface {flow['surface']}"
            )
