"""Read and render branch-owned Work Package report sources."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring.export import export_branch_report
from tools.cli.release.research_reporting.authoring.submission_status import (
    load_authoring_status,
    submission_status,
)

from .research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)
from .research_report_common import output as _output, scope_options
from .research_report_submission_errors import raise_report_gate_error
from .research_report_history_reconciliation import reconcile_graph_history
from .research_report_history_chapter_migration import (
    migrate_history_chapters_command,
)


def register_inspection_commands(group: click.Group) -> None:
    group.add_command(validate_report)
    group.add_command(show_report)
    group.add_command(manifest_report)
    group.add_command(render_report)
    group.add_command(reconcile_graph_history)
    group.add_command(migrate_history_chapters_command)


@click.command("validate")
@scope_options
@click.option("--json", "as_json", is_flag=True)
def validate_report(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Validate the structured source for one Work Package branch."""
    scope = _scope(profile_id, work_package_id, branch_id, release_profile)
    loaded, pending = _load_status(scope)
    head = loaded["head"]
    status = submission_status(pending)
    _output({
        "valid": status["writable"],
        "current_head_valid": True,
        "writable": status["writable"],
        "submission_status": status["state"],
        "report_id": head["report_id"], "generation": head["generation"],
        "body_format": "restricted_markdown",
        "components": len(loaded["components"]),
        "bindings": len(loaded["bindings"]),
        "pending_submission": pending,
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
    loaded, pending = _load_status(scope)
    if as_json:
        click.echo(json.dumps({
            "head": loaded["head"], "components": loaded["components"],
            "bindings": loaded["bindings"], "pending_submission": pending,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return
    click.echo(
        f"{loaded['head']['title']} · generation {loaded['head']['generation']}"
    )
    click.echo(
        f"components: {len(loaded['components'])} · bindings: {len(loaded['bindings'])}"
    )
    if pending:
        sequence = pending["submission_sequence"]
        click.echo(
            "pending submission: "
            f"{sequence} · attempt {pending['attempt']}"
        )
        click.echo(
            "action: correct this submission and retry with "
            f"--submission-sequence {sequence}"
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
    _output({"manifest": {
        "schema_version": 2, "report_id": loaded["head"]["report_id"],
        "generation": loaded["head"]["generation"], "root_ref": loaded["head"]["root_ref"],
        "component_refs": [{"component_id": item["component_id"], "kind": item["kind"]} for item in loaded["components"]],
        "binding_refs": [{"binding_id": item["binding_id"], "component_id": item["component_id"], "kind": item["kind"], "target_ref": item["target_ref"]} for item in loaded["bindings"]],
    }}, as_json)


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
    try:
        value = export_branch_report(
            package_root=scope.package_root,
            work_package_id=scope.work_package_id,
            branch_id=scope.branch_id,
        )
    except ValueError as error:
        raise_report_gate_error(scope=scope, error=error, as_json=as_json)
    _output({"output": str(value["path"]), "git": value["git"]}, as_json)


def _scope(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None,
):
    return resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )


def _load_status(scope) -> tuple[dict, dict | None]:
    return load_authoring_status(
        package_root=scope.package_root, branch_id=scope.branch_id,
    )
