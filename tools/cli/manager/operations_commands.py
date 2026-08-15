"""Read-only Manager operations and narrowly confirmed state changes.

These commands still use FactorTester Manager APIs.  They do not invoke host
administration transports; infrastructure access remains a declaration shown
by ``server access``.
"""

from __future__ import annotations

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.manager import commands as manager_commands
from tools.cli.manager.commands import _echo, manager, server_info


def _authenticated_client():
    return manager_commands._authenticated_client()


@server_info.command("health")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def server_health(as_json: bool) -> None:
    """Read Manager, data-plane, database, and federation health checks."""
    client, _ = _authenticated_client()
    _echo(client.health(), as_json)


@server_info.command("network")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def server_network(as_json: bool) -> None:
    """Read server-provided network and online-node information."""
    client, _ = _authenticated_client()
    _echo(client.network_info(), as_json)


@server_info.group("federation")
def server_federation() -> None:
    """Inspect Manager federation membership and public configuration."""


@server_federation.command("servers")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def federation_servers(as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.federation_servers(), as_json)


@server_federation.command("status")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def federation_status(as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.federation_config(), as_json)


@server_info.group("database")
def server_database() -> None:
    """Inspect the redacted PostgreSQL control-plane status."""


@server_database.command("status")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def database_status(as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.control_database_status(), as_json)


@manager.group("transfers")
def transfers() -> None:
    """Inspect local 7997 transfer telemetry."""


@transfers.command("metrics")
@click.option(
    "--window-seconds",
    type=click.IntRange(60, 7 * 24 * 60 * 60),
    default=24 * 60 * 60,
    show_default=True,
)
@click.option("--object-kind", default="")
@click.option("--operation", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def transfer_metrics(
    window_seconds: int,
    object_kind: str,
    operation: str,
    as_json: bool,
) -> None:
    """Read bounded transfer counts, bytes, failures, and active streams."""
    client, _ = _authenticated_client()
    value = client.transfer_metrics(
        window_seconds=window_seconds,
        object_kind=object_kind,
        operation=operation,
    )
    if as_json:
        _echo(value, True)
        return
    metrics = value.get("metrics") or {}
    totals = metrics.get("totals") or {}
    active = metrics.get("active") or {}
    click.echo(
        f"attempts={totals.get('attempts', 0)} "
        f"transferred_bytes={totals.get('transferred_bytes', 0)} "
        f"failed={totals.get('failed_attempts', 0)} "
        f"active={active.get('connections', 0)}"
    )


@manager.group("devices")
def devices() -> None:
    """Inspect or revoke this Manager's public access devices."""


@devices.command("list")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_devices(as_json: bool) -> None:
    client, _ = _authenticated_client()
    value = client.devices()
    if as_json:
        _echo(value, True)
        return
    for item in value.get("devices") or ():
        if isinstance(item, dict):
            click.echo(
                f"{item.get('device_id') or '-'} "
                f"user={item.get('username') or '-'} "
                f"client={item.get('client_name') or item.get('device_name') or '-'} "
                f"enabled={'yes' if item.get('enabled') else 'no'}"
            )


@devices.command("summary")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def device_summary(as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.device_summary(), as_json)


@devices.command("revoke")
@click.argument("device_id")
@click.option("--yes", is_flag=True, help="Confirm device revocation.")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def revoke_device(device_id: str, yes: bool, as_json: bool) -> None:
    if not yes:
        raise click.ClickException("撤销设备会立即阻止其自动登录；请显式提供 --yes")
    client, _ = _authenticated_client()
    _echo(client.revoke_device(device_id), as_json)


__all__ = ["server_health", "transfer_metrics", "list_devices"]
