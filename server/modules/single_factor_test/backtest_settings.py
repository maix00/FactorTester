"""Backend-owned, lazily loaded backtest setting manifests."""

from __future__ import annotations

from flask import jsonify

from tools.backtest.settings import backtest_setting_registry

from . import sft_bp


@sft_bp.get("/api/backtest/settings/<application>")
def get_backtest_setting_application(application: str):
    try:
        manifest = backtest_setting_registry.get(application).manifest()
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, **manifest})


@sft_bp.get("/api/backtest/settings/<application>/tabs/<tab_key>")
def get_backtest_setting_tab(application: str, tab_key: str):
    try:
        manifest = backtest_setting_registry.get(application).tab_manifest(tab_key)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, **manifest})
