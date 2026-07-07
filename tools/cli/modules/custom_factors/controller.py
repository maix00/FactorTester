"""Custom factors home-module CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import module_lines
from tools.cli.core.errors import friendly_errors


@click.group("custom_factors", invoke_without_command=True)
@click.pass_context
@friendly_errors
def custom_factors(ctx: click.Context) -> None:
    """Enter custom factors module."""
    if ctx.invoked_subcommand is None:
        ensure_child_available(None, "custom_factors")
        click.echo("因子管理")
        click.echo("下一层: factortester custom_factors list")
        click.echo("可用功能:")
        click.echo("  factortester custom_factors factor-library list|add")
        click.echo("  factortester custom_factors workspace show|root|build|sync|push")
        click.echo("  factortester custom_factors workspace git status|diff|commit|branch|checkout")


@custom_factors.command("list")
@friendly_errors
def list_custom_factor_children() -> None:
    """List custom factor module children."""
    click.echo("当前位置: custom_factors")
    for line in module_lines(client_from_config().list_modules(parent="custom_factors")):
        click.echo(line)


@custom_factors.group("factor-library", invoke_without_command=True)
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.pass_context
@friendly_errors
def factor_library(ctx: click.Context, factor_family: str, product_group: str) -> None:
    """Manage factor parameter library from the existing SQL store."""
    ctx.ensure_object(dict)
    ctx.obj["factor_family"] = factor_family
    ctx.obj["product_group"] = product_group
    if ctx.invoked_subcommand is None:
        ctx.invoke(list_factors, factor_family=factor_family, product_group=product_group)


@factor_library.command("list")
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.option("--include-subordinates", is_flag=True, help="包含下级用户可见配置。")
@click.pass_context
@friendly_errors
def list_factors(
    ctx: click.Context,
    factor_family: str,
    product_group: str,
    include_subordinates: bool,
) -> None:
    """List factor parameter candidates."""
    factor_family = factor_family or ctx.obj.get("factor_family", "")
    product_group = product_group or ctx.obj.get("product_group", "")
    overview = client_from_config().factor_library_overview(
        factor_family=factor_family,
        product_group=product_group,
        include_subordinates=include_subordinates,
    )
    factors = overview.get("factors") or []
    if not factors:
        click.echo("暂无因子参数候选")
        return
    for factor in factors:
        click.echo(factor_line(factor, default_family=factor_family, default_product_group=product_group))


@factor_library.command("add")
@click.option("--factor-family", "--factor_family", required=True, help="因子家族。")
@click.option("--product-group", "--product_group", default="", help="可选产品组 scope。")
@click.option("--param", "params", multiple=True, required=True, metavar="KEY=VALUE", help="参数键值，可重复传入。")
@friendly_errors
def add_factor_params(factor_family: str, product_group: str, params: tuple[str, ...]) -> None:
    """Append one parameter row to the factor library."""
    client = client_from_config()
    current_rows = current_user_params(client.factor_library_configs(factor_family, product_group=product_group))
    row = dict(parse_key_value(item) for item in params)
    current_rows.append(row)
    data = client.save_factor_library_config(
        factor_family,
        product_group=product_group,
        params_list=current_rows,
    )
    factors = data.get("factors") or []
    click.echo("已新增因子参数")
    if factors:
        click.echo(factor_line(factors[-1], default_family=factor_family, default_product_group=product_group))


@custom_factors.group("workspace", invoke_without_command=True)
@click.pass_context
@friendly_errors
def workspace(ctx: click.Context) -> None:
    """管理本地 factor workspace。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_workspace)


@workspace.command("show")
@friendly_errors
def show_workspace() -> None:
    """显示本地 factor workspace 目录与 Git 状态。"""
    client = client_from_config()
    source = client.factor_workspace_source_root()
    git_state = client.factor_workspace_git_settings()
    _print_workspace_source(source)
    _print_workspace_git(git_state)


@workspace.command("root")
@click.argument("path", required=False)
@friendly_errors
def set_workspace_root(path: str | None) -> None:
    """读取或保存源码目录。省略 PATH 时只显示当前目录。"""
    client = client_from_config()
    if path is None:
        _print_workspace_source(client.factor_workspace_source_root())
        return
    _print_workspace_source(client.save_factor_workspace_source_root(path))


@workspace.command("build")
@friendly_errors
def build_workspace() -> None:
    """建立本地 factor workspace。"""
    _print_workspace_action("建立", client_from_config().build_factor_workspace())


@workspace.command("sync")
@click.option("--branch-mode", default="force", show_default=True, help="同步分支模式。")
@friendly_errors
def sync_workspace(branch_mode: str) -> None:
    """从数据库下载同步到本地 workspace。"""
    _print_workspace_action("下载同步", client_from_config().sync_factor_workspace(branch_mode=branch_mode))


@workspace.command("push")
@click.option("--branch-mode", default="auto", show_default=True, help="上传分支模式。")
@friendly_errors
def push_workspace(branch_mode: str) -> None:
    """上传本地 workspace 到数据库。"""
    _print_workspace_action("上传入库", client_from_config().push_factor_workspace(branch_mode=branch_mode))


@workspace.command("git-settings")
@click.option("--enable/--disable", "git_enabled", default=None, help="启用或禁用 workspace Git。")
@click.option("--repo-root", default="", help="Git 仓库根目录。")
@friendly_errors
def workspace_git_settings(git_enabled: bool | None, repo_root: str) -> None:
    """读取或修改 workspace Git 设置。"""
    client = client_from_config()
    if git_enabled is None and not repo_root:
        _print_workspace_git(client.factor_workspace_git_settings())
        return
    current = client.factor_workspace_git_settings()
    enabled = bool(current.get("git_enabled")) if git_enabled is None else git_enabled
    root = repo_root or str(current.get("git_repo_root") or "")
    _print_workspace_git(client.save_factor_workspace_git_settings(git_enabled=enabled, git_repo_root=root))


@workspace.group("git", invoke_without_command=True)
@click.pass_context
@friendly_errors
def workspace_git(ctx: click.Context) -> None:
    """Run local Git commands inside the factor workspace."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(workspace_git_status)


@workspace_git.command("status")
@friendly_errors
def workspace_git_status() -> None:
    """Show local Git status for the factor workspace."""
    _print_workspace_git_action(client_from_config().factor_workspace_git_action("status"))


@workspace_git.command("diff")
@click.option("--stat", "show_stat", is_flag=True, help="只显示 diff stat。")
@click.option("--cached", is_flag=True, help="查看 staged diff。")
@friendly_errors
def workspace_git_diff(show_stat: bool, cached: bool) -> None:
    """Show local Git diff for the factor workspace."""
    _print_workspace_git_action(
        client_from_config().factor_workspace_git_action("diff", cached=cached, stat=show_stat)
    )


@workspace_git.command("commit")
@click.option("-m", "--message", required=True, help="提交信息。")
@friendly_errors
def workspace_git_commit(message: str) -> None:
    """Stage all workspace changes and commit them locally."""
    _print_workspace_git_action(client_from_config().factor_workspace_git_action("commit", message=message))


@workspace_git.command("branch")
@friendly_errors
def workspace_git_branch() -> None:
    """List local Git branches for the factor workspace."""
    _print_workspace_git_action(client_from_config().factor_workspace_git_action("branch"))


@workspace_git.command("checkout")
@click.argument("branch")
@click.option("--create", is_flag=True, help="如果分支不存在则创建。")
@friendly_errors
def workspace_git_checkout(branch: str, create: bool) -> None:
    """Switch workspace Git branch."""
    _print_workspace_git_action(
        client_from_config().factor_workspace_git_action("checkout", branch=branch, create=create)
    )


def current_user_params(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for user in payload.get("users") or []:
        if not user.get("editable"):
            continue
        config = user.get("config") or {}
        params = config.get("params_list") or []
        return [dict(row) for row in params if isinstance(row, dict)]
    return []


def _print_workspace_source(payload: dict[str, Any]) -> None:
    click.echo("本地 factor workspace")
    click.echo(f"源码目录: {payload.get('source_root') or '默认用户目录'}")
    click.echo(f"实际目录: {payload.get('resolved_root') or payload.get('workspace_root') or ''}")


def _print_workspace_git(payload: dict[str, Any]) -> None:
    click.echo("Git 状态:")
    click.echo(f"  启用: {'是' if payload.get('git_enabled') else '否'}")
    if payload.get("git_repo_root"):
        click.echo(f"  仓库: {payload.get('git_repo_root')}")
    if payload.get("git_current_branch"):
        click.echo(f"  当前分支: {payload.get('git_current_branch')}")
    branches = payload.get("git_branches") or []
    if branches:
        click.echo("  分支: " + ", ".join(str(branch) for branch in branches))


def _print_workspace_action(action: str, payload: dict[str, Any]) -> None:
    click.echo(f"{action}完成")
    if payload.get("workspace_root"):
        click.echo(f"workspace: {payload.get('workspace_root')}")
    if payload.get("git_selected_branch"):
        click.echo(f"分支: {payload.get('git_selected_branch')}")
    for key, label in (
        ("custom_factor_count", "自定义因子"),
        ("public_factor_count", "公共因子"),
        ("updated_custom_count", "更新自定义因子"),
        ("updated_public_count", "更新公共因子"),
    ):
        if key in payload:
            click.echo(f"{label}: {payload.get(key)}")
    for key, label in (
        ("touched_files", "写入文件"),
        ("removed_files", "移除文件"),
        ("cleared_files", "清理文件"),
    ):
        values = payload.get(key) or []
        if values:
            click.echo(f"{label}:")
            for value in values:
                click.echo(f"  - {value}")
    if payload.get("skipped"):
        click.echo(f"已跳过: {payload.get('skip_reason') or ''}")


def factor_line(factor: dict[str, Any], *, default_family: str = "", default_product_group: str = "") -> str:
    alias = factor.get("factor_alias") or factor.get("alias") or factor.get("name")
    family = factor.get("factor_family_alias") or factor.get("factor_family_name") or default_family
    scope = factor.get("product_group") or factor.get("scope_key") or default_product_group or "默认"
    owner = factor.get("owner_alias") or factor.get("owner_username") or ""
    parts = [str(alias)]
    if family:
        parts.append(f"因子家族={family}")
    if scope:
        parts.append(f"产品组={scope}")
    if owner:
        parts.append(f"所有者={owner}")
    return " · ".join(parts)


def parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("参数必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("参数 KEY 不能为空")
    return key, value.strip()


def _print_workspace_git_action(payload: dict[str, Any]) -> None:
    stdout = str(payload.get("stdout") or "").rstrip()
    stderr = str(payload.get("stderr") or "").rstrip()
    if stdout:
        click.echo(stdout)
    if stderr:
        click.echo(stderr, err=True)
    if payload.get("commit_sha"):
        click.echo(f"commit: {payload.get('commit_sha')}")
