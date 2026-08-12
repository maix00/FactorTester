"""Super-admin read and process-lifecycle commands."""

from __future__ import annotations

import json

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors


def _echo_json(value) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


@click.group("admin")
def admin() -> None:
    """Inspect authorized server state and bounded administrative actions."""


@admin.command("jobs")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 100))
@click.option("--cursor", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_global_jobs(limit: int, cursor: str, as_json: bool) -> None:
    value = client_from_config().list_global_jobs(
        limit=limit,
        cursor=cursor,
    )
    if as_json:
        _echo_json(value)
        return
    for item in value.get("jobs") or []:
        click.echo(
            f"{item.get('job_id')} owner={item.get('owner')} "
            f"kind={item.get('kind')} status={item.get('status')}"
        )
    if value.get("next_cursor"):
        click.echo(f"next_cursor={value['next_cursor']}")


@admin.group("server")
def admin_server() -> None:
    """Inspect and control Manager-owned server instances."""


@admin_server.command("list")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_server_instances(as_json: bool) -> None:
    value = client_from_config().list_server_instances()
    if as_json:
        _echo_json(value)
        return
    for item in value.get("instances") or []:
        click.echo(
            f"{item.get('label') or item.get('instance_id')} "
            f"port={item.get('port')} status={item.get('status') or 'unknown'}"
        )


@admin_server.command("restart")
@click.argument("instance_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def restart_server_instance(instance_id: str, as_json: bool) -> None:
    _run_server_action(instance_id, "restart", as_json=as_json)


@admin_server.command("start")
@click.argument("instance_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def start_server_instance(instance_id: str, as_json: bool) -> None:
    _run_server_action(instance_id, "start", as_json=as_json)


@admin_server.command("stop")
@click.argument("instance_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def stop_server_instance(instance_id: str, as_json: bool) -> None:
    _run_server_action(instance_id, "stop", as_json=as_json)


def _run_server_action(
    instance_id: str,
    action: str,
    *,
    as_json: bool,
) -> None:
    value = client_from_config().run_server_instance_action(
        instance_id,
        action,
    )
    if as_json:
        _echo_json(value)
        return
    click.echo(f"{action} submitted: {value.get('instance_id')}")
