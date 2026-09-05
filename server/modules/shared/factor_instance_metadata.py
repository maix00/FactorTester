"""Build source-free recursive metadata for one parameterized Factor."""

from __future__ import annotations

import re
from typing import Any

from server.modules.shared.factor_param_utils import (
    unique_frozen_factor_records,
)
from server.modules.shared.param_meta import serialize_param_meta
from tools.factors.FactorExpr import ConstExpr
from tools.factors.formula_identity import require_frozen_factor
from tools.parameters import FactorParam

def build_factor_instance_metadata(
    family: Any,
    factor: Any,
    values: dict[str, Any],
    *,
    factor_dependencies: list[dict] | None = None,
    username: str = "",
) -> dict[str, Any]:
    """Return a recursive parameter tree and concrete instance formula.

    Nested factors are represented by their frozen v2 identity.  Source code is
    never copied into this read-only projection; the runtime dependency graph
    remains the authority for reconstructing the expression.
    """
    dependencies = _dependency_index(factor_dependencies or [])
    for value in values.values():
        if isinstance(value, dict) and value.get("schema_version") == 2:
            dependencies.setdefault(require_frozen_factor(value)["ref"], value)
    return _instance_node(
        family, factor, values, dependencies=dependencies,
        username=username, active=set(), final_symbol=_family_symbol(family),
    )

def _instance_node(
    family: Any,
    factor: Any,
    values: dict[str, Any],
    *,
    dependencies: dict[str, dict],
    username: str,
    active: set[str],
    final_symbol: str,
) -> dict[str, Any]:
    rows = []
    for parameter in getattr(family, "params", ()):
        raw = values.get(parameter.alias, getattr(parameter, "default_value", None))
        row = {
            **serialize_param_meta(parameter),
            "value": _display_value(parameter, raw, dependencies),
        }
        record = _nested_record(parameter, raw, dependencies)
        if record is not None:
            child = _nested_node(
                record, dependencies=dependencies, username=username,
                active=active,
            )
            row["nested_factor"] = child
        rows.append(row)

    template = _template_formula(family)
    node = {
        "factor_alias": str(getattr(factor, "alias", "") or ""),
        "factor_family_alias": str(getattr(family, "alias", "") or ""),
        "factor_family_name": str(
            getattr(family, "__class__", type(family)).__name__ or ""
        ),
        "family_formula_fingerprint": str(
            getattr(family, "formula_fingerprint", "")
            or getattr(factor, "family_formula_fingerprint", "") or ""
        ),
        # math_expr stays the self-contained template (parameter references
        # surface as ``\\textcolor{red}{Alias}``), matching the browser's
        # template view.  resolved_math_expr is the fully composed block that
        # the catalog detail page renders directly in view mode.
        "math_expr": template,
        "resolved_math_expr": "",
        "parameter_definitions": rows,
    }
    from server.modules.shared.factor_preview_latex import preview_expression
    node["resolved_math_expr"] = preview_expression(node)
    return node

def _nested_node(
    record: dict,
    *,
    dependencies: dict[str, dict],
    username: str,
    active: set[str],
) -> dict[str, Any]:
    frozen = require_frozen_factor(record)
    factor_ref = frozen["ref"]
    if factor_ref in active:
        raise ValueError(f"FactorParam 依赖形成循环: {factor_ref}")
    active.add(factor_ref)
    try:
        from server.modules.shared.factor_param_resolver import (
            resolve_factor_param_value,
        )
        factor = resolve_factor_param_value(
            record, username=username or None, frozen_by_ref=dependencies,
        )
        family = getattr(factor, "family", None)
        if family is None:
            raise ValueError(f"嵌套因子缺少因子家族: {frozen['alias']}")
        node = _instance_node(
            family, factor, frozen["identity"]["params"],
            dependencies=dependencies, username=username, active=active,
            final_symbol=_family_symbol(family),
        )
        node.update({
            "ref": factor_ref,
            "factor_ref": factor_ref,
            "factor_alias": frozen["alias"],
            "factor_owner_ref": str(record.get("owner_ref") or ""),
            "owner_ref": str(record.get("owner_ref") or ""),
            "family_formula_fingerprint": str(
                frozen["identity"].get("family_formula_fingerprint") or ""
            ),
            "self_formula_fingerprint": str(
                frozen["identity"].get("self_formula_fingerprint") or ""
            ),
            "factor_kind": str(record.get("factor_kind") or ""),
            "source": str(record.get("source") or ""),
            "owner_username": str(record.get("owner_username") or ""),
        })
        return node
    finally:
        active.remove(factor_ref)

def _dependency_index(values: list[dict]) -> dict[str, dict]:
    """Index the merged frozen DAG by canonical dependency identity.

    The outer instance may contain a compact identity-only child while the
    configuration's flattened dependency list contains the same node with
    source/provenance.  Raw dictionary equality is the wrong comparison: the
    frozen identity is authoritative for sameness, and the merge helper keeps
    the complete source and recursive child links.
    """
    result: dict[str, dict] = {}
    for value in unique_frozen_factor_records(values):
        frozen = require_frozen_factor(value)
        result[frozen["ref"]] = value
        for nested in value.get("factor_dependencies") or []:
            nested_frozen = require_frozen_factor(nested)
            result[nested_frozen["ref"]] = nested
    return result

def _nested_record(
    parameter: Any, value: Any, dependencies: dict[str, dict],
) -> dict | None:
    if not isinstance(parameter, FactorParam) or isinstance(value, ConstExpr):
        return None
    if isinstance(value, dict) and value.get("schema_version") == 2:
        return value
    if isinstance(value, str) and value.startswith("factor:v2:"):
        return dependencies.get(value)
    return None

def _display_value(
    parameter: Any, value: Any, dependencies: dict[str, dict],
) -> str:
    record = _nested_record(parameter, value, dependencies)
    if record is not None:
        return require_frozen_factor(record)["alias"]
    if isinstance(value, ConstExpr):
        value = value.value
    try:
        return str(parameter._value_space.alias(value))
    except Exception:
        return "" if value is None else str(value)

def _template_formula(family: Any) -> str:
    expression = getattr(family, "expr", None)
    if expression is not None:
        try:
            return str(expression.to_latex() or "")
        except Exception:
            pass
    return str(getattr(family, "math_expr", "") or "")

def _family_symbol(family: Any) -> str:
    return str(getattr(family, "alias", "") or "Factor")

__all__ = ["build_factor_instance_metadata"]
