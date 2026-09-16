"""Remove Agent-authored ordinary content from a branch report."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import (
    remove_branch_component,
)

from .research_report_common import output, scope_options
from .research_report_graph_guard import validate_graph_bound_mutations
from .research_report_scope import (
    ensure_authoring,
    load_current_authoring,
    resolve_branch_report_scope,
)
from .research_report_submission_errors import (
    begin_or_raise,
    reject_mutation,
)
from .research_report_submission_finalize import finalize_report_command


@click.command("remove")
@scope_options
@click.option("--component-id", required=True)
@click.option(
    "--include-children",
    is_flag=True,
    help=(
        "明确删除整棵普通子树；任意深度含系统或研究图特殊小节时仍会拒绝"
        "（Agent 自己挂载的 Job 证据小节除外）"
    ),
)
@click.option(
    "--submission-sequence", type=click.IntRange(min=1), default=None,
    help="修正被拦截的删除时必须复用 CLI 返回的提交序号",
)
@click.option("--json", "as_json", is_flag=True)
def remove_report_component(
    profile_id: str,
    work_package_id: str,
    branch_id: str,
    release_profile: Path | None,
    component_id: str,
    include_children: bool,
    submission_sequence: int | None,
    as_json: bool,
) -> None:
    """Remove an ordinary component while retaining immutable Git history."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
    )
    ensure_authoring(scope, materialize=False, persist=False)
    payload = {
        "component_id": component_id,
        "include_children": include_children,
    }
    submission = begin_or_raise(
        scope=scope,
        requested_sequence=submission_sequence,
        logical_identity={
            "operation": "remove",
            "components": [{"component_id": component_id}],
        },
        payload=payload,
        as_json=as_json,
    )
    removed_ids: list[str] = []
    if submission.phase == "finalized":
        saved = None
    elif submission.phase == "published":
        saved = load_current_authoring(scope)
    else:
        try:
            validate_graph_bound_mutations(
                scope,
                operations=[{
                    "op": "remove",
                    "component_id": component_id,
                }],
            )
            mutation = remove_branch_component(
                package_root=scope.package_root,
                work_package_id=work_package_id,
                branch_id=branch_id,
                component_id=component_id,
                include_children=include_children,
                materialize=False,
                submission=submission,
            )
            removed_ids = list(mutation["removed_component_ids"])
        except Exception as error:
            reject_mutation(
                scope=scope,
                submission=submission,
                error=error,
                as_json=as_json,
            )
        saved = load_current_authoring(scope)

    finalized = finalize_report_command(
        scope=scope,
        submission=submission,
        descriptor=saved["descriptor"] if saved else {},
        message="Remove report component",
        as_json=as_json,
    )
    output({
        "component_id": component_id,
        "removed_component_ids": removed_ids,
        "removed_component_count": (
            len(removed_ids) if removed_ids else None
        ),
        "generation": (
            saved["head"]["generation"]
            if saved else submission.published_generation
        ),
        "submission_sequence": submission.sequence,
        "git": finalized["git"],
    }, as_json)
