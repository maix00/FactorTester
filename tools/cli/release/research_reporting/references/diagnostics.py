"""Structured, location-aware report submission diagnostics."""

from __future__ import annotations

from typing import Any


class ReportPreflightError(ValueError):
    def __init__(self, diagnostics: list[dict[str, Any]]) -> None:
        self.diagnostics = diagnostics
        first = diagnostics[0]
        super().__init__(
            f"{first['component_id']} {first['field']} "
            f"{first['line']}:{first['column']} {first['message']}"
        )


def diagnostic(
    *,
    component_id: str,
    field: str,
    value: str,
    offset: int,
    code: str,
    message: str,
    rule: str,
    example: str,
) -> dict[str, Any]:
    line = value.count("\n", 0, offset) + 1
    previous = value.rfind("\n", 0, offset)
    column = offset - previous
    return {
        "component_id": component_id,
        "field": field,
        "line": line,
        "column": column,
        "code": code,
        "message": message,
        "rule": rule,
        "example": example,
    }
