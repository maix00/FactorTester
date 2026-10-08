"""Create and append structured report components in a Report Workspace."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import (
    apply_branch_batch, commit_branch_authoring,
    register_branch_asset,
)

from .research_report_common import output, read_json, scope_options
from .research_report_content_structure import (
    validate_titled_chapter_content,
)
from .research_report_component import add_report_component
from .research_report_component_removal import remove_report_component
from .research_report_mutation_guide import report_mutation_guide
from .research_report_scope import (
    ensure_authoring, load_current_authoring, persist_descriptor,
    resolve_branch_report_scope,
)
from .research_report_submission import (
    begin_batch_submission,
    reject_mutation,
)
from .research_report_submission_errors import raise_report_gate_error
from .research_report_submission_finalize import finalize_report_command


def register_authoring_commands(group: click.Group) -> None:
    group.add_command(create_report)
    group.add_command(add_report_component)
    group.add_command(remove_report_component)
    group.add_command(add_report_asset)
    group.add_command(add_report_batch)
    group.add_command(report_mutation_guide)


@click.command("create")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def create_report(
    profile_id: str, report_workspace_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Initialize the exact branch-owned structured report source."""
    scope = _scope(profile_id, report_workspace_id, branch_id, release_profile)
    result = ensure_authoring(scope, materialize=False)
    git = commit_branch_authoring(scope.package_root, message="Initialize report tree")
    output({
        "head": str(result["paths"]["head"]),
        "generation": result["head"]["generation"], "git": git,
    }, as_json)


@click.command("asset")
@scope_options
@click.option("--asset-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--input", "source_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="复制工作区图片到指定分支，保留原文件。")
@click.option("--caption", default="")
@click.option("--alt-text", default="")
@click.option("--json", "as_json", is_flag=True)
def add_report_asset(
    profile_id: str, report_workspace_id: str, branch_id: str,
    release_profile: Path | None, asset_file: Path | None, as_json: bool,
    source_path: Path | None = None, caption: str = "", alt_text: str = "",
) -> None:
    """向指定分支登记图片；随后用 image 部件引用返回的 asset_ref。"""
    if (asset_file is None) == (source_path is None):
        raise click.UsageError("--input 与 --asset-file 必须且只能提供一个")
    scope = _scope(profile_id, report_workspace_id, branch_id, release_profile)
    ensure_authoring(scope, materialize=False, persist=False)
    if source_path is not None:
        from tools.cli.release.research_reporting.assets import stage_branch_image
        asset = stage_branch_image(package_root=scope.package_root, branch_id=branch_id,
                                   source_path=source_path, caption=caption, alt_text=alt_text)
    else:
        asset = read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain a JSON object")
    try:
        saved = register_branch_asset(
            package_root=scope.package_root, report_workspace_id=report_workspace_id,
            branch_id=branch_id, asset=asset, materialize=False,
        )
    except ValueError as error:
        raise_report_gate_error(scope=scope, error=error, as_json=as_json)
    persist_descriptor(scope, saved["descriptor"])
    git = commit_branch_authoring(scope.package_root, message="Register report asset")
    output({"asset_ref": asset["asset_ref"], "generation": saved["head"]["generation"], "git": git}, as_json)


@click.command("add-batch")
@scope_options
@click.option("--operations-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--submission-sequence", type=click.IntRange(min=1), default=None,
    help="修正被拦截的提交时必须复用 CLI 返回的提交序号",
)
@click.option("--json", "as_json", is_flag=True)
def add_report_batch(profile_id: str, report_workspace_id: str, branch_id: str, release_profile: Path | None, operations_file: Path, submission_sequence: int | None, as_json: bool) -> None:
    """Apply related report operations under one HEAD generation.

    ``op=replace`` requires component_id, title, body, content, and
    display_kind. It preserves the component's kind, parent, and children.
    Agent-authored bindings are rejected; write typed links in report fields.
    """
    scope = _scope(profile_id, report_workspace_id, branch_id, release_profile)
    ensure_authoring(scope, materialize=False, persist=False)
    payload = read_json(operations_file)
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        raise click.ClickException("--operations-file must contain an operations array")
    submission, enriched = begin_batch_submission(
        scope=scope,
        requested_sequence=submission_sequence,
        operations=operations,
        as_json=as_json,
    )
    if submission.phase == "finalized":
        saved = None
    elif submission.phase == "published":
        saved = load_current_authoring(scope)
    else:
        try:
            validate_titled_chapter_content(
                load_current_authoring(scope), enriched,
            )
            apply_branch_batch(
                package_root=scope.package_root, report_workspace_id=report_workspace_id,
                branch_id=branch_id, operations=enriched, materialize=False,
                submission=submission,
            )
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
        message="Add report batch",
        as_json=as_json,
    )
    git = finalized["git"]
    output({
        "generation": (
            saved["head"]["generation"] if saved
            else submission.published_generation
        ),
        "submission_sequence": submission.sequence,
        "operation_count": len(operations),
        "git": git,
    }, as_json)


def _scope(profile_id: str, report_workspace_id: str, branch_id: str, release_profile: Path | None):
    return resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        report_workspace_id=report_workspace_id, branch_id=branch_id,
    )
