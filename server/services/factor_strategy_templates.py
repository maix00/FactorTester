"""Versioned public factor-strategy templates for NautilusTrader Runs.

Templates are executable contracts, not user-authored source files. Their
definitions live in FactorTester while their events, orders, and positions are
owned by NautilusTrader.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any


_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_ref": "nautilus-factor-strategy:cross-sectional-group",
        "revision_ref": "nautilus-factor-strategy-revision:cross-sectional-group:1",
        "version": 1,
        "kind": "cross_sectional_group",
        "name": "因子横截面分组第 N 组",
        "description": "在每个已完成的横截面时点按因子值稳定排序并等分产品，生成指定组的目标成员。",
        "factor_roles": [{"key": "signal", "label": "分组因子", "required": True}],
        "parameters": [
            {"key": "split_count", "label": "分组数", "type": "integer", "minimum": 2, "maximum": 100},
            {"key": "group_index", "label": "第 N 组", "type": "integer", "minimum": 1, "maximum_from": "split_count"},
        ],
        "execution": "nautilus_strategy",
        "batch_optimization": "同一因子、产品范围、时点和分组数只计算一次因子横截面排序；结果分发给各组策略。",
    },
    {
        "template_ref": "nautilus-factor-strategy:threshold",
        "revision_ref": "nautilus-factor-strategy-revision:threshold:1",
        "version": 1,
        "kind": "threshold",
        "name": "因子阈值买卖策略",
        "description": "因子达到入场阈值时建立方向仓位，回到退出阈值时退出；中间区域保持现有目标。",
        "factor_roles": [{"key": "signal", "label": "信号因子", "required": True}],
        "parameters": [
            {"key": "entry_threshold", "label": "入场阈值（绝对值）", "type": "number", "minimum": 0},
            {"key": "exit_threshold", "label": "退出阈值（绝对值）", "type": "number", "minimum": 0},
            {"key": "side_mode", "label": "方向", "type": "enum", "values": ["long_short", "long_only", "short_only"]},
        ],
        "execution": "nautilus_strategy",
        "batch_optimization": "相同信号因子只发布一次事件时间因子值；各阈值策略在同一发布结果上生成目标。",
    },
)
_BY_REF = {item["template_ref"]: item for item in _TEMPLATES}
_FACTOR_REF = re.compile(r"^factor:v2:[A-Za-z0-9_-]{43}$")
_ROLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def factor_strategy_catalog() -> dict[str, Any]:
    """Return static public templates; this path does not inspect user data."""
    return {
        "success": True,
        "scope": "public",
        "items": [
            {
                **item,
                "library_scope": "public",
                "library_kind": "factor_strategy_template",
                "read_only": True,
            }
            for item in _TEMPLATES
        ],
    }


def normalize_factor_bindings(value: object, *, field: str = "factor_bindings") -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must map role names to frozen factor:v2 refs")
    result: dict[str, str] = {}
    for raw_role, raw_ref in value.items():
        role = str(raw_role or "").strip()
        ref = str(raw_ref or "").strip()
        if not _ROLE.fullmatch(role):
            raise ValueError(f"{field} contains an invalid factor role: {role!r}")
        if not _FACTOR_REF.fullmatch(ref):
            raise ValueError(f"{field}.{role} must be an immutable factor:v2 reference")
        if role in result:
            raise ValueError(f"{field} contains a duplicate role: {role}")
        result[role] = ref
    if not result:
        raise ValueError(f"{field} must bind at least one factor")
    return dict(sorted(result.items()))


def normalize_factor_strategy_binding(
    raw: object,
    *,
    available_factor_refs: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("factor strategy binding must be an object")
    template_ref = str(raw.get("template_ref") or "").strip()
    template = _BY_REF.get(template_ref)
    if template is None:
        raise ValueError(f"unknown public factor strategy template: {template_ref}")
    revision_ref = str(raw.get("revision_ref") or "").strip()
    if revision_ref != template["revision_ref"]:
        raise ValueError("public factor strategy revision is missing or unsupported")
    strategy_id = str(raw.get("strategy_id") or raw.get("target_strategy_id") or "").strip()
    binding_id = str(raw.get("binding_id") or "").strip()
    if not strategy_id or len(strategy_id) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in strategy_id):
        raise ValueError("factor strategy requires a bounded strategy_id")
    if not binding_id or len(binding_id) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in binding_id):
        raise ValueError("factor strategy requires a bounded binding_id")
    factor_bindings = normalize_factor_bindings(raw.get("factor_bindings"))
    required_roles = {
        str(item["key"]) for item in template["factor_roles"] if item.get("required")
    }
    if not required_roles.issubset(factor_bindings):
        raise ValueError("factor strategy is missing required factor roles: " + ", ".join(sorted(required_roles - set(factor_bindings))))
    if available_factor_refs is not None:
        missing = set(factor_bindings.values()) - set(available_factor_refs)
        if missing:
            raise ValueError("factor strategy references factors not frozen in this configuration: " + ", ".join(sorted(missing)))
    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise ValueError("factor strategy parameters must be an object")
    normalized_parameters = _normalize_parameters(template, parameters)
    return {
        "strategy_id": strategy_id,
        "binding_id": binding_id,
        "strategy_kind": "factor_template",
        "template_kind": template["kind"],
        "template_ref": template_ref,
        "revision_ref": revision_ref,
        "template_version": template["version"],
        "factor_bindings": factor_bindings,
        "parameters": normalized_parameters,
        "requirements": {},
    }


def normalize_factor_template_plan(raw: object) -> dict[str, Any]:
    """Validate the source-free form stored in a canonical RunSpec plan."""
    if not isinstance(raw, Mapping):
        raise ValueError("factor strategy plan must be an object")
    source = raw.get("source")
    if source != "factor-template":
        raise ValueError("public factor strategy plan must use the factor-template source")
    value = normalize_factor_strategy_binding(raw)
    return {
        **value,
        "source": "factor-template",
        "source_kind": "factor_template",
        "source_name": value["template_ref"],
        "strategy_origin": "public_factor_strategy",
    }


def compile_factor_strategy_bindings(
    configuration: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = configuration.get("payload") if isinstance(configuration.get("payload"), dict) else configuration
    if not isinstance(payload, dict):
        raise ValueError("strategy configuration must be an object")
    shared = payload.get("shared") or {}
    analyses = payload.get("analyses") or {}
    backtest = analyses.get("backtest") or {}
    if not isinstance(shared, dict) or not isinstance(backtest, dict):
        raise ValueError("factor strategy requires shared and backtest configuration objects")
    raw_factors = shared.get("factors") or []
    if not isinstance(raw_factors, list):
        raise ValueError("shared.factors must be an array of frozen factor records")
    available: set[str] = set()
    for item in raw_factors:
        if not isinstance(item, Mapping):
            raise ValueError("shared.factors contains a non-object record")
        ref = str(item.get("ref") or "").strip()
        if not _FACTOR_REF.fullmatch(ref):
            raise ValueError("all factors referenced by a strategy must be frozen factor:v2 records")
        available.add(ref)
    bindings = backtest.get("factor_strategy_bindings") or []
    if not isinstance(bindings, list):
        raise ValueError("analyses.backtest.factor_strategy_bindings must be an array")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in bindings:
        item = normalize_factor_strategy_binding(raw, available_factor_refs=available)
        if item["strategy_id"] in seen_ids:
            raise ValueError(f"duplicate strategy_id: {item['strategy_id']}")
        seen_ids.add(item["strategy_id"])
        result.append({"source": "factor-template", **item})
    return result


def _normalize_parameters(template: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    specs = {str(item["key"]): item for item in template["parameters"]}
    unknown = set(raw) - set(specs)
    if unknown:
        raise ValueError("unknown factor strategy parameter: " + ", ".join(sorted(map(str, unknown))))
    result: dict[str, Any] = {}
    for key, spec in specs.items():
        if key not in raw:
            raise ValueError(f"factor strategy parameter is required: {key}")
        value = raw[key]
        kind = spec["type"]
        if kind == "integer":
            if isinstance(value, bool):
                raise ValueError(f"{key} must be an integer")
            try:
                number = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            if str(value).strip() not in {str(number), f"{number}.0"}:
                raise ValueError(f"{key} must be an integer")
            if number < int(spec["minimum"]):
                raise ValueError(f"{key} must be at least {spec['minimum']}")
            maximum = int(result.get(spec.get("maximum_from") or "", spec.get("maximum", 2**31 - 1)))
            if number > maximum:
                raise ValueError(f"{key} must be no greater than {maximum}")
            result[key] = number
        elif kind == "number":
            if isinstance(value, bool):
                raise ValueError(f"{key} must be a finite number")
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{key} must be a finite number") from exc
            if not math.isfinite(number) or number < float(spec.get("minimum", -math.inf)):
                raise ValueError(f"{key} must be a finite number at or above {spec.get('minimum', '-infinity')}")
            result[key] = number
        elif kind == "enum":
            selected = str(value or "")
            if selected not in spec["values"]:
                raise ValueError(f"{key} is not an allowed value")
            result[key] = selected
    if template["kind"] == "threshold" and result["exit_threshold"] > result["entry_threshold"]:
        raise ValueError("exit_threshold must not exceed entry_threshold")
    if template["kind"] == "cross_sectional_group" and result["group_index"] > result["split_count"]:
        raise ValueError("group_index must not exceed split_count")
    return result


__all__ = [
    "compile_factor_strategy_bindings",
    "factor_strategy_catalog",
    "normalize_factor_bindings",
    "normalize_factor_strategy_binding",
    "normalize_factor_template_plan",
]
