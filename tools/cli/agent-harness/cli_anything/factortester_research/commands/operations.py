"""Source ownership, managed services, and factor-workspace commands."""

from __future__ import annotations

import click

from ..core.service import fetch_worktrees, restart_worktree_service
from ..core.session import load_session, record_event, save_session
from .common import echo_json


@click.group("operator")
def operator() -> None:
    """Configure whether this agent can modify FactorTester server source."""


@operator.command("set")
@click.option("--mode", type=click.Choice(["client_only", "source_owner"]), required=True, help="client_only 只能使用远端服务；source_owner 可以修改并重启服务器代码。")
@click.option("--admin-port", default=7998, show_default=True, type=int, help="本机 worktree Flask manager 管理端口。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def operator_set(ctx: click.Context, mode: str, admin_port: int, as_json: bool) -> None:
    """Persist source-code ownership and admin-port assumptions."""
    session = load_session(ctx.obj["session_path"])
    session.operator_mode = mode
    session.admin_port = admin_port
    record_event(session, "operator_configured", operator_mode=mode, admin_port=admin_port)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        echo_json({"session": session.to_dict()})
        return
    click.echo(f"operator_mode: {mode}")
    click.echo(f"admin_port: {admin_port}")
    if mode == "client_only":
        click.echo("说明: 当前用户没有服务器源码，平台代码缺口只能记录并交给维护者；仍可通过因子 workspace 修改可写因子。")
    else:
        click.echo(
            "说明: 平台代码修复后，先阅读 factortester-server-maintenance Skill，"
            "再运行 `factortester-manager server access --json` 读取目标服务器声明，"
            "按声明选择已授权的服务器维护工具。"
        )


@click.group("service")
def service() -> None:
    """Use the local 7998 worktree manager for source-owner validation loops."""


@service.command("list")
@click.option("--admin-port", default=None, type=int, help="覆盖 session 中的管理端口。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def service_list(ctx: click.Context, admin_port: int | None, as_json: bool) -> None:
    """List worktrees exposed by the local Flask manager."""
    session = load_session(ctx.obj["session_path"])
    port = admin_port or session.admin_port
    try:
        rows = [item.__dict__ for item in fetch_worktrees(admin_port=port)]
    except Exception as exc:
        raise click.ClickException(f"无法访问管理端口 {port}: {exc}") from exc
    if as_json:
        echo_json({"admin_port": port, "worktrees": rows})
        return
    for item in rows:
        click.echo(
            f"{item['branch']} instance_id={item['instance_id']} "
            f"port={item['port']} running={item['running']}"
        )


@service.command("restart")
@click.option("--instance-id", default="", help="按 Manager 返回的 opaque instance_id 选择目标。")
@click.option("--target-port", default=0, type=int, help="要重启的服务端口，例如 8123。")
@click.option("--branch", default="", help="按 worktree branch/label 选择目标。")
@click.option("--admin-port", default=None, type=int, help="覆盖 session 中的管理端口。")
@click.option("--dry-run", is_flag=True, help="只解析并打印 stop/start 动作。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def service_restart(
    ctx: click.Context,
    instance_id: str,
    target_port: int,
    branch: str,
    admin_port: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Restart a managed FactorTester server after source-code fixes."""
    session = load_session(ctx.obj["session_path"])
    if session.operator_mode != "source_owner":
        raise click.ClickException("当前 operator_mode=client_only：没有服务器源码的用户不能修改代码或重启服务。请先用 `operator set --mode source_owner`。")
    port = admin_port or session.admin_port
    if not any([instance_id, target_port, branch]):
        raise click.ClickException(
            "必须指定 --instance-id、--target-port 或 --branch 之一，避免重启错服务。"
        )
    try:
        payload = restart_worktree_service(
            admin_port=port,
            instance_id=instance_id,
            target_port=target_port,
            branch=branch,
            dry_run=dry_run,
        )
    except Exception as exc:
        raise click.ClickException(f"重启失败: {exc}") from exc
    record_event(session, "service_restart", admin_port=port, target=payload["target"], dry_run=dry_run)
    save_session(session, ctx.obj["session_path"])
    if as_json:
        echo_json(payload)
        return
    click.echo(f"target: {payload['target']['branch']} port={payload['target']['port']}")
    for action in payload["actions"]:
        click.echo(
            f"- {action['action']} instance_id={action['instance_id']} "
            f"port={action['port']}"
        )
    if dry_run:
        click.echo("dry-run: 未执行 stop/start")
    else:
        click.echo("已通过管理端口提交 stop/start；请重新运行失败步骤验证。")
