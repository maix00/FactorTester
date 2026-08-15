"""Public ``factortester manager`` command group."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import (
    ManagerConfig,
    ManagerCredentialStore,
    load_manager_config,
    save_manager_config,
)
from tools.cli.manager.fleet import restart_managed_fleet


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
    """Configure, authenticate, and control the independent Manager.

    Source-owner maintenance uses the private
    ``factortester-server-maintenance`` Skill;
    discover the approved transaction with ``restart-fleet --help``.
    """


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


@manager.command("restart-fleet")
@click.option(
    "--source-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="提供 Manager 源码的 worktree；重启后从这里加载 Manager。",
)
@click.option(
    "--target-port",
    type=click.IntRange(1, 65535),
    default=None,
    help="可选的发布目标端口；只校验它已运行，实际仍恢复全部运行端口。",
)
@click.option(
    "--source-mode",
    type=click.Choice(["worktree", "git-commit"]),
    default="worktree",
    show_default=True,
    help="按当前工作区文件，或按指定 Git 提交的只读 worktree 启动 Manager。",
)
@click.option("--source-revision", default="", help="可选的源码 revision，写入回执。")
@click.option(
    "--stop-mode",
    type=click.Choice(["wait", "force"]),
    default="wait",
    show_default=True,
    help="默认关闭策略：wait 等待优雅退出，force 立即终止活动服务。",
)
@click.option(
    "--port-stop-mode",
    "port_stop_modes",
    multiple=True,
    metavar="PORT=MODE",
    help="覆盖单个端口的关闭策略，可重复，例如 8141=force。",
)
@click.option("--yes", is_flag=True, help="确认会短暂停止所有当前运行的服务。")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def restart_fleet(
    source_root: Path,
    target_port: int | None,
    source_mode: str,
    source_revision: str,
    stop_mode: str,
    port_stop_modes: tuple[str, ...],
    yes: bool,
    as_json: bool,
) -> None:
    """Restart Manager and restore exactly its previously running services.

    Read the private ``factortester-server-maintenance`` Skill before using
    this command.

    This is a server-maintenance transaction, separate from ``client release``.
    It deliberately requires an explicit source worktree and ``--yes`` so a
    maintenance agent cannot accidentally restart a different checkout or an
    active fleet.
    """
    if not yes:
        raise click.UsageError("整组重启会短暂停止所有运行服务，请显式追加 --yes")
    parsed_stop_modes = _parse_port_stop_modes(port_stop_modes)
    if source_mode == "git-commit" and not source_revision:
        raise click.UsageError("--source-mode git-commit 必须同时指定 --source-revision")
    client, _ = _authenticated_client()
    receipt = restart_managed_fleet(
        client=client,
        source_root=source_root,
        required_port=target_port,
        source_mode=source_mode,
        source_revision=source_revision,
        manager_url=client.config.base_url,
        stop_mode=stop_mode,
        port_stop_modes=parsed_stop_modes,
    )
    value = asdict(receipt)
    _echo(value, as_json)


def _parse_port_stop_modes(values: tuple[str, ...]) -> dict[int, str]:
    parsed: dict[int, str] = {}
    for value in values:
        raw_port, separator, mode = value.partition("=")
        if not separator or not raw_port.isdigit() or mode not in {"wait", "force"}:
            raise click.BadParameter(
                "必须使用 PORT=wait 或 PORT=force，例如 8141=force",
                param_hint="--port-stop-mode",
            )
        port = int(raw_port)
        if not 1 <= port <= 65535 or port in parsed:
            raise click.BadParameter(
                "端口必须唯一且在 1..65535 内",
                param_hint="--port-stop-mode",
            )
        parsed[port] = mode
    return parsed


def _action_command(name: str, help_text: str):
    def decorator(function):
        command = manager.command(name, help=help_text)(function)
        command = click.argument(
            "port", type=click.IntRange(1, 65535),
        )(command)
        command = click.option("--json", "as_json", is_flag=True)(command)
        return command
    return decorator


@_action_command("start", "Start one stopped service.")
@friendly_errors
def start(port: int, as_json: bool) -> None:
    _run_action(port, "start", as_json)


@_action_command("stop", "Stop one idle service without interrupting jobs.")
@friendly_errors
def stop(port: int, as_json: bool) -> None:
    _run_action(port, "stop", as_json)


@_action_command("restart-web", "Restart web/API while preserving background jobs.")
@friendly_errors
def restart_web(port: int, as_json: bool) -> None:
    _run_action(port, "restart-web", as_json)


@_action_command("restart-all", "Drain jobs, then restart the complete service.")
@friendly_errors
def restart_all(port: int, as_json: bool) -> None:
    _run_action(port, "restart-all", as_json)


@_action_command("force-stop", "Immediately stop all processes and active jobs.")
@click.confirmation_option(
    prompt="This interrupts active research jobs. Continue?"
)
@friendly_errors
def force_stop(port: int, as_json: bool) -> None:
    _run_action(port, "force-stop", as_json)


def _run_action(port: int, action: str, as_json: bool) -> None:
    client, _ = _authenticated_client()
    matches = [
        item for item in (client.instances().get("worktrees") or [])
        if int(item.get("port") or 0) == port
    ]
    if not matches:
        raise click.ClickException(f"没有找到端口 {port} 对应的服务")
    if len(matches) != 1:
        raise click.ClickException(f"端口 {port} 对应多个服务，Manager 状态无效")
    instance_id = str(matches[0].get("instance_id") or "").strip()
    if not instance_id:
        raise click.ClickException(f"端口 {port} 缺少内部服务身份")
    value = client.action(instance_id, action)
    value.pop("instance_id", None)
    value["port"] = port
    _echo(value, as_json)
