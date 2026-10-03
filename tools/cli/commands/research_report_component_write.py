"""Sequenced implementation behind the report component Click command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.cli.release.research_reporting.authoring import add_branch_component

from .research_report_common import component_content, rich_body
from .research_report_content_structure import (
    validate_titled_chapter_content,
)
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


def _resolve_report_parent(
    scope: Any,
    *,
    parent_id: str | None,
    target_chapter_id: str,
) -> tuple[str | None, str]:
    """Place ordinary content in the requested or latest report chapter."""
    snapshot = load_current_authoring(scope)
    components = snapshot["components"]
    by_id = {str(item["component_id"]): item for item in components}
    chapters = [
        str(item["component_id"]) for item in components
        if item["kind"] == "chapter" and item["parent_id"] is None
    ]
    requested_chapter = target_chapter_id.strip()
    if requested_chapter and requested_chapter not in chapters:
        raise ValueError("target_chapter_id must identify a report chapter")
    requested_parent = str(parent_id or "").strip()
    ancestor = requested_parent
    parent_chapter = ""
    visited: set[str] = set()
    while ancestor:
        if ancestor in visited or ancestor not in by_id:
            raise ValueError("parent_id must identify a report component")
        visited.add(ancestor)
        if ancestor in chapters:
            parent_chapter = ancestor
            break
        ancestor = str(by_id[ancestor]["parent_id"] or "")
    if requested_chapter and parent_chapter and requested_chapter != parent_chapter:
        raise ValueError("parent_id and target_chapter_id identify different chapters")
    selected = requested_chapter or parent_chapter or (
        chapters[-1] if chapters else ""
    )
    return requested_parent or selected or None, selected


def write_report_component(
    *,
    client_root: Path,
    profile_id: str,
    report_workspace_id: str,
    branch_id: str,
    component_id: str,
    kind: str,
    title: str,
    parent_id: str | None,
    target_chapter_id: str,
    before_component_id: str | None,
    after_component_id: str | None,
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
    submission_sequence: int | None,
    as_json: bool,
) -> dict[str, Any]:
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id=profile_id,
        report_workspace_id=report_workspace_id, branch_id=branch_id,
    )
    ensure_authoring(scope, materialize=False, persist=False)
    parent_error = None
    if kind == "chapter":
        parent_id = None
        target_chapter_id = ""
    else:
        try:
            parent_id, target_chapter_id = _resolve_report_parent(
                scope,
                parent_id=parent_id,
                target_chapter_id=target_chapter_id,
            )
        except ValueError as error:
            # Reserve the branch-local submission sequence before surfacing
            # the validation failure, so the caller can correct and retry the
            # same logical component without losing the diagnostic.
            parent_error = error
    content = component_content(
        kind=kind, content_file=content_file, code_file=code_file,
        language=language, latex=latex, fallback=fallback,
        items=items, ordered=ordered,
    )
    plain_body = rich_body(body=body, body_file=body_file)
    component = {
        "component_id": component_id, "kind": kind, "title": title,
        "parent_id": parent_id, "body": plain_body, "content": content,
        "display_kind": display_kind,
        "target_chapter_id": target_chapter_id,
        "before_component_id": before_component_id,
        "after_component_id": after_component_id,
    }
    submission, reference_bindings = begin_component_submission(
        scope=scope, requested_sequence=submission_sequence,
        component=component, as_json=as_json,
        validation_error=parent_error,
    )
    if submission.phase == "finalized":
        saved = None
    elif submission.phase == "published":
        saved = load_current_authoring(scope)
    else:
        _publish_component(
            scope=scope, report_workspace_id=report_workspace_id,
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
        "before_component_id": before_component_id,
        "after_component_id": after_component_id,
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
    report_workspace_id: str,
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
        return add_branch_component(
            package_root=scope.package_root, report_workspace_id=report_workspace_id,
            branch_id=branch_id, component_id=component["component_id"],
            kind=component["kind"], title=component["title"],
            parent_id=component["parent_id"], body=component["body"],
            content=component["content"], display_kind=component["display_kind"],
            before_component_id=component["before_component_id"],
            after_component_id=component["after_component_id"],
            bindings=reference_bindings, materialize=False, submission=submission,
        )
    except Exception as error:
        reject_mutation(
            scope=scope, submission=submission, error=error, as_json=as_json,
        )
