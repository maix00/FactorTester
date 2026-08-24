"""Profile-scoped research fork command and local report-tree materialization."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root

from .client_research_fork_local import (
    bind_local_fork,
    inherit_local_report,
    source_package_root,
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
    """Fork a Graph branch with the source report as its initial snapshot."""
    instance_id, source_branch_id = _parse_branch_ref(research_ref)
    client_root = load_profile_root(release_profile)
    profile = LocalProfileStore(client_root).load(profile_id)
    package_root = source_package_root(profile, research_ref)
    client = client_from_config()
    branch = client.fork_research_graph_branch(
        instance_id,
        source_branch_id,
        label=label,
        acting_profile_ref=(acting_profile_ref or f"profile:{profile_id}"),
    )
    target_branch_id = str(branch.get("branch_id") or "")
    try:
        target_packet = client.get_research_graph_node_info(
            instance_id, target_branch_id,
        )
        branch["local_report_tree"] = inherit_local_report(
            package_root,
            source_branch_id,
            target_branch_id,
            target_instance_id=instance_id,
            target_packet=target_packet,
        )
        bind_local_fork(
            client_root=client_root,
            profile_id=profile_id,
            source_ref=research_ref,
            target_ref=(
                f"graph-branch:{instance_id}:{target_branch_id}"
            ),
        )
    except ValueError as exc:
        raise click.ClickException(
            "server returned a research fork without a valid branch_id"
        ) from exc
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
