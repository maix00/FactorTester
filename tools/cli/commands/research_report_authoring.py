"""Create report sources and attach typed bindings in a Work Package."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import save_branch_authoring
from tools.cli.release.research_reporting.document import (
    add_asset, add_binding, rebind_document,
)

from .research_report_common import output, read_json, scope_options
from .research_report_component import add_report_component
from .research_report_scope import (
    ensure_authoring, load_authoring, persist_descriptor,
    resolve_branch_report_scope,
)


def register_authoring_commands(group: click.Group) -> None:
    group.add_command(create_report)
    group.add_command(add_report_component)
    group.add_command(attach_report_chip)
    group.add_command(add_report_asset)


@click.command("create")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def create_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Initialize the exact branch-owned structured report source."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    result = ensure_authoring(scope)
    output({
        "document": str(result["paths"]["document"]),
        "bindings": str(result["paths"]["bindings"]),
        "revision": result["document"]["revision"], "git": result["git"],
    }, as_json)


@click.command("chip")
@scope_options
@click.argument("component_id")
@click.option("--chip-id", required=True)
@click.option("--kind", type=click.Choice([
    "evidence", "obligation", "task", "job", "claim", "artifact",
    "report_requirement", "graph_reference", "checkpoint", "run",
]), required=True)
@click.option("--target-ref", required=True)
@click.option("--label", default="")
@click.option("--data-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True)
def attach_report_chip(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_id: str, chip_id: str, kind: str,
    target_ref: str, label: str, data_file: Path | None, as_json: bool,
) -> None:
    """Attach one typed chip to a branch report component."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    ensure_authoring(scope)
    loaded = load_authoring(scope)
    data = read_json(data_file) if data_file else {}
    if not isinstance(data, dict):
        raise click.ClickException("--data-file must contain a JSON object")
    saved = save_branch_authoring(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, document=loaded["document"],
        bindings=add_binding(
            loaded["bindings"], loaded["document"], component_id=component_id,
            binding_id=chip_id, kind=kind, target_ref=target_ref, label=label,
            data=data,
        ),
    )
    persist_descriptor(scope, saved["descriptor"])
    output({"binding_id": chip_id, "git": saved["git"]}, as_json)


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
    ensure_authoring(scope)
    loaded = load_authoring(scope)
    asset = read_json(asset_file)
    if not isinstance(asset, dict):
        raise click.ClickException("--asset-file must contain a JSON object")
    document = add_asset(loaded["document"], asset)
    saved = save_branch_authoring(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, document=document,
        bindings=rebind_document(loaded["bindings"], document),
    )
    persist_descriptor(scope, saved["descriptor"])
    output({"asset_ref": asset["asset_ref"], "git": saved["git"]}, as_json)


def _scope(profile_id: str, work_package_id: str, branch_id: str, release_profile: Path | None):
    return resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
