"""Authentication and server-owned declarations for ``factortester-manager``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.manager.access import select_access_methods
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
    client = ManagerClient(config, token=credentials.read())
    client.require_manager()
    return client, credentials


@click.group("manager")
def manager() -> None:
    """Manage FactorTester through its authenticated 7998/7997 APIs.

    Host administration is outside this CLI.  A server may advertise
    operator-controlled connection metadata through ``server access``; the
    CLI only displays that declaration and never executes it.
    """


def register_manager_commands(target: click.Group) -> None:
    """Expose the Manager command group directly on the installed entrypoint."""
    for name, command in manager.commands.items():
        target.add_command(command, name=name)


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
    """Save the FactorTester Manager control endpoint."""
    config = ManagerConfig.from_url(url or f"{scheme}://{host}:{port}")
    save_manager_config(config)
    _echo({"status": "configured", "manager_url": config.base_url}, as_json)


@manager.command("login")
@click.option("--username", required=True)
@click.option("--password", default="", hide_input=True)
@click.option("--credentials-stdin", is_flag=True, hidden=True)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def login_manager(
    username: str,
    password: str,
    credentials_stdin: bool,
    as_json: bool,
) -> None:
    """Authenticate a Manager administrator and save the URL-scoped token."""
    if credentials_stdin:
        credentials = json.load(sys.stdin)
        username = str(credentials.get("username") or username)
        password = str(credentials.get("password") or "")
    elif not password:
        password = click.prompt("Password", hide_input=True)
    config = load_manager_config()
    value = ManagerClient(config).login(username, password)
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities.get("manager"):
        raise click.ClickException(
            "登录成功，但当前账号没有 Manager 管理权限（需要 super_admin）"
        )
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


@manager.group("server")
def server_info() -> None:
    """Read server identity and the access methods declared by that server."""


@server_info.command("inspect")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def inspect_server(as_json: bool) -> None:
    """Display FactorTester role, endpoints, features, and access metadata."""
    client, _ = _authenticated_client()
    _echo(client.identity(), as_json)


@server_info.group("access", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
@friendly_errors
def inspect_server_access(ctx: click.Context, as_json: bool) -> None:
    """Display the server's non-secret connection declarations."""
    if ctx.invoked_subcommand is not None:
        return
    client, _ = _authenticated_client()
    value = client.identity()
    payload = {
        "server": value.get("server") or {},
        "factor_tester": value.get("factor_tester") or {},
        "management_access": value.get("management_access") or [],
    }
    if as_json:
        _echo(payload, True)
        return
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@inspect_server_access.command("check")
@click.option("--method", "method_id", default="")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def check_server_access(method_id: str, as_json: bool) -> None:
    """Check declared local credential readiness without reading secrets."""
    client, _ = _authenticated_client()
    value = client.identity()
    methods = select_access_methods(
        value.get("management_access") or (),
        method_id=method_id,
    )
    payload = {
        "server": value.get("server") or {},
        "factor_tester": value.get("factor_tester") or {},
        "methods": methods,
    }
    if as_json:
        _echo(payload, True)
        return
    for item in methods:
        credential = item.get("credential") or {}
        click.echo(
            f"{item.get('method_id') or '-'} "
            f"ready={'yes' if item.get('ready') else 'no'} "
            f"credential={credential.get('state') or 'unknown'} "
            f"{credential.get('message') or ''}".rstrip()
        )


@inspect_server_access.group("script")
def server_access_script() -> None:
    """Download a server-declared connection script without executing it."""


@server_access_script.command("download")
@click.option("--method", "method_id", required=True)
@click.option(
    "--output",
    "destination",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option("--force", is_flag=True)
@click.option(
    "--skip-credential-check",
    is_flag=True,
    help="Download after an explicit override when local credential detection is unavailable.",
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def download_server_access_script(
    method_id: str,
    destination: Path,
    force: bool,
    skip_credential_check: bool,
    as_json: bool,
) -> None:
    """Download and digest-check one declared script; never execute it."""
    client, _ = _authenticated_client()
    value = client.identity()
    methods = value.get("management_access") or ()
    selected = [
        item for item in methods
        if isinstance(item, dict) and str(item.get("id") or "") == method_id
    ]
    if len(selected) != 1:
        raise click.ClickException(f"服务器没有声明连接方式: {method_id}")
    method = selected[0]
    script = method.get("script")
    if not isinstance(script, dict):
        raise click.ClickException(f"连接方式 {method_id} 没有可下载脚本")
    status = select_access_methods((method,))[0]
    if not skip_credential_check and not status.get("ready"):
        credential = status.get("credential") or {}
        auth = method.get("auth")
        hint = str(auth.get("setup_hint") or "").strip() if isinstance(auth, dict) else ""
        message = str(credential.get("message") or "本机凭证未就绪")
        if hint:
            message += f"；下一步：{hint}"
        raise click.ClickException(
            f"{message}。如确认凭证由外部工具管理，请使用 --skip-credential-check"
        )
    result = client.download_access_script_to_path(
        method_id,
        destination,
        expected_sha256=str(script.get("sha256") or ""),
        force=force,
    )
    _echo({**result, "executed": False}, as_json)
