"""Resolve server-owned objects into portable typed report links."""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring.inline_links import (
    typed_markdown_link,
)

from .research_report_common import output, scope_options
from .research_report_scope import (
    BranchReportScope,
    resolve_branch_report_scope,
)


@click.command("reference")
@scope_options
@click.option("--kind", required=True, type=click.Choice(["product"]))
@click.option("--target", required=True)
@click.option("--label", default="")
@click.option("--json", "as_json", is_flag=True)
def resolve_report_reference_command(
    profile_id: str,
    work_package_id: str,
    branch_id: str,
    release_profile: Path | None,
    kind: str,
    target: str,
    label: str,
    as_json: bool,
) -> None:
    """Resolve one authoritative object and print its Markdown reference."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        work_package_id=work_package_id,
        branch_id=branch_id,
    )
    try:
        reference = _client_for_scope(scope).resolve_report_reference(
            kind=kind, target=target,
        )
        markdown = typed_markdown_link(
            kind=str(reference["kind"]),
            target_ref=str(reference["target_ref"]),
            label=label or str(reference["label"]),
        )
    except (KeyError, RuntimeError, TypeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if as_json:
        output({**reference, "markdown": markdown}, True)
    else:
        click.echo(markdown)


def _client_for_scope(scope: BranchReportScope) -> FactorTesterClient:
    server = scope.profile.get("server")
    base_url = str(server.get("base_url") if isinstance(server, dict) else "")
    if not base_url:
        raise ValueError("Profile server base_url is required")
    return FactorTesterClient(HttpSession(base_url))
