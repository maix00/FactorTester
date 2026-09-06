"""Read-only metadata inspection for source-backed Run inputs."""

from __future__ import annotations

from typing import Any

from server.modules.shared.factor_param_utils import (
    factor_param_value_display,
    frozen_factor_dependencies,
    frozen_factor_records_from_values,
    normalize_factor_param_row,
    unique_frozen_factor_records,
)
from server.services.strategy_plans import normalize_strategy_plan
from server.services.strategy_source_inspection import inspect_source
from server.services.transient_strategy_sources import validate_entries


def family_template_latex(family: Any) -> str:
    """Render the configurable family expression, preserving ParamRef nodes."""
    template = str(getattr(family, "math_expr", "") or "")
    if template:
        return template
    expression = getattr(family, "expr", None)
    if expression is not None:
        try:
            formula = expression.to_latex()
        except Exception:
            formula = ""
        if formula:
            return str(formula)
    return str(getattr(family, "math_expr", "") or "")


def instantiate_factor_metadata(
    family: Any, params: Any = None, *, username: str | None = None,
) -> dict[str, Any]:
    """Return factor identity plus template and resolved formula views.

    ``math_expr`` is the family template: parameter references remain visible
    (for example ``\\textcolor{red}{N}``) so the formula describes the
    configurable factor rather than silently turning into its default
    instance.  ``resolved_math_expr`` is retained for callers that need to
    audit the concrete parameterized expression used for this row.
    """
    raw = params if isinstance(params, dict) else {}
    raw_dependencies = frozen_factor_records_from_values(raw)
    frozen_by_ref = {value['ref']: value for value in raw_dependencies}
    try:
        from server.services.session_runtime import current_user
        session_user = current_user()
    except Exception:
        # Migration/background threads have no HTTP request context; the
        # caller then must pass username explicitly.
        session_user = None
    principal = str(
        username
        or session_user
        or getattr(family, 'owner_ref', '')
        or '',
    ).strip().removeprefix('principal:')
    from server.modules.shared.factor_param_resolver import resolve_factor_param_value
    from tools.factors.factor_param_resolution import factor_param_resolver_scope
    with factor_param_resolver_scope(lambda value: resolve_factor_param_value(
        value, username=principal or None, frozen_by_ref=frozen_by_ref,
    )):
        normalized = normalize_factor_param_row(family, raw)
        factor = family.get_factor(**normalized)
    expression = getattr(factor, "_source_expr", None) or getattr(factor, "expr", None)
    resolved_formula = expression.to_latex() if expression is not None else ""
    template_formula = family_template_latex(family)
    dependencies = unique_frozen_factor_records([
        *raw_dependencies,
        *frozen_factor_dependencies(family.params, normalized),
    ])
    from server.modules.shared.factor_instance_metadata import (
        build_factor_instance_metadata,
    )
    instance = build_factor_instance_metadata(
        family, factor, normalized, factor_dependencies=dependencies,
    )
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
        # math_expr = 因子家族的_LATEX模板_（自包含，参数以 \textcolor{red}{alias} 占位，未做
        # 参数替换/嵌套叠加）。resolved_math_expr = 参数解析+嵌套因子叠加后的完整公式。
        # 前端查看模式渲染 resolved_math_expr；编辑/新建模式用 math_expr(模板)+参数列表现场叠加。
        "math_expr": str(template_formula or resolved_formula or ""),
        "resolved_math_expr": str(
            instance.get("resolved_math_expr") or resolved_formula or ""
        ),
        "parameter_definitions": instance.get("parameter_definitions") or [],
    }


def inspect_strategy_source(value: Any) -> dict[str, Any]:
    """Inspect a Strategy source without executing user code in the HTTP process."""
    if not isinstance(value, dict):
        raise ValueError("strategy inspection requires an object")
    path = str(value.get("path") or "").replace("\\", "/").strip()
    source = value.get("source_code")
    entries = validate_entries([{"path": path, "source_code": source}])
    requested = str(value.get("entrypoint") or "").strip()
    try:
        inspection = inspect_source(
            entries[0]["source_code"], requested or None,
        )
    except ValueError as exc:
        if str(exc).startswith("strategy source has invalid Python syntax"):
            detail = str(exc).split(": ", 1)[-1]
            raise ValueError(f"strategy source syntax error: {detail}") from exc
        if requested and (
            "class not found" in str(exc) or "not a native Strategy" in str(exc)
        ):
            raise ValueError("strategy entrypoint is not a Strategy subclass") from exc
        raise
    entrypoint = inspection["entrypoint"]
    callbacks = list(inspection["callbacks"])
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
    return {
        "entrypoint": entrypoint,
        "callbacks": callbacks,
        "hooks": inspection["hooks"],
        "effective_hooks": inspection.get(
            "effective_hooks", inspection["hooks"],
        ),
        "source_sha256": inspection["source_sha256"],
        "source_bytes": inspection["source_bytes"],
        "requirements": dict(normalized.get("requirements") or {}),
        "strategy_spec": normalized,
    }
