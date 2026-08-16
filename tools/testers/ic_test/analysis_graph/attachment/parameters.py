"""Freeze registered analysis parameters without client-side field knowledge."""

from __future__ import annotations

import json
from typing import Any, Mapping

from tools.testers.analysis_graph import (
    AnalysisParameterDefinition,
    AnalysisTypeDefinition,
)

from .contracts import AnalysisAttachmentIssue


def freeze_analysis_parameters(
    definition: AnalysisTypeDefinition,
    supplied: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], tuple[AnalysisAttachmentIssue, ...]]:
    values = dict(supplied or {})
    definitions = {item.key: item for item in definition.parameters}
    unknown = sorted(set(values) - set(definitions))
    issues = [
        AnalysisAttachmentIssue(
            "unknown_parameter",
            "存在未注册的分析参数",
            {"parameter_keys": unknown},
        )
    ] if unknown else []
    frozen: dict[str, Any] = {}
    for key, parameter in definitions.items():
        value = values[key] if key in values else parameter.default
        try:
            frozen[key] = _freeze_value(parameter.value_descriptor.editor, value)
            _validate_registered_bounds(parameter, frozen[key])
        except (TypeError, ValueError) as exc:
            issues.append(AnalysisAttachmentIssue(
                "invalid_parameter",
                f"分析参数 {key} 不符合注册合同",
                {"parameter_key": key, "reason": str(exc)},
            ))
    return frozen, tuple(issues)


def _freeze_value(editor: str, value: Any) -> Any:
    if editor == "signal_count_list":
        values = value if isinstance(value, (list, tuple)) else (value,)
        counts = []
        for item in values:
            raw = item.get("value") if isinstance(item, dict) else item
            count = _integer(raw, minimum=2)
            counts.append({"unit": "signals", "value": count})
        return sorted(
            {item["value"]: item for item in counts}.values(),
            key=lambda item: item["value"],
        )
    if editor == "positive_integer_list":
        values = value if isinstance(value, (list, tuple)) else (value,)
        return sorted({_integer(item, minimum=1) for item in values})
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _integer(value: Any, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"value must be an integer >= {minimum}")
    number = int(value)
    if number != value or number < minimum:
        raise ValueError(f"value must be an integer >= {minimum}")
    return number


def _validate_registered_bounds(
    parameter: AnalysisParameterDefinition,
    value: Any,
) -> None:
    values = value if isinstance(value, list) else (value,)
    for item in values:
        scalar = item.get("value") if isinstance(item, dict) else item
        if (
            parameter.value_descriptor.minimum is not None
            and isinstance(scalar, (int, float))
            and scalar < parameter.value_descriptor.minimum
        ):
            raise ValueError(f"value must be >= {parameter.value_descriptor.minimum:g}")
        if (
            parameter.value_descriptor.maximum is not None
            and isinstance(scalar, (int, float))
            and scalar > parameter.value_descriptor.maximum
        ):
            raise ValueError(f"value must be <= {parameter.value_descriptor.maximum:g}")
    if parameter.value_descriptor.options:
        accepted = {option[0] for option in parameter.value_descriptor.options}
        if any(item not in accepted for item in values):
            raise ValueError(f"value must be one of {sorted(accepted)}")


__all__ = ["freeze_analysis_parameters"]
