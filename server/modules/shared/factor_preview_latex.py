"""1:1 backend port of the frontend factor-preview LaTeX composer.

This module mirrors ``server/manager/web/catalog/factor-detail-shared.js``
(``previewExpression`` and its helpers) so the backend can produce exactly the
composed LaTeX string the browser renders for a factor instance.

The frontend algorithm starts from the *template* ``math_expr`` (self-contained
expression whose parameter references surface as ``\\textcolor{red}{Alias}``),
then walks the parameter rows, substituting scalar values in red and expanding
nested factor references recursively as blue family-name intermediate
definitions.  The result is an ``aligned`` block for the root + every nested
definition.

———— 字段语义（全仓库统一，勿混淆）————
- ``math_expr``          = 因子家族_LaTeX模板_：自包含表达式，参数以 \\textcolor{red}{alias} 占位，
                           尚未做参数替换 / 嵌套因子叠加。它是叠加的**输入**，供编辑/新建预览起点。
- ``resolved_math_expr`` = **叠加后_输出_**：用 math_expr(模板)+参数列表做参数替换 + 递归展开嵌套
                           因子家族得到的完整公式。前端**查看模式**直接渲染它。
- 两者为「输入 / 输出」，绝不可互换：前端叠加函数读 math_expr(模板)作起点，查看模式渲染 resolved。

Everything below is a faithful translation of the JavaScript in
``factor-detail-shared.js``.  ``preview_expression`` is the public entry point;
it accepts a factor object (a ``dict`` mirroring the frontend factor payload)
and an optional ``parameter_values`` map, and returns the composed string.
"""

from __future__ import annotations

import json
import re
from typing import Any


# Version of the backend renderer that materializes ``resolved_math_expr``.
# Account-domain mirrors compare this marker before reusing a frozen formula;
# bump it whenever the resolved-formula semantics change.  The view page must
# continue to render the persisted resolved value instead of repairing it in
# JavaScript.
RESOLVED_MATH_EXPR_VERSION = 2


# Sentinel used to distinguish "attribute present with value None" from
# "attribute absent" (JavaScript's ``undefined``).
_UNDEF = object()

_DURATION_RE = re.compile(
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ns|us|ms|s|min|m|h|d|w)",
    re.IGNORECASE,
)
# Characters that a ``latex_value`` body must backslash-escape.
_LATEX_ESCAPE_CHARS = set("_{}%&#$")


def _get(value: Any, key: str, default: Any = None) -> Any:
    """Read ``value[key]`` from a dict/object, returning ``default`` when absent."""
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(key, default)
    if hasattr(value, key):
        return getattr(value, key, default)
    return default


def _undef(value: Any, key: str) -> Any:
    """Read ``value[key]`` returning ``_UNDEF`` when absent (JS ``undefined``)."""
    if value is None:
        return _UNDEF
    if isinstance(value, dict):
        return value.get(key, _UNDEF)
    if hasattr(value, key):
        return getattr(value, key)
    return _UNDEF


def _has(value: Any, key: str) -> bool:
    """JavaScript ``Object.prototype.hasOwnProperty`` equivalent."""
    if value is None:
        return False
    if isinstance(value, dict):
        return key in value
    return hasattr(value, key)


def _is_object(value: Any) -> bool:
    """JavaScript ``typeof value === \"object\" && value`` equivalent."""
    return value is not None and not isinstance(
        value, (str, int, float, bool, bytes, type(None))
    )


def unwrap_family_draft(value: Any) -> Any:
    """Return ``value.__factor_family`` when it is a family draft, else value."""
    if (
        _is_object(value)
        and _get(value, "__factor_family_draft") is True
        and _get(value, "__factor_family")
    ):
        return _get(value, "__factor_family")
    return value


def expression(value: Any, options: dict | None = None) -> str:
    """First non-empty trimmed string field, mirroring JS ``expression``."""
    options = options or {}
    keys = (
        ["resolved_math_expr", "math_expr", "formula", "latex", "factor_expr", "expression"]
        if options.get("instance") is True
        else ["math_expr", "formula", "latex", "factor_expr", "expression", "resolved_math_expr"]
    )
    if not _is_object(value):
        return ""
    for key in keys:
        candidate = _undef(value, key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def strip_formula_environment(value: Any) -> str:
    """Strip a leading ``aligned``/``align*`` environment, if present."""
    result = str(value or "").strip()
    for opening, closing in [
        (r"\begin{aligned}", r"\end{aligned}"),
        (r"\begin{align*}", r"\end{align*}"),
    ]:
        if result.startswith(opening) and result.endswith(closing):
            result = result[len(opening): -len(closing)].strip()
            break
    return result


def family_symbol(value: Any) -> str:
    """Return ``\\mathrm{<safe alias>}`` for the factor family."""
    item = unwrap_family_draft(value)
    alias = str(
        _get(item, "factor_family_alias")
        or _get(item, "family_alias")
        or (_get(item, "identity") and _get(_get(item, "identity"), "family_alias"))
        or _get(item, "name")
        or "Factor",
    )
    # JS : /[^\p{L}\p{N}]+/gu  == replace runs of non-alphanumerics with "_"
    # Non-alphanumeric = non-word chars OR underscore -> [\W_]
    safe = re.sub(r"[\W_]+", "_", alias, flags=re.UNICODE)
    safe = re.sub(r"^_+|_+$", "", safe)
    return "\\mathrm{" + (safe or "Factor") + "}"


def blue(value: Any) -> str:
    return "\\textcolor{blue}{" + str(value) + "}"


def _red(value: Any) -> str:
    return "\\textcolor{red}{" + str(value) + "}"


def latex_value(value: Any) -> str:
    """JS ``latexValue``: duration renders ``N\\,unit``, else ``\\mathrm{escaped}``."""
    text = "" if value is None else str(value)
    duration = _DURATION_RE.fullmatch(text)
    if duration:
        return f"{duration.group(1)}\\," + f"\\mathrm{{{duration.group(2)}}}"
    escaped = "".join(
        "\\" + char if char in _LATEX_ESCAPE_CHARS else char for char in text
    )
    return "\\mathrm{" + escaped + "}"


def preview_scalar_value(value: Any) -> Any:
    """JS ``previewScalarValue``: pull ``alias``/``factor_alias``/``value`` off an object."""
    if not _is_object(value):
        return value
    for key in ("alias", "factor_alias", "value"):
        v = _undef(value, key)
        if v is not None and v is not _UNDEF:
            return v
    return value


def specific_parameter_type(parameter: Any) -> bool:
    """JS ``specificParameterType``: type present and not the generic ``Parameter``."""
    kind = str(
        _get(parameter, "type") or _get(parameter, "param_type") or ""
    ).strip()
    return bool(kind and kind != "Parameter")


def parameter_value_map(item: Any) -> dict[str, Any]:
    """JS ``parameterValueMap``: flatten compact/identity/editor parameter values."""
    result: dict[str, Any] = {}

    def collect(source: Any, allow_empty: bool = False) -> None:
        if isinstance(source, list):
            for parameter in source:
                if not _is_object(parameter):
                    continue
                alias = str(
                    _get(parameter, "alias") or _get(parameter, "name") or ""
                ).strip()
                if not alias or not _has(parameter, "value"):
                    continue
                value = _get(parameter, "value")
                if allow_empty or (value is not None and value != "" and value != _UNDEF):
                    result[alias] = value
            return
        if not _is_object(source) or isinstance(source, (list, tuple)):
            return
        entries = source.items() if isinstance(source, dict) else []
        for raw_alias, parameter in entries:
            alias = str(raw_alias or "").strip()
            if not alias:
                continue
            if _is_object(parameter) and _has(parameter, "value"):
                value = _get(parameter, "value")
            else:
                value = parameter
            if allow_empty or (value is not None and value != "" and value != _UNDEF):
                result[alias] = value

    collect(_get(item, "params"))
    collect(_get(item, "factor_params"))
    identity = _get(item, "identity")
    collect(_get(identity, "params") if _is_object(identity) else None)
    collect(_get(item, "parameter_values"), True)
    return result


def normalize_parameter_row(parameter: Any, values: dict[str, Any]) -> list[dict[str, Any]]:
    """JS ``normalizeParameterRow``."""
    alias = str(
        _get(parameter, "alias") or _get(parameter, "name") or ""
    ).strip()
    if not alias:
        return []
    has_value = alias in values
    fallback = _undef(parameter, "value")
    if fallback is _UNDEF:
        fallback = _undef(parameter, "default_value")
        if fallback is _UNDEF:
            fallback = ""
    value = values.get(alias) if has_value else ("" if fallback is _UNDEF else fallback)

    p_value = _get(parameter, "value")
    nested_factor = (
        _get(parameter, "nested_factor")
        or (_get(p_value, "nested_factor") if _is_object(p_value) else None)
        or (
            p_value
            if _is_object(p_value)
            and _get(p_value, "__factor_family_draft") is True
            and _get(p_value, "__factor_family")
            else None
        )
        or (
            p_value
            if _is_object(p_value) and is_nested_preview_value(p_value)
            else None
        )
        or (
            p_value
            if _is_object(p_value)
            and _get(p_value, "schema_version") == 2
            and _is_object(_get(p_value, "identity"))
            else None
        )
    )
    return [{
        "alias": alias,
        "value": value,
        "default_value": _get(parameter, "default_value"),
        "input_mode": _get(parameter, "input_mode") or "",
        "options": _get(parameter, "options") or [],
        "type": _get(parameter, "type") or _get(parameter, "param_type") or "Parameter",
        "input_help": _get(parameter, "input_help") or _get(parameter, "help_text") or "",
        "redacted": _get(parameter, "redacted") is True,
        "description": _get(parameter, "desc") or _get(parameter, "value_space_desc") or "",
        "nested_factor": nested_factor,
    }]


def parameter_rows(value: Any, options: dict | None = None) -> list[dict[str, Any]]:
    """JS ``parameterRows``."""
    options = options or {}
    item = value or {}
    family = (
        options.get("family")
        or _get(item, "family")
        or _get(item, "__factor_family")
        or None
    )
    candidates = [
        _get(item, "parameter_definitions"),
        _get(item, "family_parameter_definitions"),
        _get(family, "parameter_definitions"),
        _get(family, "params"),
        _get(item, "params"),
        _get(item, "factor_params"),
        _get(item, "parameters"),
    ]
    arrays = [c for c in candidates if isinstance(c, list) and len(c)]

    def specific(p: Any) -> bool:
        return _is_object(p) and specific_parameter_type(p)

    def has_defaults(p: Any) -> bool:
        return _is_object(p) and _undef(p, "default_value") is not _UNDEF

    specific_arr = next((c for c in arrays if any(specific(p) for p in c)), None)
    with_defaults = next((c for c in arrays if any(has_defaults(p) for p in c)), None)
    raw = specific_arr or with_defaults or (arrays[0] if arrays else None)
    if raw is None:
        raw = next(
            (
                c for c in candidates
                if _is_object(c) and not isinstance(c, list) and len(c) > 0
            ),
            None,
        )
    values = parameter_value_map(item)
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for p in raw:
            out.extend(normalize_parameter_row(p, values))
        return out
    if _is_object(raw) and not isinstance(raw, list):
        out = []
        entries = raw.items() if isinstance(raw, dict) else []
        for alias, p in entries:
            if _is_object(p):
                merged = dict(p) if isinstance(p, dict) else {}
                merged.setdefault("alias", _get(p, "alias") or alias)
                out.extend(normalize_parameter_row(merged, values))
            else:
                out.extend(normalize_parameter_row({"alias": alias, "value": p}, values))
        return out
    return []


def _parameter_values(value: Any) -> dict[str, Any]:
    """JS ``parameterValues``: alias -> value (dropping empty values)."""
    out: dict[str, Any] = {}
    for parameter in parameter_rows(value):
        alias = _get(parameter, "alias")
        current = _undef(parameter, "value")
        if current is _UNDEF:
            current = _undef(parameter, "default_value")
        if current is _UNDEF:
            current = ""
        if alias and current != "" and current is not None:
            out[alias] = current
    return out


parameter_values = _parameter_values


def is_nested_preview_value(value: Any) -> bool:
    """JS ``isNestedPreviewValue``."""
    if not _is_object(value):
        return False
    schema_raw = _undef(value, "schema_version")
    try:
        schema_number = int(schema_raw) if schema_raw not in (None, _UNDEF) else None
    except (TypeError, ValueError):
        schema_number = None
    return bool(
        schema_number == 2
        or _get(value, "ref")
        or _get(value, "factor_ref")
        or _get(value, "factor_family_alias")
        or _get(value, "family_alias")
        or _get(value, "math_expr")
        or _get(value, "resolved_math_expr")
    )


def nested_parameter_values(value: Any) -> dict[str, Any]:
    """JS ``nestedParameterValues``."""
    if _is_object(value) and _get(value, "__factor_family_draft") is True:
        return _get(value, "parameter_values") or {}
    identity = _get(value, "identity")
    identity_values = _get(identity, "params") if _is_object(identity) else {}
    identity_values = identity_values or {}
    out: dict[str, Any] = {}
    for parameter in parameter_rows(value):
        alias = _get(parameter, "alias")
        if not alias:
            continue
        value_from_row = _undef(parameter, "value")
        if value_from_row is _UNDEF or value_from_row == "":
            iv = identity_values.get(alias, "")
            out[alias] = "" if iv is None else iv
        else:
            out[alias] = value_from_row
    return {k: v for k, v in out.items() if k}


def preview_node_key(value: Any, parameter_values: dict | None = None) -> str:
    """JS ``previewNodeKey``: identity + JSON of parameter values."""
    parameter_values = parameter_values or {}
    item = unwrap_family_draft(value)
    identity = (
        _get(item, "ref")
        or _get(item, "factor_ref")
        or _get(item, "factor_alias")
        or _get(item, "alias")
        or _get(item, "family_ref")
        or _get(item, "factor_family_alias")
        or _get(item, "family_alias")
        or ""
    )
    if not identity:
        return ""
    try:
        values_str = json.dumps(
            parameter_values, sort_keys=True, ensure_ascii=False, default=str,
        )
    except (TypeError, ValueError):
        values_str = ""
    return str(identity) + "|" + values_str


def nested_preview_value(raw: Any, parameter: Any) -> dict | None:
    """JS ``nestedPreviewValue`` -> ``{"value", "values"}`` or None."""
    if _is_object(raw) and _get(raw, "__factor_family_draft") is True and _get(raw, "__factor_family"):
        return {
            "value": _get(raw, "__factor_family"),
            "values": _get(raw, "parameter_values") or {},
        }
    if is_nested_preview_value(raw):
        return {"value": raw, "values": nested_parameter_values(raw)}
    raw_nested = _get(raw, "nested_factor")
    if is_nested_preview_value(raw_nested):
        return {"value": raw_nested, "values": nested_parameter_values(raw_nested)}
    param_nested = _get(parameter, "nested_factor")
    if is_nested_preview_value(param_nested):
        return {"value": param_nested, "values": nested_parameter_values(param_nested)}
    return None


def child_definition(symbol: str, line: Any, align: bool, punctuation: str = "") -> str:
    """JS ``childDefinition``."""
    clean = str(line).strip()
    clean = re.sub(r"[.;]\s*$", "", clean)
    output = re.match(r"^(?:X|\\mathrm{X})_t\s*&?\s*:=\s*(.+)$", clean)
    prefix = "" if (output or "&" in clean) else ("& " if align else "")
    return f"{prefix}{symbol}_t := {output.group(1) if output else clean}{punctuation}"


def append_preview_definition(
    lines: list[str], nested: dict, state: dict,
) -> None:
    """JS ``appendPreviewDefinition``."""
    key = preview_node_key(nested["value"], nested.get("values") or {})
    if key and (key in state["active"] or key in state["emitted"]):
        return
    if key:
        state["active"].add(key)
        state["emitted"].add(key)
    rendered = render_preview_node(
        nested["value"], nested.get("values") or {}, state,
    )
    if key:
        state["active"].discard(key)
    lines.extend(rendered["lines"])
    body = strip_formula_environment(rendered["body"])
    if body:
        body_lines = [line.strip() for line in re.split(r"\s*\\\\\s*", body)]
        body_lines = [line for line in body_lines if line]
        symbol = blue(family_symbol(nested["value"]))
        if len(body_lines) > 1:
            body_lines[-1] = child_definition(
                symbol, body_lines[-1], False, ";",
            )
            lines.extend(body_lines)
        else:
            lines.append(child_definition(symbol, body, True, ";"))


def render_preview_node(
    value: Any, parameter_values: dict | None = None, state: dict | None = None,
) -> dict[str, Any]:
    """JS ``renderPreviewNode`` -> ``{"body", "lines"}``."""
    parameter_values = parameter_values or {}
    state = state or {"active": set(), "emitted": set()}
    item = unwrap_family_draft(value)
    result_value = expression(item)
    if not result_value:
        return {"body": "", "lines": []}
    result = result_value
    lines: list[str] = []
    rows = parameter_rows(item)
    reverse_value = parameter_values.get("$Rev", next(
        (row.get("value") for row in rows if row.get("alias") == "$Rev"), None,
    ))
    reversed_signal = str(reverse_value).strip().lower() in {
        "1", "-1", "true", "t", "yes", "y", "rev", "reverse",
    }
    signal = r"\operatorname{Resample}_{\textcolor{red}{\$F}}"
    signal_prefix = r"\operatorname{Resample}_"
    reverse_signal = reversed_signal and signal_prefix in result
    if reverse_signal:
        if r"\textcolor{red}{-}" + signal in result:
            pass
        elif signal in result:
            result = result.replace(signal, r"\textcolor{red}{-}" + signal, 1)
        else:
            position = result.find(signal_prefix)
            result = result[:position] + r"\textcolor{red}{-}" + result[position:]
    for parameter in rows:
        alias = str(_get(parameter, "alias") or "").strip()
        if not alias:
            continue
        raw = parameter_values.get(alias) if alias in parameter_values else _get(parameter, "value")
        nested = nested_preview_value(raw, parameter)
        if nested:
            shown = blue(family_symbol(nested["value"]))
            append_preview_definition(lines, nested, state)
        else:
            # JS: latexValue(raw === "" || raw == null ? alias : previewScalarValue(raw))
            shown = (
                r"\$F" if alias == "$F" and (raw == "" or raw is None)
                else latex_value(
                    alias if (raw == "" or raw is None) else preview_scalar_value(raw),
                )
            )
        for spelling in {alias, alias.replace("$", r"\$")}:
            token = "\\textcolor{red}{" + spelling + "}"
            result = result.replace(token, shown if nested else _red(shown))
    if reversed_signal and not reverse_signal:
        body = strip_formula_environment(result)
        parts = body.split(r"\\")
        last = parts.pop().strip()
        assignment = last.find(":=")
        prefix = "" if assignment < 0 else last[:assignment + 2] + " "
        operand = (last if assignment < 0 else last[assignment + 2:]).strip()
        punctuation = operand[-1:] if operand[-1:] in {".", ",", ";"} else ""
        parts.append(prefix + r"\textcolor{red}{-}\left("
                     + (operand[:-1] if punctuation else operand) + r"\right)" + punctuation)
        aligned = body != result.strip() or len(parts) > 1
        result = r" \\ ".join(parts)
        if aligned:
            result = "\\begin{aligned}\n" + result + "\n\\end{aligned}"
    return {"body": result, "lines": lines}


def preview_expression(
    value: Any, parameter_values: dict | None = None,
) -> str:
    """JS ``previewExpression`` — the composed LaTeX block."""
    parameter_values = (
        parameter_values if parameter_values is not None else _parameter_values(value)
    )
    state = {"active": set(), "emitted": set()}
    root = unwrap_family_draft(value)
    root_key = preview_node_key(root, parameter_values)
    if root_key:
        state["active"].add(root_key)
    rendered = render_preview_node(root, parameter_values, state)
    if root_key:
        state["active"].discard(root_key)
    if not rendered["body"]:
        return ""
    if not rendered["lines"]:
        return rendered["body"]
    separator = " \\\\"
    return (
        "\\begin{aligned}\n"
        + separator.join(rendered["lines"] + [strip_formula_environment(rendered["body"])])
        + "\n\\end{aligned}"
    )


__all__ = [
    "expression",
    "preview_expression",
    "render_preview_node",
    "parameter_rows",
    "parameter_values",
    "parameter_value_map",
    "nested_preview_value",
    "is_nested_preview_value",
    "nested_parameter_values",
    "preview_node_key",
    "unwrap_family_draft",
    "strip_formula_environment",
    "family_symbol",
    "latex_value",
    "preview_scalar_value",
    "child_definition",
    "append_preview_definition",
]
