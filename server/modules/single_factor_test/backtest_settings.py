"""Backend-owned, lazily loaded backtest setting manifests.

The manifest now includes `executable_modules` via the ModuleRegistry —
the frontend receives module phase declarations alongside setting schemas.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from tools.testers.backtest.modules.registry import BacktestModuleRegistry
from tools.testers.home import HomeModuleRegistry
from tools.testers.registry import Module, ModuleRegistry
from tools.testers.settings import backtest_setting_registry

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


def _serialize_module(module: Module) -> dict[str, Any]:
    sub = module.sub_registry
    has_children = isinstance(sub, ModuleRegistry)
    if not has_children:
        try:
            has_children = bool(module.app.tabs)
        except Exception:
            has_children = False
    return {
        "key": module.key,
        "label": module.label,
        "order": module.order,
        "layout": module.layout,
        "kind": "module",
        "application": _module_application(module),
        "has_children": has_children,
    }


@sft_bp.get("/api/test-authoring/modules")
def get_testers_modules():
    home = HomeModuleRegistry()
    parent = (request.args.get("parent") or "").strip()
    try:
        modules = _navigation_children(home, parent)
    except (KeyError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({
        "success": True,
        "parent": parent or None,
        "modules": modules,
    })


def _navigation_children(home: HomeModuleRegistry, parent: str) -> list[dict[str, Any]]:
    """Return exactly one frontend navigation layer.

    Frontend navigation modules are user-editable setting surfaces:
      ModuleRegistry Module -> application tabs -> tab public fields.

    Backtest ExecutableModule classes are not exposed as navigation modules;
    they stay in settings manifests as `executable_modules` for execution and
    progress infrastructure.
    """
    if not parent:
        return [_serialize_module(module) for module in home.sorted_modules()]
    if "/" in parent:
        application, tab_key, *rest = parent.split("/")
        if rest:
            return []
        module = home.find(application)
        if module is None:
            raise KeyError(f"unknown module: {application}")
        return _field_nodes(module, tab_key)
    module = home.find(parent)
    if module is None:
        raise KeyError(f"unknown module: {parent}")
    sub = module.sub_registry
    if isinstance(sub, ModuleRegistry) and not isinstance(sub, BacktestModuleRegistry):
        return [_serialize_module(child) for child in sub.sorted_modules()]
    return _tab_nodes(module)


def _tab_nodes(module: Module) -> list[dict[str, Any]]:
    app = module.app
    application = _module_application(module)
    tabs = sorted(app.tabs.values(), key=lambda tab: tab.order)
    return [
        {
            "key": f"{module.key}/{tab.key}",
            "label": tab.label,
            "order": tab.order,
            "kind": "tab",
            "application": application,
            "tab_key": tab.key,
            "layout": tab.layout_template,
            "has_children": any(setting.tab == tab.key for setting in app.settings.values()),
        }
        for tab in tabs
    ]


def _field_nodes(module: Module, tab_key: str) -> list[dict[str, Any]]:
    app = module.app
    application = _module_application(module)
    if tab_key not in app.tabs:
        raise KeyError(f"unknown tab: {module.key}/{tab_key}")
    fields = [
        setting
        for setting in app.settings.values()
        if setting.tab == tab_key
    ]
    fields = sorted(
        fields,
        key=lambda setting: (
            setting.serialization.get("display_order", 1000),
            setting.label,
            setting.key,
        ),
    )
    return [
        {
            "key": f"{module.key}/{tab_key}/{setting.key}",
            "label": setting.label,
            "order": setting.serialization.get("display_order", index),
            "kind": "field",
            "application": application,
            "tab_key": tab_key,
            "field_key": setting.key,
            "value_descriptor": setting.value_descriptor.to_dict(),
            "has_children": False,
        }
        for index, setting in enumerate(fields, start=1)
    ]


def _module_application(module: Module) -> str:
    try:
        application = str(module.app.application)
    except Exception:
        application = ""
    return application or module.key


@sft_bp.get("/api/test-authoring/modules/<application>")
def get_backtest_setting_application(application: str):
    try:
        client = (request.args.get("client") or "web").strip().lower()
        settings_manifest = backtest_setting_registry.get(application).manifest(
            client=client,
        )
    except (KeyError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    # Merge executable module manifest from the registry
    registry = _registry_for(application)
    settings_manifest["executable_modules"] = registry.module_manifest()
    return jsonify({"success": True, **settings_manifest})


@sft_bp.get("/api/test-authoring/modules/<application>/summary")
def get_backtest_setting_application_summary(application: str):
    try:
        client = (request.args.get("client") or "web").strip().lower()
        settings_manifest = backtest_setting_registry.get(application).summary(
            client=client,
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    registry = _registry_for(application)
    settings_manifest["executable_modules"] = registry.module_manifest()
    return jsonify({"success": True, **settings_manifest})


@sft_bp.get("/api/test-authoring/modules/<application>/tabs/<tab_key>")
def get_backtest_setting_tab(application: str, tab_key: str):
    try:
        manifest = backtest_setting_registry.get(application).tab_manifest(tab_key)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    registry = _registry_for(application)
    manifest["executable_modules"] = registry.module_manifest()
    return jsonify({"success": True, **manifest})
