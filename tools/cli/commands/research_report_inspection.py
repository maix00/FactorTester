"""Read and render branch-owned Work Package report sources."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.document import (
    bindings_manifest,
    document_manifest,
    validate_document,
)
from tools.cli.release.research_reporting.writer import render_branch_authoring_report

from .research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)
from .research_report_common import output as _output, scope_options


def register_inspection_commands(group: click.Group) -> None:
    group.add_command(validate_report)
    group.add_command(show_report)
    group.add_command(manifest_report)
    group.add_command(render_report)


@click.command("validate")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def validate_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Validate the structured source for one Work Package branch."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    loaded = load_authoring(scope)
    value = validate_document(loaded["document"])
    _output({
        "valid": True,
        "document_id": value["document_id"],
        "revision": value["revision"],
        "components": len(value["components"]),
        "bindings": len(loaded["bindings"]["bindings"]),
    }, as_json)


@click.command("show")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def show_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Show the structured authoring data of one Work Package branch."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    loaded = load_authoring(scope)
    if as_json:
        click.echo(json.dumps({
            "document": loaded["document"], "bindings": loaded["bindings"],
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(
        f"{loaded['document']['title']} · revision "
        f"{loaded['document']['revision']}"
    )
    click.echo(
        f"components: {len(loaded['document']['components'])} · bindings: "
        f"{len(loaded['bindings']['bindings'])}"
    )


@click.command("manifest")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def manifest_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Emit a content-free manifest for a branch-owned report source."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    loaded = load_authoring(scope)
    _output({
        "manifest": document_manifest(loaded["document"]),
        "bindings_manifest": bindings_manifest(
            loaded["bindings"], loaded["document"],
        ),
    }, as_json)


@click.command("render")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def render_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Refresh the single branch REPORT.md from the structured source."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    load_authoring(scope)
    value = render_branch_authoring_report(
        package_root=scope.package_root,
        work_package_id=scope.work_package_id,
        branch_id=scope.branch_id,
    )
    _output({"output": str(value["path"]), "git": value["git"]}, as_json)


def _scope(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None,
):
    return resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
