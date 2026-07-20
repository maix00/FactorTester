"""Resume one stable local Agent identity with a compact server packet."""

from __future__ import annotations

import json
from pathlib import Path

import click

from tools.cli.client import FactorTesterClient
from tools.cli.core.errors import friendly_errors
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root


@click.command("resume-local")
@click.argument("profile_id")
@click.argument("agent_id")
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@friendly_errors
def resume_local_agent(
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
) -> None:
    """Resume a provider-neutral Agent from its local profile."""
    profile, agent = LocalProfileStore(
        load_profile_root(release_profile)
    ).load_agent(profile_id, agent_id)
    scope = agent["scope"]
    client = FactorTesterClient(HttpSession(
        str(profile["server"]["base_url"])
    ))
    packet = client.resume_agent(
        agent_id,
        role=str(agent["role"]),
        workspace_id=str(scope.get("workspace_id") or ""),
        instance_id=str(scope.get("instance_id") or ""),
        branch_id=str(scope.get("branch_id") or ""),
    )
    click.echo(json.dumps(
        packet,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
