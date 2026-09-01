"""Read-only metadata inspection for source-backed Run inputs."""

from __future__ import annotations

import ast
import hashlib
from typing import Any

from server.modules.shared.factor_param_utils import (
    factor_param_value_display,
    normalize_factor_param_row,
)
from server.services.strategy_plans import normalize_strategy_plan
from server.services.transient_strategy_sources import validate_entries
from tools.testers.backtest.engines.native.strategy import STRATEGY_CALLBACKS


_STRATEGY_BASES = {"Strategy", "BarStrategy", "EventStrategy", "OrderAwareStrategy"}


def family_template_latex(family: Any) -> str:
    """Render the configurable family expression, preserving ParamRef nodes."""
    expression = getattr(family, "expr", None)
    if expression is not None:
        try:
            formula = expression.to_latex()
        except Exception:
            formula = ""
        if formula:
            return str(formula)
    return str(getattr(family, "math_expr", "") or "")


def instantiate_factor_metadata(family: Any, params: Any = None) -> dict[str, Any]:
    """Return factor identity plus template and resolved formula views.

    ``math_expr`` is the family template: parameter references remain visible
    (for example ``\\textcolor{red}{N}``) so the formula describes the
    configurable factor rather than silently turning into its default
    instance.  ``resolved_math_expr`` is retained for callers that need to
    audit the concrete parameterized expression used for this row.
    """
    raw = params if isinstance(params, dict) else {}
    normalized = normalize_factor_param_row(family, raw)
    factor = family.get_factor(**normalized)
    expression = getattr(factor, "_source_expr", None) or getattr(factor, "expr", None)
    resolved_formula = expression.to_latex() if expression is not None else ""
    template_formula = family_template_latex(family)
    return {
        "factor_alias": str(factor.alias),
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "self_formula_fingerprint": expression.semantic_fingerprint(),
        "normalized_params": {
            parameter.alias: factor_param_value_display(
                parameter, normalized.get(parameter.alias),
            )
            for parameter in family.params
        },
        "math_expr": str(template_formula or resolved_formula or ""),
        "resolved_math_expr": str(resolved_formula or ""),
    }


def inspect_strategy_source(value: Any) -> dict[str, Any]:
    """Inspect a Strategy source without executing user code in the HTTP process."""
    if not isinstance(value, dict):
        raise ValueError("strategy inspection requires an object")
    path = str(value.get("path") or "").replace("\\", "/").strip()
    source = value.get("source_code")
    entries = validate_entries([{"path": path, "source_code": source}])
    try:
        tree = ast.parse(entries[0]["source_code"], filename=path)
    except SyntaxError as exc:
        raise ValueError(f"strategy source syntax error: {exc.msg}") from exc
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    candidates = [name for name in classes if _inherits_strategy(name, classes, set())]
    requested = str(value.get("entrypoint") or "").strip()
    if requested:
        if requested not in candidates:
            raise ValueError("strategy entrypoint is not a Strategy subclass")
        entrypoint = requested
    elif len(candidates) == 1:
        entrypoint = candidates[0]
    elif not candidates:
        raise ValueError("strategy source does not define a Strategy subclass")
    else:
        raise ValueError("strategy source has multiple entrypoints; choose one")
    callbacks = sorted(_strategy_methods(entrypoint, classes, set()))
    raw_spec = value.get("strategy_spec")
    if raw_spec is None:
        raw_spec = {
            "source": f"profile:{path}",
            "workspace": "profile",
            "strategy_id": entrypoint,
            "entrypoint": entrypoint,
        }
    elif not isinstance(raw_spec, dict):
        raise ValueError("strategy_spec must be an object")
    else:
        raw_spec = dict(raw_spec)
        raw_spec.setdefault("source", f"profile:{path}")
        raw_spec.setdefault("workspace", "profile")
        raw_spec.setdefault("strategy_id", entrypoint)
        raw_spec.setdefault("entrypoint", entrypoint)
    normalized = normalize_strategy_plan([raw_spec], uploaded_paths=[path])[0]
    normalized["actor_callbacks"] = callbacks
    source_text = str(entries[0]["source_code"])
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    hooks = []
    selected_class = classes.get(entrypoint)
    for node in (selected_class.body if selected_class is not None else []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in STRATEGY_CALLBACKS:
            continue
        start = int(getattr(node, "lineno", 0) or 0)
        end = int(getattr(node, "end_lineno", start) or start)
        hooks.append({
            "name": node.name,
            "lineno": start,
            "end_lineno": end,
            "source": "\n".join(source_text.splitlines()[start - 1:end]) if start else "",
        })
    return {
        "entrypoint": entrypoint,
        "callbacks": callbacks,
        "hooks": hooks,
        "source_sha256": source_hash,
        "source_bytes": len(source_text.encode("utf-8")),
        "requirements": dict(normalized.get("requirements") or {}),
        "strategy_spec": normalized,
    }


def _base_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _inherits_strategy(
    name: str,
    classes: dict[str, ast.ClassDef],
    visiting: set[str],
) -> bool:
    if name in visiting:
        return False
    node = classes.get(name)
    if node is None:
        return False
    visiting = {*visiting, name}
    for base in node.bases:
        base_name = _base_name(base)
        if base_name in _STRATEGY_BASES:
            return True
        if _inherits_strategy(base_name, classes, visiting):
            return True
    return False


def _strategy_methods(
    name: str,
    classes: dict[str, ast.ClassDef],
    visiting: set[str],
) -> set[str]:
    if name in visiting or name not in classes:
        return set()
    visiting = {*visiting, name}
    node = classes[name]
    methods = {
        item.name for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name in STRATEGY_CALLBACKS
    }
    for base in node.bases:
        methods.update(_strategy_methods(_base_name(base), classes, visiting))
    return methods
