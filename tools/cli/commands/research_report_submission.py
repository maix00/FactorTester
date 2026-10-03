"""CLI orchestration for preflighted, sequenced report submissions."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.submission_gate import (
    ReportSubmission,
)
from tools.cli.release.research_reporting.authoring.tree_projection import (
    load_snapshot,
)
from tools.cli.release.research_reporting.references.diagnostics import (
    diagnostic,
)
from .research_report_submission_errors import (
    SubmissionGateUsageError,
    begin_or_raise,
    reject_mutation,
    reject_submission,
)
from .research_report_submission_identity import (
    agent_binding_diagnostic,
    batch_identity,
    component_identity,
)
from .research_report_submission_preflight import (
    checked_component_preflight,
)

def begin_component_submission(
    *,
    scope: Any,
    requested_sequence: int | None,
    component: dict[str, Any],
    as_json: bool,
    allow_historical_entry_requirement: bool = False,
    validation_error: ValueError | None = None,
) -> tuple[ReportSubmission, list[dict[str, Any]]]:
    submission = begin_or_raise(
        scope=scope,
        requested_sequence=requested_sequence,
        logical_identity=component_identity(component),
        payload=component,
        as_json=as_json,
    )
    if submission.phase in {"published", "finalized"}:
        return submission, []
    if validation_error is not None:
        reject_mutation(
            scope=scope, submission=submission,
            error=validation_error, as_json=as_json,
        )
    bindings, diagnostics = checked_component_preflight(
        component_id=component["component_id"],
        kind=component["kind"],
        title=component["title"],
        body=component["body"],
        content=component["content"],
        display_kind=str(component.get("display_kind") or ""),
        scope=scope,
        allow_historical_entry_requirement=(
            allow_historical_entry_requirement
        ),
    )
    if (
        component["kind"] != "chapter"
        and not str(component.get("parent_id") or "").strip()
    ):
        diagnostics.append(_parent_required_diagnostic(
            str(component.get("component_id") or ""),
        ))
    if diagnostics:
        reject_submission(
            scope=scope,
            submission=submission,
            diagnostics=diagnostics,
            as_json=as_json,
        )
    return submission, bindings


def _parent_required_diagnostic(component_id: str) -> dict[str, Any]:
    return diagnostic(
        component_id=component_id or "submission",
        field="parent_id", value="", offset=0,
        code="report.parent.required",
        message="非章节报告组件必须明确指定父级",
        rule=(
            "每次提交都要用 --parent-id 明确选择章节、特殊小节"
            "或其中的普通小节；不会继承上一条的位置"
        ),
        example="--parent-id grill-directional-gate",
    )

def begin_batch_submission(
    *,
    scope: Any,
    requested_sequence: int | None,
    operations: list[dict[str, Any]],
    as_json: bool,
    historical_review: dict[str, Any] | None = None,
) -> tuple[ReportSubmission, list[dict[str, Any]]]:
    try:
        logical_identity = batch_identity(operations)
    except ValueError as error:
        raise SubmissionGateUsageError(str(error), as_json) from error
    submission = begin_or_raise(
        scope=scope,
        requested_sequence=requested_sequence,
        logical_identity=logical_identity,
        payload=operations,
        as_json=as_json,
    )
    if submission.phase in {"published", "finalized"}:
        return submission, operations
    enriched: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    try:
        current_kinds = _current_component_kinds(scope, operations)
        report_components = _planned_report_components(scope, operations)
    except (OSError, ValueError) as error:
        reject_mutation(scope=scope, submission=submission, error=error,
                        as_json=as_json)
    for operation in operations:
        value = dict(operation)
        if operation.get("op") in {"add", "replace"}:
            if "bindings" in operation:
                diagnostics.append(agent_binding_diagnostic(
                    str(operation.get("component_id") or ""),
                ))
                value["bindings"] = []
            declared_kind = str(operation.get("kind") or "")
            kind = declared_kind
            if operation.get("op") == "replace":
                current_kind = current_kinds.get(
                    str(operation.get("component_id") or ""), "",
                )
                kind = current_kind or declared_kind
                value["kind"] = declared_kind or current_kind
            generated, issues = checked_component_preflight(
                component_id=str(operation.get("component_id") or ""),
                kind=kind,
                title=str(operation.get("title") or ""),
                body=str(operation.get("body") or ""),
                content=operation.get("content"),
                display_kind=str(operation.get("display_kind") or ""),
                scope=scope,
                allow_historical_entry_requirement=(
                    historical_review is not None
                ),
                report_components=report_components,
            )
            value["bindings"] = generated
            diagnostics.extend(issues)
            if (
                operation.get("op") == "add"
                and kind != "chapter"
                and not str(operation.get("parent_id") or "").strip()
            ):
                diagnostics.append(_parent_required_diagnostic(
                    str(operation.get("component_id") or ""),
                ))
        elif operation.get("op") == "bind":
            diagnostics.append(agent_binding_diagnostic(
                str(operation.get("component_id") or ""),
            ))
        elif "bindings" in operation:
            diagnostics.append(agent_binding_diagnostic(
                str(operation.get("component_id") or ""),
            ))
        enriched.append(value)
    if diagnostics:
        reject_submission(
            scope=scope,
            submission=submission,
            diagnostics=diagnostics,
            as_json=as_json,
        )
    return submission, enriched


def _current_component_kinds(
    scope: Any, operations: list[dict[str, Any]],
) -> dict[str, str]:
    if not any(
        isinstance(item, dict) and item.get("op") == "replace"
        for item in operations
    ):
        return {}
    snapshot = load_snapshot(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
    return {
        str(item["component_id"]): str(item["kind"])
        for item in snapshot["components"]
    }


def _planned_report_components(scope: Any, operations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate internal links against the complete batch, including forward references."""
    snapshot = load_snapshot(package_root=scope.package_root, branch_id=scope.branch_id)
    nodes = {item['component_id']: dict(item) for item in snapshot['components']}
    for operation in operations:
        node_id = operation.get('component_id')
        if operation.get('op') in {'add', 'replace'} and node_id:
            nodes[node_id] = {**nodes.get(node_id, {}), **operation}
    return nodes
