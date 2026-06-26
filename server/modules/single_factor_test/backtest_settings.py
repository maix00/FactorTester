"""Backend-owned, lazily loaded backtest setting manifests.

The manifest now includes `executable_modules` via the ModuleRegistry —
the frontend receives module phase declarations alongside setting schemas.
"""

from __future__ import annotations

from flask import jsonify

from tools.backtest.settings import backtest_setting_registry
from tools.backtest.modules.registry import BacktestModuleRegistry, GroupTestModuleRegistry

from . import sft_bp


def _registry_for(application: str) -> BacktestModuleRegistry:
    """Return the appropriate module registry for an application."""
    if application == "group_test":
        return GroupTestModuleRegistry()
    return BacktestModuleRegistry()


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
