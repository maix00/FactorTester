"""Cross-platform Work Package research projections."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _echo_json(value: dict) -> None:
    click.echo(json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


@click.group("research")
def client_research() -> None:
    """Inspect Work Packages and their Hypothesis Branches."""


@client_research.command("list")
@click.option("--workspace-ref", required=True)
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--after", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_research(
    workspace_ref: str,
    limit: int,
    after: str,
    as_json: bool,
) -> None:
    """List one Work Package per research, never one row per branch."""
    value = client_from_config().list_profile_research(
        workspace_ref=workspace_ref,
        limit=limit,
        after=after,
    )
    _echo_json(value)


@client_research.command("show")
@click.argument("work_package_ref")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_research(work_package_ref: str, as_json: bool) -> None:
    """Show one Work Package with compact Hypothesis Branch summaries."""
    _echo_json(
        client_from_config().get_profile_research(work_package_ref)
    )


@client_research.command("branch")
@click.argument("work_package_ref")
@click.argument("branch_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_branch(
    work_package_ref: str,
    branch_id: str,
    as_json: bool,
) -> None:
    """Show one Hypothesis Branch current-state projection."""
    _echo_json(client_from_config().get_profile_research_branch(
        work_package_ref,
        branch_id,
    ))


@client_research.command("timeline")
@click.argument("work_package_ref")
@click.argument("branch_id")
@click.option("--limit", default=50, show_default=True, type=int)
@click.option("--after", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show_timeline(
    work_package_ref: str,
    branch_id: str,
    limit: int,
    after: str,
    as_json: bool,
) -> None:
    """Page compact transition refs for one Hypothesis Branch."""
    _echo_json(
        client_from_config().list_profile_research_branch_timeline(
            work_package_ref,
            branch_id,
            limit=limit,
            after=after,
        )
    )
