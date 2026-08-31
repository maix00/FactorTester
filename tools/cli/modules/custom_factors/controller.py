"""Custom factors home-module CLI controller."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.factor_subject_refs import split_owner_qualified_factor_family
from tools.cli.modules.custom_factors.factor_library import factor_library
from tools.cli.table import render_table


@factor_library.command("operators")
@click.option("--group", "group_filter", default="", help="只显示某个算子组 key。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def factor_expr_operators(group_filter: str, as_json: bool) -> None:
    """列出后端注册的 FactorExpr 算子，供因子工作区编写源码时参考。"""
    import json

    payload = client_from_config().factor_expr_operators()
    groups = payload.get("groups") or []
    if group_filter:
        groups = [group for group in groups if str(group.get("key") or "") == group_filter]
    if as_json:
        click.echo(json.dumps({"groups": groups}, ensure_ascii=False, indent=2))
        return
    if not groups:
        click.echo("暂无 FactorExpr 算子")
        return
    for group in groups:
        key = str(group.get("key") or "")
        label = str(group.get("label") or key)
        operators = list(group.get("operators") or [])
        more = list(group.get("more_operators") or [])
        click.echo(f"{label} ({key})")
        rows = []
        for operator in [*operators, *more]:
            rows.append(
                (
                    operator.get("key") or "",
                    operator.get("label") or "",
                    operator.get("symbol") or "",
                    operator.get("arity") if operator.get("arity") is not None else "",
                    operator.get("desc") or "",
                )
            )
        for line in render_table(
            ("key", "名称", "符号", "入参", "说明"),
            rows,
            indent="  ",
            max_widths=(22, 14, 10, 6, 58),
        ):
            click.echo(line)


@factor_library.command("describe")
@click.argument("factor_family")
@click.option(
    "--source",
    "source_mode",
    type=click.Choice(["auto", "custom", "public"]),
    default="auto",
    show_default=True,
    help="因子来源解析模式。",
)
@click.option("--owner-username", default="", help="custom 因子的 owner；默认当前登录用户。")
@click.option("--include-subordinates", is_flag=True, help="允许从下级用户可见因子中解析。")
@click.option("--source-code/--no-source-code", default=False, help="是否输出源码。")
@click.option("--debug-graph/--no-debug-graph", default=False, help="兼容调试：输出后端残留 graph JSON。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def describe_factor(
    factor_family: str,
    source_mode: str,
    owner_username: str,
    include_subordinates: bool,
    source_code: bool,
    debug_graph: bool,
    as_json: bool,
) -> None:
    """返回某个因子家族的源码摘要、参数和 FactorExpr 算子树。"""
    import json

    client = client_from_config()
    qualified_owner, lookup_family = _split_owner_qualified_factor_ref(
        factor_family
    )
    requested_owner = owner_username or qualified_owner or ""
    factor = _resolve_factor_from_catalog(
        client.custom_factor_catalog(
            include_subordinates=(
                include_subordinates or bool(requested_owner)
            )
        ),
        lookup_family,
        source_mode=source_mode,
        owner_username=requested_owner,
    )
    current_username = str(factor.pop("_current_username", "") or "")
    factor_owner = str(
        factor.get("owner_username") or requested_owner or ""
    )
    cross_owner = bool(
        not factor.get("is_public")
        and factor_owner
        and current_username
        and factor_owner != current_username
    )
    if source_code and cross_owner:
        raise click.ClickException(
            "跨账号登记因子只授权执行，不授权读取源码或数学表达式"
        )
    validation_payload: dict[str, Any]
    if factor.get("is_public"):
        validation_payload = {"is_public": True, "factor_name": factor.get("name") or factor_family}
    elif cross_owner:
        validation_payload = {}
    else:
        validation_payload = {
            "factor_id": factor.get("id") or lookup_family,
            "owner_username": factor_owner,
        }
    validation = (
        client.validate_factor_expr(validation_payload)
        if validation_payload else {}
    )
    if validation.get("valid") is False:
        raise click.ClickException(str(validation.get("error") or "因子表达式解析失败"))
    payload = {
        "factor": {
            "id": factor.get("id") or "",
            "name": factor.get("name") or factor_family,
            "source": "public" if factor.get("is_public") else "custom",
            "owner_username": factor_owner,
            "source_access": not cross_owner,
            "chinese_name": factor.get("chinese_name") or validation.get("desc") or "",
            "description": factor.get("description") or validation.get("description") or "",
            "params": validation.get("params") or factor.get("params") or [],
        },
        "tree_repr": validation.get("tree_repr") or factor.get("tree_repr") or "",
        "column_refs": validation.get("column_refs") or [],
        "operator_keys": _operator_keys_from_tree(validation.get("tree_repr") or factor.get("tree_repr") or ""),
    }
    payload["source_checks"] = _source_tree_checks(
        str(factor.get("source_code") or ""),
        str(payload["tree_repr"] or ""),
        payload["operator_keys"],
    )
    if source_code:
        payload["source_code"] = factor.get("source_code") or ""
    if debug_graph and validation.get("visual_graph") is not None:
        payload["debug_graph"] = validation.get("visual_graph")
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_factor_description(payload, include_source=source_code, include_debug_graph=debug_graph)


@factor_library.group("workspace", invoke_without_command=True)
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
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def sync_workspace(branch_mode: str, as_json: bool) -> None:
    """从数据库下载同步到本地 workspace。"""
    result = client_from_config().sync_factor_workspace(branch_mode=branch_mode)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_workspace_action("下载同步", result)


@workspace.command("push")
@click.option("--branch-mode", default="auto", show_default=True, help="上传分支模式。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def push_workspace(branch_mode: str, as_json: bool) -> None:
    """上传本地 workspace 到数据库。"""
    result = client_from_config().push_factor_workspace(branch_mode=branch_mode)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_workspace_action("上传入库", result)


@workspace.command("merge-download")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def merge_download_workspace(as_json: bool) -> None:
    """把 download 分支按既定流程合并到 upload 分支。"""
    result = client_from_config().factor_workspace_git_action("merge-download")
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_workspace_action("合并 download 到 upload", result)


@workspace.command("server-state")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def workspace_server_state(as_json: bool) -> None:
    """读取服务器 canonical 因子库快照和 Git 版本。"""
    payload = client_from_config().factor_workspace_snapshot()
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    result = {"source": "server", **snapshot}
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_workspace_state(result, "服务器 canonical 因子库")


@workspace.command("local-state")
@click.argument("root")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def workspace_local_state(root: str, as_json: bool) -> None:
    """读取本地 canonical 因子库目录和 Git 版本。"""
    result = _local_workspace_state(root)
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_workspace_state(result, "本地 canonical 因子库")


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


def _resolve_factor_from_catalog(
    payload: dict[str, Any],
    factor_family: str,
    *,
    source_mode: str,
    owner_username: str = "",
) -> dict[str, Any]:
    needle = factor_family.strip()
    if not needle:
        raise click.ClickException("因子家族不能为空")

    pools: list[dict[str, Any]] = []
    if source_mode in {"auto", "custom"}:
        pools.extend(dict(item, is_public=False) for item in payload.get("custom_factors") or [])
    if source_mode in {"auto", "public"}:
        pools.extend(dict(item, is_public=True) for item in payload.get("public_factors") or [])
    matches = [
        item
        for item in pools
        if needle in {
            str(item.get("id") or ""),
            str(item.get("name") or ""),
            str(item.get("factor_family") or ""),
        }
        and (
            not owner_username
            or str(item.get("owner_username") or "") == owner_username
        )
    ]
    if not matches:
        raise click.ClickException(f"找不到因子家族: {factor_family}")
    return dict(
        matches[0],
        _current_username=str(payload.get("current_username") or ""),
    )


def _split_owner_qualified_factor_ref(
    factor_family: str,
) -> tuple[str, str]:
    owner, family = split_owner_qualified_factor_family(factor_family)
    return ("" if owner in {None, "public"} else owner), family


def _operator_keys_from_tree(tree_repr: str) -> list[str]:
    text = str(tree_repr or "").lower()
    keys: list[str] = []
    for key in _SOURCE_TOKEN_TO_TREE_KEYS:
        if key.lower() in text:
            keys.append(key)
    return keys


def _print_factor_description(payload: dict[str, Any], *, include_source: bool, include_debug_graph: bool) -> None:
    factor = payload.get("factor") or {}
    click.echo(f"因子家族: {factor.get('name') or factor.get('id')}")
    click.echo(f"来源: {factor.get('source')}")
    if factor.get("owner_username"):
        click.echo(f"owner: {factor.get('owner_username')}")
    if factor.get("chinese_name"):
        click.echo(f"中文名: {factor.get('chinese_name')}")
    if factor.get("description"):
        click.echo(f"说明: {factor.get('description')}")
    params = factor.get("params") or []
    if params:
        click.echo("参数:")
        for line in render_table(
            ("alias", "类型", "默认值"),
            [
                (
                    item.get("alias") or item.get("name") or "",
                    item.get("type") or item.get("param_type") or "",
                    item.get("default") if item.get("default") is not None else item.get("default_value", ""),
                )
                for item in params
            ],
            indent="  ",
            max_widths=(18, 18, 24),
        ):
            click.echo(line)
    keys = payload.get("operator_keys") or []
    click.echo("算子: " + (", ".join(keys) if keys else "未解析到算子"))
    columns = payload.get("column_refs") or []
    click.echo("固定数据列: " + (", ".join(columns) if columns else "无"))
    tree = payload.get("tree_repr") or ""
    if tree:
        click.echo("算子树:")
        for line in str(tree).splitlines():
            click.echo("  " + line)
    checks = payload.get("source_checks") or {}
    if checks:
        click.echo("源码/算子树核查:")
        click.echo("  源码关键 token: " + (", ".join(checks.get("source_tokens") or []) or "无"))
        click.echo("  树中算子: " + (", ".join(checks.get("tree_tokens") or []) or "无"))
        missing = checks.get("missing_in_tree") or []
        click.echo("  结果: " + ("通过" if not missing and checks.get("has_tree") else "需要人工核查"))
        if missing:
            click.echo("  源码出现但树中未体现: " + ", ".join(missing))
    if include_source and payload.get("source_code"):
        click.echo("源码:")
        click.echo(str(payload.get("source_code") or ""))
    if include_debug_graph and payload.get("debug_graph") is not None:
        import json

        click.echo("debug_graph:")
        click.echo(json.dumps(payload.get("debug_graph"), ensure_ascii=False, indent=2))


_SOURCE_TOKEN_TO_TREE_KEYS = {
    "rolling_mean": {"rolling_mean"},
    "rolling_std": {"rolling_std"},
    "rolling_min": {"rolling_min"},
    "rolling_max": {"rolling_max"},
    "rolling_var": {"rolling_var"},
    "rolling_sum": {"rolling_sum"},
    "rolling_ema": {"rolling_ema"},
    "rolling_corr": {"rolling_corr"},
    "rolling_skew": {"rolling_skew"},
    "rolling_median": {"rolling_median"},
    "rolling_quantile": {"rolling_quantile"},
    "rolling_mad": {"rolling_mad"},
    "rolling_linreg_slope": {"rolling_linreg_slope"},
    "rolling_linreg_r2": {"rolling_linreg_r2"},
    "rolling_linreg_tstat": {"rolling_linreg_tstat"},
    "rolling_linreg_resid_std": {"rolling_linreg_resid_std"},
    "rolling_argmax": {"rolling_argmax"},
    "rolling_argmin": {"rolling_argmin"},
    "shift": {"shift"},
    "delta": {"delta", "sub"},
    "cs_rank": {"cs_rank", "cs_rank_masked"},
    "cs_ordinal_rank": {"cs_ordinal_rank_asc", "cs_ordinal_rank_desc"},
    "cs_zscore": {"cs_zscore"},
    "cs_spearman": {"cs_spearman"},
    "cs_corr": {"cs_corr"},
    "term_spread": {"term_spread"},
    "term_ratio": {"term_ratio"},
    "term_slope": {"term_slope"},
    "expr_max": {"expr_max", "max"},
    "expr_min": {"expr_min", "min"},
    "where": {"where"},
    "log": {"log"},
    "abs": {"abs"},
    "sqrt": {"sqrt"},
    "sign": {"sign"},
    "neg": {"neg"},
}


def _source_tree_checks(source: str, tree_repr: str, operator_keys: list[str]) -> dict[str, Any]:
    source_tokens = _source_operator_tokens(source)
    tree_tokens = set(operator_keys)
    tree_text = tree_repr.lower()
    missing: list[str] = []
    for token in source_tokens:
        expected = _SOURCE_TOKEN_TO_TREE_KEYS.get(token, {token})
        if not any(key in tree_tokens or key.lower() in tree_text for key in expected):
            missing.append(token)
    return {
        "has_source": bool(source.strip()),
        "has_tree": bool(tree_repr.strip() or operator_keys),
        "source_tokens": source_tokens,
        "tree_tokens": operator_keys,
        "missing_in_tree": missing,
        "ok": bool(tree_repr.strip() or operator_keys) and not missing,
    }


def _source_operator_tokens(source: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _SOURCE_TOKEN_TO_TREE_KEYS:
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}\s*\(", source):
            seen.add(token)
            tokens.append(token)
    # Unary minus can be normalized away by FactorFamily, so it is intentionally
    # checked only when explicit .neg() is used.
    return [token for token in tokens if token in seen]


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


def _local_workspace_root(root: str) -> Path:
    target = Path(root).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise click.ClickException(f"本地 canonical 因子库目录不存在: {target}")
    return target


def _local_workspace_files(root: str) -> list[dict[str, str]]:
    target = _local_workspace_root(root)
    files: list[dict[str, str]] = []
    for kind, directory in (("custom", "custom_factors"), ("public", "public_factors")):
        source_dir = target / directory
        if not source_dir.is_dir():
            continue
        for path in sorted(source_dir.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if source.strip():
                files.append({
                    "path": f"{directory}/{path.name}",
                    "kind": kind,
                    "source_code": source,
                })
    return files


def _local_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _local_workspace_state(root: str) -> dict[str, Any]:
    target = _local_workspace_root(root)
    files = _local_workspace_files(str(target))
    return {
        "source": "local",
        "workspace_root": str(target),
        "git_head": _local_git(target, "rev-parse", "--short", "HEAD"),
        "git_current_branch": _local_git(target, "branch", "--show-current"),
        "git_dirty": bool(_local_git(target, "status", "--porcelain")),
        "custom_factor_count": sum(item["kind"] == "custom" for item in files),
        "public_factor_count": sum(item["kind"] == "public" for item in files),
    }


def _print_workspace_state(payload: dict[str, Any], title: str) -> None:
    click.echo(title)
    click.echo(f"目录: {payload.get('workspace_root') or '未设置'}")
    click.echo(f"Git 版本: {payload.get('git_head') or '无'}")
    click.echo(f"分支: {payload.get('git_current_branch') or '无'}")
    if payload.get("source") == "local":
        click.echo(f"本地改动: {'有' if payload.get('git_dirty') else '无'}")
    click.echo(f"自定义因子: {payload.get('custom_factor_count') or 0}")
    click.echo(f"公共因子: {payload.get('public_factor_count') or 0}")


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
    metadata = factor.get("metadata") if isinstance(factor.get("metadata"), dict) else {}
    parts = [str(alias)]
    if family:
        parts.append(f"因子家族={family}")
    if scope:
        parts.append(f"产品组={scope}")
    if owner:
        parts.append(f"所有者={owner}")
    if metadata.get("note"):
        parts.append(f"备注={metadata.get('note')}")
    if metadata.get("product_group_paths"):
        parts.append(f"路径数={len(metadata.get('product_group_paths') or [])}")
    return " · ".join(parts)


def _print_workspace_git_action(payload: dict[str, Any]) -> None:
    stdout = str(payload.get("stdout") or "").rstrip()
    stderr = str(payload.get("stderr") or "").rstrip()
    if stdout:
        click.echo(stdout)
    if stderr:
        click.echo(stderr, err=True)
    if payload.get("commit_sha"):
        click.echo(f"commit: {payload.get('commit_sha')}")
