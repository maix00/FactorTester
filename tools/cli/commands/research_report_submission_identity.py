"""Stable logical identities for retryable report submissions."""

from __future__ import annotations

from typing import Any


def component_identity(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "add",
        "components": [{
            "component_id": component["component_id"],
        }],
    }


def batch_identity(operations: list[dict[str, Any]]) -> dict[str, Any]:
    if not operations:
        raise ValueError("report batch must contain at least one operation")
    return {
        "operation": "add-batch",
        "operations": [
            _operation_identity(index, item)
            for index, item in enumerate(operations)
        ],
    }


def agent_binding_diagnostic(component_id: str) -> dict[str, Any]:
    return {
        "component_id": component_id or "submission",
        "field": "bindings",
        "line": 1,
        "column": 1,
        "code": "report.binding.agent_forbidden",
        "message": "Agent 不能直接提交引用 binding",
        "rule": "在正文手写完整类型化链接，由 CLI 校验 authority 后生成 binding",
        "example": "[任务](factortester://job/job%3A123)",
    }


def _operation_identity(index: int, operation: Any) -> dict[str, Any]:
    if not isinstance(operation, dict):
        raise ValueError("report batch operation must identify a logical target")
    op = str(operation.get("op") or "")
    target = operation.get("component_id")
    explicit_target = isinstance(target, str) and bool(target.strip())
    if op in {"add", "replace", "bind"} or explicit_target:
        return {
            "position": index, "slot": "component",
            "component_id": target,
        }
    if op == "asset":
        asset = operation.get("asset")
        return {
            "position": index, "op": op,
            "asset_ref": asset.get("asset_ref") if isinstance(asset, dict) else None,
        }
    raise ValueError("report batch operation must identify a logical target")
