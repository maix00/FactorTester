"""Tests for the backend-declared settings surfaces + flows (the manifest-driven
list/panel infrastructure consumed by the neutral frontend common components)."""

from __future__ import annotations

from tools.testers.settings import backtest_setting_registry


def _surfaces(app: str) -> dict[str, dict]:
    return {s["key"]: s for s in backtest_setting_registry.get(app).manifest()["surfaces"]}


def _flows(app: str) -> dict[str, dict]:
    return {f["key"]: f for f in backtest_setting_registry.get(app).manifest()["flows"]}


def test_group_test_declares_one_strategy_group_list() -> None:
    surfaces = _surfaces("group_test")
    assert surfaces["local"]["kind"] == "panel"
    groups = surfaces["groups"]
    assert groups["kind"] == "list"
    assert groups["mount"] == "group-settings"
    assert groups["selection"] == "multi"
    assert groups["run_mode"] == "run_all"
    assert groups["editable"] is True
    assert groups["content_adapter"] == "backtest_groups"
    assert groups["label"] == "策略组"
    assert groups["item_label"] == "策略"
    assert set(surfaces) == {"local", "groups"}


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
    assert set(flows) == {"add_strategy", "edit_strategy", "rename_strategy", "delete_strategy"}
    assert flows["add_strategy"]["kind"] == "create"
    assert flows["add_strategy"]["label"] == "添加策略"
    assert flows["add_strategy"]["form_tab"] == "add-strategy"
    assert flows["edit_strategy"]["kind"] == "edit"
    assert flows["rename_strategy"]["kind"] == "rename"
    assert flows["delete_strategy"]["kind"] == "delete"
    assert flows["delete_strategy"]["min_selected"] == 1


def test_ic_flows_declared() -> None:
    flows = _flows("ic_test")
    assert set(flows) == {"add_config", "edit", "delete"}
    assert flows["add_config"]["kind"] == "create"
    assert flows["add_config"]["label"] == "新增配置组"
    assert (flows["edit"]["min_selected"], flows["edit"]["max_selected"]) == (1, 1)


def test_flows_only_reference_declared_list_surfaces() -> None:
    for app in ("group_test", "ic_test", "factor_evaluation"):
        manifest = backtest_setting_registry.get(app).manifest()
        list_surface_keys = {s["key"] for s in manifest["surfaces"] if s["kind"] == "list"}
        for flow in manifest["flows"]:
            assert flow["surface"] in list_surface_keys, (
                f"{app}: flow {flow['key']} references non-list surface {flow['surface']}"
            )
