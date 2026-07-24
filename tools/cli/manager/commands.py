"""Public ``factortester manager`` command group."""

from __future__ import annotations

import json
import sys

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import (
    ManagerConfig,
    ManagerCredentialStore,
    load_manager_config,
    save_manager_config,
)


def _echo(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, indent=2))
        return
    click.echo(value.get("message") or value.get("status") or "ok")


def _authenticated_client() -> tuple[ManagerClient, ManagerCredentialStore]:
    config = load_manager_config()
    credentials = ManagerCredentialStore(config)
    return ManagerClient(config, token=credentials.read()), credentials


@click.group("manager")
def manager() -> None:
    """Configure, authenticate, and control the independent Manager."""


@manager.command("configure")
@click.option("--url", default="")
@click.option("--scheme", type=click.Choice(["http", "https"]), default="http")
@click.option("--host", default="127.0.0.1")
@click.option("--port", type=click.IntRange(1, 65535), default=7998)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def configure_manager(
    url: str,
    scheme: str,
    host: str,
    port: int,
    as_json: bool,
) -> None:
    """Save the Manager URL separately from the FactorTester server."""
    config = ManagerConfig.from_url(
        url or f"{scheme}://{host}:{port}"
    )
    save_manager_config(config)
    _echo({"status": "configured", "manager_url": config.base_url}, as_json)


@manager.command("login")
@click.option("--username", required=True)
@click.option(
    "--password",
    default="",
    hide_input=True,
)
@click.option("--credentials-stdin", is_flag=True, hidden=True)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def login_manager(
    username: str,
    password: str,
    credentials_stdin: bool,
    as_json: bool,
) -> None:
    """Authenticate a super administrator directly with Manager."""
    if credentials_stdin:
        credentials = json.load(sys.stdin)
        username = str(credentials.get("username") or username)
        password = str(credentials.get("password") or "")
    elif not password:
        password = click.prompt("Password", hide_input=True)
    config = load_manager_config()
    value = ManagerClient(config).login(username, password)
    token = str(value.pop("token", "") or "")
    ManagerCredentialStore(config).write(token)
    _echo(value, as_json)


@manager.command("logout")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def logout_manager(as_json: bool) -> None:
    """Revoke and remove the current Manager session."""
    client, credentials = _authenticated_client()
    value = client.logout()
    credentials.clear()
    _echo(value, as_json)


@manager.command("status")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def manager_status(as_json: bool) -> None:
    """Read the authenticated Manager principal."""
    client, _ = _authenticated_client()
    _echo(client.session(), as_json)


@manager.command("list")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_instances(as_json: bool) -> None:
    """List Manager-owned service instances."""
    client, _ = _authenticated_client()
    value = client.instances()
    if as_json:
        _echo(value, True)
        return
    for item in value.get("worktrees") or []:
        click.echo(
            f"{item.get('label') or item.get('instance_id')} "
            f"port={item.get('port')} "
            f"status={'running' if item.get('running') else 'stopped'}"
        )


def _action_command(name: str, help_text: str):
    def decorator(function):
        command = manager.command(name, help=help_text)(function)
        command = click.argument("instance_id")(command)
        command = click.option("--json", "as_json", is_flag=True)(command)
        return command
    return decorator


@_action_command("start", "Start one stopped service.")
@friendly_errors
def start(instance_id: str, as_json: bool) -> None:
    _run_action(instance_id, "start", as_json)


@_action_command("stop", "Stop one idle service without interrupting jobs.")
@friendly_errors
def stop(instance_id: str, as_json: bool) -> None:
    _run_action(instance_id, "stop", as_json)


@_action_command("restart-web", "Restart web/API while preserving background jobs.")
@friendly_errors
def restart_web(instance_id: str, as_json: bool) -> None:
    _run_action(instance_id, "restart-web", as_json)


@_action_command("restart-all", "Drain jobs, then restart the complete service.")
@friendly_errors
def restart_all(instance_id: str, as_json: bool) -> None:
    _run_action(instance_id, "restart-all", as_json)


@_action_command("force-stop", "Immediately stop all processes and active jobs.")
@click.confirmation_option(
    prompt="This interrupts active research jobs. Continue?"
)
@friendly_errors
def force_stop(instance_id: str, as_json: bool) -> None:
    _run_action(instance_id, "force-stop", as_json)


def _run_action(instance_id: str, action: str, as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.action(instance_id, action), as_json)
