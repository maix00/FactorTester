"""Sequenced implementation behind the report component Click command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring import add_branch_component

from .research_report_common import component_content, rich_body
from .research_report_content_structure import (
    validate_titled_chapter_content,
)
from .research_report_graph_guard import (
    resolve_graph_report_parent,
    validate_graph_bound_mutations,
)
from .research_report_entry_requirement import (
    obligation_requirement_body,
    resolve_obligation_requirement_title,
    validate_report_requirement_section,
)
from .research_report_requirement import report_requirement
from .research_report_scope import (
    ensure_authoring,
    load_current_authoring,
    resolve_branch_report_scope,
)
from .research_report_submission import (
    begin_component_submission,
    reject_mutation,
)
from .research_report_submission_finalize import finalize_report_command


def write_report_component(
    *,
    client_root: Path,
    profile_id: str,
    work_package_id: str,
    branch_id: str,
    component_id: str,
    kind: str,
    title: str,
    parent_id: str | None,
    target_chapter_id: str,
    body: str | None,
    body_file: Path | None,
    display_kind: str,
    content_file: Path | None,
    code_file: Path | None,
    language: str,
    latex: str | None,
    fallback: str,
    items: tuple[str, ...],
    ordered: bool,
    obligation_requirement_id: str,
    requirement_id: str,
    subject_ref: str,
    content_kind: str,
    submission_sequence: int | None,
    as_json: bool,
) -> dict[str, Any]:
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    ensure_authoring(scope, materialize=False, persist=False)
    (
        parent_id,
        target_chapter_id,
        allow_historical_entry_requirement,
    ) = resolve_graph_report_parent(
        scope,
        parent_id=parent_id,
        target_chapter_id=target_chapter_id,
    )
    content = component_content(
        kind=kind, content_file=content_file, code_file=code_file,
        language=language, latex=latex, fallback=fallback,
        items=items, ordered=ordered,
    )
    plain_body = obligation_requirement_body(
        body=rich_body(body=body, body_file=body_file),
        kind=kind,
        display_kind=display_kind,
        requirement_id=obligation_requirement_id,
        title_zh=(
            resolve_obligation_requirement_title(
                scope=scope,
                requirement_id=obligation_requirement_id,
                allow_historical=allow_historical_entry_requirement,
            )
            if kind == "special"
            and display_kind == "obligation_requirement"
            else ""
        ),
    )
    validate_report_requirement_section(
        kind=kind,
        display_kind=display_kind,
        obligation_requirement_id=obligation_requirement_id,
        report_requirement_id=requirement_id,
        report_subject_ref=subject_ref,
    )
    component = {
        "component_id": component_id, "kind": kind, "title": title,
        "parent_id": parent_id, "body": plain_body, "content": content,
        "display_kind": display_kind,
        "target_chapter_id": target_chapter_id,
        "report_requirement_id": requirement_id,
        "report_subject_ref": subject_ref,
        "report_content_kind": content_kind,
    }
    submission, reference_bindings = begin_component_submission(
        scope=scope, requested_sequence=submission_sequence,
        component=component, as_json=as_json,
        allow_historical_entry_requirement=(
            allow_historical_entry_requirement
        ),
    )
    if submission.phase == "finalized":
        saved = None
    elif submission.phase == "published":
        saved = load_current_authoring(scope)
    else:
        _publish_component(
            scope=scope, work_package_id=work_package_id,
            branch_id=branch_id, component=component,
            reference_bindings=reference_bindings,
            submission=submission, as_json=as_json,
        )
        saved = load_current_authoring(scope)
    finalized = finalize_report_command(
        scope=scope, submission=submission,
        descriptor=saved["descriptor"] if saved else {},
        message="Add report component", as_json=as_json,
    )
    return {
        "component_id": component_id, "kind": kind,
        "target_chapter_id": target_chapter_id,
        "body_format": "restricted_markdown",
        "generation": (
            saved["head"]["generation"] if saved
            else submission.published_generation
        ),
        "submission_sequence": submission.sequence,
        "git": finalized["git"],
    }


def _publish_component(
    *,
    scope: Any,
    work_package_id: str,
    branch_id: str,
    component: dict[str, Any],
    reference_bindings: list[dict[str, Any]],
    submission: Any,
    as_json: bool,
) -> dict[str, Any]:
    try:
        validate_titled_chapter_content(
            load_current_authoring(scope),
            [{
                "op": "add",
                "component_id": component["component_id"],
                "kind": component["kind"],
                "title": component["title"],
                "parent_id": component["parent_id"],
            }],
        )
        requirement, rendered_body = report_requirement(
            component_id=component["component_id"],
            body=component["body"],
            requirement_id=component["report_requirement_id"],
            subject_ref=component["report_subject_ref"],
            content_kind=component["report_content_kind"],
        )
        bindings = [*reference_bindings, *([requirement] if requirement else [])]
        validate_graph_bound_mutations(scope, operations=[{
            "op": "add",
            "component_id": component["component_id"],
            "kind": component["kind"],
            "title": component["title"],
            "parent_id": component["parent_id"],
            "display_kind": component["display_kind"],
            "target_chapter_id": component["target_chapter_id"],
        }])
        return add_branch_component(
            package_root=scope.package_root, work_package_id=work_package_id,
            branch_id=branch_id, component_id=component["component_id"],
            kind=component["kind"], title=component["title"],
            parent_id=component["parent_id"], body=rendered_body,
            content=component["content"], display_kind=component["display_kind"],
            bindings=bindings, materialize=False, submission=submission,
        )
    except Exception as error:
        reject_mutation(
            scope=scope, submission=submission, error=error, as_json=as_json,
        )
