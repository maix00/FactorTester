"""Source ownership, managed services, and factor-workspace commands."""

from __future__ import annotations

import shlex

import click

from ..core.service import fetch_worktrees, restart_worktree_service
from ..core.session import load_session, record_event, record_gap, save_session
from ..core.workspace import inspect_factor_source, parse_workspace_root
from ..utils.factortester_backend import run_factortester
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
        click.echo("说明: 平台代码修复后，使用 `service restart` 通过管理端口重启目标服务。")


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
        click.echo(f"{item['branch']} port={item['port']} running={item['running']} path={item['path']}")


@service.command("restart")
@click.option("--target-port", default=0, type=int, help="要重启的服务端口，例如 8123。")
@click.option("--branch", default="", help="按 worktree branch/label 选择目标。")
@click.option("--path", "target_path", default="", help="按 worktree path 选择目标。")
@click.option("--admin-port", default=None, type=int, help="覆盖 session 中的管理端口。")
@click.option("--dry-run", is_flag=True, help="只解析并打印 stop/start 动作。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def service_restart(
    ctx: click.Context,
    target_port: int,
    branch: str,
    target_path: str,
    admin_port: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Restart a managed FactorTester server after source-code fixes."""
    session = load_session(ctx.obj["session_path"])
    if session.operator_mode != "source_owner":
        raise click.ClickException("当前 operator_mode=client_only：没有服务器源码的用户不能修改代码或重启服务。请先用 `operator set --mode source_owner`。")
    port = admin_port or session.admin_port
    if not any([target_port, branch, target_path]):
        raise click.ClickException("必须指定 --target-port、--branch 或 --path 之一，避免重启错服务。")
    try:
        payload = restart_worktree_service(
            admin_port=port,
            target_port=target_port,
            branch=branch,
            path=target_path,
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
        click.echo(f"- {action['action']} {action['path']} port={action['port']}")
    if dry_run:
        click.echo("dry-run: 未执行 stop/start")
    else:
        click.echo("已通过管理端口提交 stop/start；请重新运行失败步骤验证。")


@click.group("workspace")
def workspace() -> None:
    """Prepare and inspect the FactorTester factor workspace."""


@workspace.command("prepare")
@click.option("--build", "do_build", is_flag=True, help="先执行 workspace build。")
@click.option("--sync/--no-sync", default=True, show_default=True, help="从数据库同步 workspace。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def workspace_prepare(ctx: click.Context, do_build: bool, sync: bool, as_json: bool) -> None:
    """Prepare local factor workspace through the real factortester CLI."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    commands: list[list[str]] = []
    if do_build:
        commands.append(["custom_factors", "workspace", "build"])
    if sync:
        commands.append(["custom_factors", "workspace", "sync"])
    commands.extend(
        [
            ["custom_factors", "workspace", "show"],
            ["custom_factors", "workspace", "git", "status"],
        ]
    )
    results = []
    root = ""
    for args in commands:
        result = run_factortester(args, timeout=600)
        results.append(result.as_dict())
        if result.returncode != 0:
            record_gap(session, "Factor workspace command failed", result.stderr or result.stdout, command=result.argv)
            break
        root = root or parse_workspace_root(result.stdout)
    if root:
        session.factor_source["workspace_root"] = root
    record_event(session, "workspace_prepared", root=root, command_count=len(results))
    save_session(session, session_path)
    payload = {"workspace_root": root, "results": results, "session": session.to_dict()}
    if as_json:
        echo_json(payload)
        return
    if root:
        click.echo(f"workspace: {root}")
    for item in results:
        click.echo("$ " + " ".join(shlex.quote(part) for part in item["argv"]))
        if item.get("stdout"):
            click.echo(str(item["stdout"]).rstrip())
        if item.get("stderr"):
            click.echo(str(item["stderr"]).rstrip(), err=True)


@workspace.command("inspect")
@click.option("--factor-family", required=True, help="因子家族名。")
@click.option("--root", default="", help="显式指定 workspace root；默认从 session 或 factortester workspace show 解析。")
@click.option("--sync/--no-sync", default=True, show_default=True, help="inspect 前先同步 workspace。")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON。")
@click.pass_context
def workspace_inspect(ctx: click.Context, factor_family: str, root: str, sync: bool, as_json: bool) -> None:
    """Inspect local factor source before testing a factor family."""
    session_path = ctx.obj["session_path"]
    session = load_session(session_path)
    workspace_root = root or str(session.factor_source.get("workspace_root") or "")
    if sync:
        sync_result = run_factortester(["custom_factors", "workspace", "sync"], timeout=600)
        record_event(session, "workspace_sync_before_inspect", returncode=sync_result.returncode)
        if sync_result.returncode != 0:
            record_gap(session, "Factor workspace sync failed", sync_result.stderr or sync_result.stdout, command=sync_result.argv)
            save_session(session, session_path)
            raise click.ClickException(sync_result.stderr or sync_result.stdout)
        workspace_root = workspace_root or parse_workspace_root(sync_result.stdout)
    if not workspace_root:
        show_result = run_factortester(["custom_factors", "workspace", "show"], timeout=60)
        if show_result.returncode != 0:
            record_gap(session, "Factor workspace root unavailable", show_result.stderr or show_result.stdout, command=show_result.argv)
            save_session(session, session_path)
            raise click.ClickException(show_result.stderr or show_result.stdout)
        workspace_root = parse_workspace_root(show_result.stdout)
    if not workspace_root:
        record_gap(session, "Factor workspace root unavailable", "factortester workspace show did not expose a parseable root")
        save_session(session, session_path)
        raise click.ClickException("无法解析 factor workspace root")
    report = inspect_factor_source(workspace_root, factor_family)
    describe_result = run_factortester(
        ["custom_factors", "describe", factor_family, "--source-code", "--json"],
        timeout=120,
    )
    if describe_result.returncode != 0:
        record_gap(session, "Factor operator tree unavailable", describe_result.stderr or describe_result.stdout, command=describe_result.argv)
        save_session(session, session_path)
        raise click.ClickException(describe_result.stderr or describe_result.stdout)
    try:
        import json

        factor_tree = json.loads(describe_result.stdout or "{}")
    except Exception as exc:
        record_gap(session, "Factor operator tree invalid", f"{type(exc).__name__}: {exc}", command=describe_result.argv)
        save_session(session, session_path)
        raise click.ClickException("无法解析因子算子树 JSON") from exc
    source_checks = factor_tree.get("source_checks") or {}
    report["tree_repr"] = factor_tree.get("tree_repr") or ""
    report["operator_keys"] = factor_tree.get("operator_keys") or []
    report["source_checks"] = source_checks
    if factor_family not in session.factor_families:
        session.factor_families.append(factor_family)
    session.factor_source = report
    record_event(session, "factor_source_inspected", factor_family=factor_family, file_count=report["file_count"])
    if report["file_count"] == 0:
        record_gap(session, "Factor source not found in workspace", f"factor_family={factor_family}, root={workspace_root}")
    if source_checks and not source_checks.get("ok"):
        record_gap(
            session,
            "Factor source and operator tree mismatch",
            f"missing_in_tree={source_checks.get('missing_in_tree')}, factor_family={factor_family}",
            command=describe_result.argv,
        )
        save_session(session, session_path)
        raise click.ClickException("因子源码与后端解析算子树不一致，请先修复因子源码或 FactorExpr 算子语义")
    save_session(session, session_path)
    if as_json:
        echo_json({"factor_source": report, "session": session.to_dict()})
        return
    click.echo(f"因子源码: {factor_family}")
    click.echo(f"workspace: {workspace_root}")
    if not report["files"]:
        click.echo("未找到匹配源码")
        return
    for item in report["files"]:
        click.echo(f"- {item['relative_path']}")
        for line in item["summary"][:16]:
            click.echo(f"    {line}")
    if report.get("operator_keys"):
        click.echo("算子: " + ", ".join(str(key) for key in report["operator_keys"]))
