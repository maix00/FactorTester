"""Create and append structured report components in a Work Package."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import (
    apply_branch_batch, commit_branch_authoring,
    register_branch_asset,
)

from .research_report_common import output, read_json, scope_options
from .research_report_component import add_report_component
from .research_report_reference import resolve_report_reference_command
from .research_report_scope import ensure_authoring, persist_descriptor, resolve_branch_report_scope


def register_authoring_commands(group: click.Group) -> None:
    group.add_command(create_report)
    group.add_command(add_report_component)
    group.add_command(add_report_asset)
    group.add_command(add_report_batch)
    group.add_command(resolve_report_reference_command)


@click.command("create")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def create_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Initialize the exact branch-owned structured report source."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    result = ensure_authoring(scope, materialize=False)
    git = commit_branch_authoring(scope.package_root, message="Initialize report tree")
    output({
        "head": str(result["paths"]["head"]),
        "generation": result["head"]["generation"], "git": git,
    }, as_json)


@click.command("asset")
@scope_options
@click.option("--asset-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def add_report_asset(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, asset_file: Path, as_json: bool,
) -> None:
    """Register an existing Work Package asset in the branch report source."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    ensure_authoring(scope, materialize=False)
    asset = read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain a JSON object")
    saved = register_branch_asset(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, asset=asset, materialize=False,
    )
    persist_descriptor(scope, saved["descriptor"])
    git = commit_branch_authoring(scope.package_root, message="Register report asset")
    output({"asset_ref": asset["asset_ref"], "generation": saved["head"]["generation"], "git": git}, as_json)


@click.command("add-batch")
@scope_options
@click.option("--operations-file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def add_report_batch(profile_id: str, work_package_id: str, branch_id: str, release_profile: Path | None, operations_file: Path, as_json: bool) -> None:
    """Apply related report components and internal bindings under one HEAD generation."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    ensure_authoring(scope, materialize=False)
    payload = read_json(operations_file)
    operations = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(operations, list):
        raise click.ClickException("--operations-file must contain an operations array")
    saved = apply_branch_batch(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, operations=operations, materialize=False,
    )
    persist_descriptor(scope, saved["descriptor"])
    git = commit_branch_authoring(scope.package_root, message="Add report batch")
    output({"generation": saved["head"]["generation"], "operation_count": len(operations), "git": git}, as_json)


def _scope(profile_id: str, work_package_id: str, branch_id: str, release_profile: Path | None):
    return resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
