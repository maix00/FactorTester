"""Profile-scoped research fork command and local report-tree materialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.core.errors import friendly_errors
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.package_layout import (
    ensure_branch_report_tree,
    safe_package_component,
)


def register_research_fork(group: click.Group) -> None:
    """Register the fork command without growing the root command module."""
    group.add_command(fork_profile_scoped_research)


@click.command("fork")
@click.argument("research_ref")
@click.option("--profile", "profile_id", required=True)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--label", required=True)
@click.option("--acting-profile-ref", default="")
@friendly_errors
def fork_profile_scoped_research(
    research_ref: str,
    profile_id: str,
    release_profile: Path | None,
    label: str,
    acting_profile_ref: str,
) -> None:
    """Fork a Graph branch and materialize its empty local report tree.

    The local directory records only the new branch identity.  It does not
    clone source content, invent a checkpoint, or assign an Agent to the fork.
    The first real checkpoint writes the branch report and journal.
    """
    instance_id, source_branch_id = _parse_branch_ref(research_ref)
    profile = LocalProfileStore(load_profile_root(release_profile)).load(
        profile_id
    )
    package_root = _package_root_for_source(profile, research_ref)
    server_url = str((profile.get("server") or {}).get("base_url") or "")
    if not server_url:
        raise click.ClickException(
            f"profile has no server URL: {profile_id}"
        )
    client = FactorTesterClient(HttpSession(server_url))
    branch = client.fork_research_graph_branch(
        instance_id,
        source_branch_id,
        label=label,
        acting_profile_ref=(acting_profile_ref or f"profile:{profile_id}"),
    )
    target_branch_id = str(branch.get("branch_id") or "")
    try:
        branch_root = ensure_branch_report_tree(package_root, target_branch_id)
    except ValueError as exc:
        raise click.ClickException(
            "server returned a research fork without a valid branch_id"
        ) from exc
    branch["local_report_tree"] = {
        "path": str(branch_root),
        "status": "materialized",
    }
    click.echo(json.dumps(
        branch, ensure_ascii=False, indent=2, sort_keys=True,
    ))


def _parse_branch_ref(research_ref: str) -> tuple[str, str]:
    parts = research_ref.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch" or not all(parts[1:]):
        raise click.ClickException(
            "research_ref must use graph-branch:<instance>:<branch>"
        )
    return parts[1], parts[2]


def _package_root_for_source(
    profile: dict[str, Any], research_ref: str,
) -> Path:
    matches = [
        record for record in profile["research_records"]
        if record["graph_branch_ref"] == research_ref
    ]
    if len(matches) != 1:
        raise click.ClickException(
            "fork requires exactly one local research record for its source"
        )
    package_ref = str(matches[0]["graph_instance_ref"] or "")
    if not package_ref.startswith("work-package:"):
        raise click.ClickException(
            "source research record has no valid Work Package reference"
        )
    try:
        package_id = safe_package_component(
            package_ref.removeprefix("work-package:"),
            field="source Work Package id",
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    package_root = (
        Path(profile["workspace_root"]).expanduser()
        / "research" / package_id
    )
    if not (package_root / "INDEX.json").is_file():
        raise click.ClickException(
            "source Work Package is not initialized locally"
        )
    return package_root
