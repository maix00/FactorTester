"""Business-port API for the staged NautilusTrader workbench."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from server.services.nautilus_bridge.capabilities import native_capabilities
from server.services.nautilus_bridge.config import (
    UnsupportedExecutionConfig,
    compile_frozen_execution_plan,
)
from server.services.session_runtime import current_user

nautilus_workbench_bp = Blueprint("nautilus_workbench", __name__)


@nautilus_workbench_bp.get("/api/nautilus/capabilities")
def capabilities():
    """Expose installed support, without promising an unconfigured trading mode."""
    if current_user() is None:
        return jsonify({"error": "authentication required"}), 401
    return jsonify(native_capabilities())


@nautilus_workbench_bp.post("/api/nautilus/config/preview")
def preview_configuration():
    """Show the new execution contract without creating a Run or a Job.

    This endpoint deliberately remains fail-closed until the frozen contract
    is connected to a NautilusTrader worker.  The browser preview is advisory;
    the durable Run endpoints must independently enforce engine selection.
    """
    if current_user() is None:
        return jsonify({"error": "authentication required"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("analysis_kind") != "backtest":
        return jsonify({"error": "analysis_kind=backtest is required"}), 400
    configuration = body.get("configuration")
    if not isinstance(configuration, dict):
        return jsonify({"error": "configuration must be an object"}), 400
    analysis = ((configuration.get("analyses") or {}).get("backtest") or {})
    execution = analysis.get("execution") if isinstance(analysis, dict) else None
    settings = execution.get("settings") if isinstance(execution, dict) else None
    if not isinstance(settings, dict):
        return jsonify({"error": "backtest execution.settings is required"}), 400

    if execution.get("backend") != "nautilus_trader" or execution.get("contract_version") != 4:
        return jsonify({
            "error": "NautilusTrader backtest requires execution contract version 4",
            "code": "unsupported_execution_contract_version",
        }), 400

    blockers: list[dict[str, str]] = []
    fields: list[dict[str, Any]] = []
    manifest: dict[str, object] = {}
    canonical = settings
    if "data_source_ref" not in settings:
        try:
            # Reuse the same server-side freeze boundary used when creating a
            # RunSpec. The browser cannot claim that a source adapter or
            # exchange rule set is supported.
            from server.modules.shared.run_spec_resolution.freezing import (
                freeze_nautilus_execution_policy,
            )

            frozen = freeze_nautilus_execution_policy({"payload": configuration})
            frozen_backtest = frozen["payload"]["analyses"]["backtest"]
            compiled_contract = frozen_backtest["execution"].get("nautilus_contract")
            if not isinstance(compiled_contract, dict):
                raise ValueError("RunSpec 未生成 Nautilus 执行合同")
            fields.extend({
                "path": f"execution.nautilus.{item['path']}",
                "label": item.get("label") or item["path"],
                "status": item["status"],
                **{
                    key: item[key]
                    for key in ("value", "section", "review_section", "type", "note")
                    if key in item
                },
                **({"reason": item["reason"]} if item.get("reason") else {}),
            } for item in compiled_contract.get("fields", []))
            blockers.extend({
                "path": f"execution.nautilus.{item['path']}",
                "reason": item["reason"],
            } for item in compiled_contract.get("blockers", []))
            canonical = compiled_contract.get("settings") or {}
        except (ValueError, KeyError, TypeError) as exc:
            blockers.append({
                "path": "execution.settings",
                "reason": f"无法冻结 Nautilus RunSpec：{exc}",
            })
    if not blockers:
        try:
            # Feed kind and tested adapter capabilities are service-owned.
            # Client values cannot promote an adapter to supported.
            plan = compile_frozen_execution_plan(
                canonical, feed_kind="bar",
                adapter_capabilities=frozenset({"native_bar_open_market_orders"}),
            )
            manifest = plan.manifest()
        except UnsupportedExecutionConfig as exc:
            blockers.append({"path": f"execution.settings.{exc.field}", "reason": exc.reason})
            fields.append({
                "path": f"execution.settings.{exc.field}", "label": exc.field,
                "status": "unsupported", "reason": exc.reason,
            })
    blockers.append({
        "path": "execution.engine",
        "reason": "NautilusTrader Job execution is not connected on this service",
    })
    fields.append({
        "path": "execution.engine", "label": "回测引擎",
        "status": "unsupported",
        "reason": "NautilusTrader Job execution is not connected on this service",
    })
    return jsonify({
        "engine": "nautilus_trader", "ready": False,
        "effective_configuration": manifest,
        "fields": fields, "blockers": blockers,
    })
