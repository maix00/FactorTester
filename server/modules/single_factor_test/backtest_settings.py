"""Backend-owned, lazily loaded backtest setting manifests."""

from __future__ import annotations

from flask import jsonify, request

from server.services import page_runtime
from tools.backtest.settings import backtest_setting_registry

from . import sft_bp


@sft_bp.get("/api/backtest/settings/<application>")
def get_backtest_setting_application(application: str):
    try:
        manifest = backtest_setting_registry.get(application).manifest()
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    page_uuid = str(request.args.get("page_uuid") or "")
    current_time = page_runtime.get_current_time(page_uuid) if page_uuid else None
    if current_time:
        start, end, _start_calc = current_time
        defaults = manifest.get("defaults") or {}
        if "start_date" in defaults:
            defaults["start_date"]["value"] = _date_value(start)
        if "end_date" in defaults:
            defaults["end_date"]["value"] = _date_value(end)
        if "start_time" in defaults:
            defaults["start_time"]["value"] = _time_value(start)
        if "end_time" in defaults:
            defaults["end_time"]["value"] = _time_value(end)
        if "time_precision" in defaults:
            defaults["time_precision"]["value"] = getattr(start, "precision", "exact") or "exact"
        if "timezone" in defaults:
            defaults["timezone"]["value"] = _timezone_value(start)
    return jsonify({"success": True, **manifest})


@sft_bp.get("/api/backtest/settings/<application>/tabs/<tab_key>")
def get_backtest_setting_tab(application: str, tab_key: str):
    try:
        manifest = backtest_setting_registry.get(application).tab_manifest(tab_key)
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, **manifest})


def _date_value(value) -> str:
    timestamp = getattr(value, "ts", value)
    return timestamp.strftime("%Y-%m-%d")


def _time_value(value) -> str:
    timestamp = getattr(value, "ts", value)
    return timestamp.strftime("%H:%M")


def _timezone_value(value) -> str:
    precision = getattr(value, "precision", "exact")
    if precision == "trading_day":
        return ""
    tz = getattr(value, "tz", None)
    if tz:
        return str(tz)
    timestamp = getattr(value, "ts", value)
    tzinfo = getattr(timestamp, "tzinfo", None)
    return str(tzinfo) if tzinfo else "Asia/Shanghai"
