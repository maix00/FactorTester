"""Backend-owned, lazily loaded backtest setting manifests.

The manifest now includes `executable_modules` via the ModuleRegistry —
the frontend receives module phase declarations alongside setting schemas.
"""

from __future__ import annotations

from flask import jsonify

from tools.testers.settings import backtest_setting_registry
from tools.testers.backtest.modules.registry import BacktestModuleRegistry
from tools.testers.home import HomeModuleRegistry
from tools.testers.registry import Module, ModuleRegistry

from . import sft_bp


def _registry_for(application: str) -> BacktestModuleRegistry:
    """Return the appropriate module registry for an application.

    Looks up the application's Module in the HomeModuleRegistry tree; if it
    has a nested BacktestModuleRegistry sub_registry (e.g. group_test ->
    GroupTestModuleRegistry), use that. Otherwise fall back to a default
    BacktestModuleRegistry (executable modules are application-agnostic for
    non-group applications).
    """
    module = HomeModuleRegistry().find(application)
    if module is not None and isinstance(module.sub_registry, BacktestModuleRegistry):
        return module.sub_registry
    return BacktestModuleRegistry()


def _serialize_module(module: Module) -> dict:
    """递归序列化一个 Module。BacktestModuleRegistry 子注册中心展开为其
    module_manifest()（叶子是执行模块，不是嵌套 Module 树）；其它 ModuleRegistry
    子注册中心递归展开为 Module 列表。"""
    sub = module.sub_registry
    if isinstance(sub, BacktestModuleRegistry):
        modules: list[dict] = sub.module_manifest()
    elif isinstance(sub, ModuleRegistry):
        modules = [_serialize_module(m) for m in sub.sorted_modules()]
    else:
        modules = []
    return {
        "key": module.key,
        "label": module.label,
        "order": module.order,
        "layout": module.layout,
        "modules": modules,
    }


@sft_bp.get("/api/testers/modules")
def get_testers_modules():
    home = HomeModuleRegistry()
    return jsonify({
        "success": True,
        "modules": [_serialize_module(m) for m in home.sorted_modules()],
    })


@sft_bp.get("/api/backtest/settings/<application>")
def get_backtest_setting_application(application: str):
    try:
        settings_manifest = backtest_setting_registry.get(application).manifest()
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    # Merge executable module manifest from the registry
    registry = _registry_for(application)
    settings_manifest["executable_modules"] = registry.module_manifest()
    if application == "single_factor_page":
        settings_manifest["shared_global_default_keys"] = backtest_setting_registry.shared_global_default_keys(
            ("factor_evaluation", "ic_test", "group_test")
        )
    return jsonify({"success": True, **settings_manifest})


@sft_bp.get("/api/backtest/settings/<application>/tabs/<tab_key>")
def get_backtest_setting_tab(application: str, tab_key: str):
    try:
        manifest = backtest_setting_registry.get(application).tab_manifest(tab_key)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    registry = _registry_for(application)
    manifest["executable_modules"] = registry.module_manifest()
    return jsonify({"success": True, **manifest})
