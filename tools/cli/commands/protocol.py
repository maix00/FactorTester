"""Compact protocol discovery and compatibility checks."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.protocol import negotiate_protocol


@click.group("protocol", invoke_without_command=True)
@click.pass_context
def protocol(ctx: click.Context) -> None:
    """Inspect or negotiate the remote FactorTester protocol."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(negotiate)


@protocol.command("show")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def show(as_json: bool) -> None:
    """Show the authenticated compact server manifest."""
    payload = client_from_config().protocol_manifest()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    proto = payload["protocol"]
    click.echo(
        f"{proto['name']} server={proto['minimum_client']}..{proto['current']} "
        f"capabilities={len(payload.get('capabilities') or [])}"
    )


@protocol.command("negotiate")
@click.option(
    "--require",
    "required",
    multiple=True,
    help="Required capability ID; repeatable.",
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def negotiate(required: tuple[str, ...], as_json: bool) -> None:
    """Fail unless this client and required capabilities are compatible."""
    result = negotiate_protocol(
        client_from_config().protocol_manifest(),
        required_capabilities=required,
    )
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(
        "协议兼容 · "
        f"server={result['server']['current']} "
        f"capabilities={len(result['capabilities'])}"
    )
