"""Exception-total report preflight used after a sequence is reserved."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.references.diagnostics import (
    ReportPreflightError,
)
from tools.cli.release.research_reporting.references.preflight import (
    preflight_component,
)


def checked_component_preflight(
    *,
    scope: Any,
    component_id: str,
    kind: str,
    title: str,
    body: str,
    content: Any,
    display_kind: str,
    allow_historical_entry_requirement: bool = False,
    report_components: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return bindings or durable diagnostics; never strand an empty pending."""
    try:
        return preflight_component(
            component_id=component_id,
            kind=kind,
            title=title,
            body=body,
            content=content,
            display_kind=display_kind,
            scope=scope,
            allow_historical_entry_requirement=(
                allow_historical_entry_requirement
            ),
            report_components=report_components,
        ), []
    except ReportPreflightError as error:
        return [], error.diagnostics
    except Exception as error:
        return [], [{
            "component_id": component_id or "submission",
            "field": "component",
            "line": 1,
            "column": 1,
            "code": "report.preflight.unavailable",
            "message": f"报告预检无法完成: {error}",
            "rule": "恢复依赖或修正输入后，使用同一提交序号重试",
            "example": "--submission-sequence <CLI 返回的序号>",
        }]
