"""Custom factors home-module CLI controller."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import module_lines
from tools.cli.core.errors import friendly_errors
from tools.cli.table import render_table


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
        click.echo("  factortester custom_factors operators")


@custom_factors.command("list")
@friendly_errors
def list_custom_factor_children() -> None:
    """List custom factor module children."""
    click.echo("当前位置: custom_factors")
    for line in module_lines(client_from_config().list_modules(parent="custom_factors")):
        click.echo(line)


@custom_factors.command("operators")
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


@custom_factors.command("describe")
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
    factor = _resolve_factor_from_catalog(
        client.custom_factor_catalog(include_subordinates=include_subordinates),
        factor_family,
        source_mode=source_mode,
    )
    validation_payload: dict[str, Any]
    if factor.get("is_public"):
        validation_payload = {"is_public": True, "factor_name": factor.get("name") or factor_family}
    else:
        validation_payload = {
            "factor_id": factor.get("id") or factor_family,
            "owner_username": owner_username or factor.get("owner_username") or "",
        }
    validation = client.validate_factor_expr(validation_payload)
    if validation.get("valid") is False:
        raise click.ClickException(str(validation.get("error") or "因子表达式解析失败"))
    payload = {
        "factor": {
            "id": factor.get("id") or "",
            "name": factor.get("name") or factor_family,
            "source": "public" if factor.get("is_public") else "custom",
            "owner_username": factor.get("owner_username") or owner_username or "",
            "chinese_name": factor.get("chinese_name") or validation.get("desc") or "",
            "description": factor.get("description") or validation.get("description") or "",
            "params": validation.get("params") or factor.get("params") or [],
        },
        "tree_repr": validation.get("tree_repr") or factor.get("tree_repr") or "",
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
@click.option("--note", default="", help="保存到因子库配置的研究备注。")
@click.option("--research-report", "--research_report", default="", help="关联的研究报告路径或标识。")
@click.option("--product-path", "--product_path", "product_paths", multiple=True, help="当场产品组路径，可重复；默认按产品组库同名 scope 自动快照。")
@friendly_errors
def add_factor_params(
    factor_family: str,
    product_group: str,
    params: tuple[str, ...],
    note: str,
    research_report: str,
    product_paths: tuple[str, ...],
) -> None:
    """Append one parameter row to the factor library."""
    client = client_from_config()
    current_rows = current_user_params(client.factor_library_configs(factor_family, product_group=product_group))
    row = dict(parse_key_value(item) for item in params)
    current_rows.append(row)
    metadata = {
        "note": note,
        "research_report": research_report,
        "product_group_paths": list(product_paths),
    }
    data = client.save_factor_library_config(
        factor_family,
        product_group=product_group,
        params_list=current_rows,
        metadata={key: value for key, value in metadata.items() if value},
    )
    factors = data.get("factors") or []
    click.echo("已新增因子参数")
    if factors:
        click.echo(factor_line(factors[-1], default_family=factor_family, default_product_group=product_group))


@factor_library.command("import-result")
@click.option("--artifact", "artifact_paths", multiple=True, type=click.Path(exists=True, dir_okay=False), required=True, help="研究 artifact JSON，可重复。")
@click.option("--factor-family", "--factor_family", default="", help="覆盖 artifact 中的因子家族。")
@click.option("--factor-alias", "--factor_alias", default="", help="覆盖 artifact 中的因子 alias。")
@click.option("--product-group", "--product_group", default="", help="覆盖 artifact 中的产品组。")
@click.option("--test-type", "--test_type", default="auto", type=click.Choice(["auto", "ic", "backtest", "bucket_label", "factor_type"]), help="研究结果类型。")
@click.option("--report-path", "--research-report", "--research_report", default="", help="关联研究报告路径。")
@click.option("--note", default="", help="入库备注。")
@friendly_errors
def import_factor_research_result(
    artifact_paths: tuple[str, ...],
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    report_path: str,
    note: str,
) -> None:
    """Import existing research artifact JSON into the structured result index."""
    client = client_from_config()
    saved = []
    for artifact_path in artifact_paths:
        payloads = _research_payloads_from_artifact(
            Path(artifact_path),
            factor_family=factor_family,
            factor_alias=factor_alias,
            product_group=product_group,
            test_type=test_type,
            report_path=report_path,
            note=note,
        )
        for payload in payloads:
            saved.append(client.save_factor_research_run(payload).get("run") or {})
    click.echo(f"已导入研究结果: {len(saved)}")
    for run in saved:
        click.echo(_research_run_line(run))


@factor_library.command("rank")
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--factor-alias", "--factor_alias", default="", help="因子 alias。")
@click.option("--product-group", "--product_group", default="", help="产品组。")
@click.option("--test-type", "--test_type", default="", help="测试类型: ic/backtest/bucket_label/factor_type。")
@click.option("--start-date", "--start_date", default="", help="查询开始日期。")
@click.option("--end-date", "--end_date", default="", help="查询结束日期。")
@click.option("--contained", is_flag=True, help="要求结果区间完全落在查询区间内；默认只要求 overlap。")
@click.option("--metric", default="ls_return", help="排序指标。")
@click.option("--min-metric", "--min_metric", "min_metrics", multiple=True, metavar="KEY=VALUE", help="最小指标过滤，可重复。")
@click.option("--max-metric", "--max_metric", "max_metrics", multiple=True, metavar="KEY=VALUE", help="最大指标过滤，可重复。")
@click.option("--ascending", is_flag=True, help="升序排序。")
@click.option("--top", "--limit", "limit", default=20, show_default=True, type=int, help="返回数量。")
@friendly_errors
def rank_factor_research_results(
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    start_date: str,
    end_date: str,
    contained: bool,
    metric: str,
    min_metrics: tuple[str, ...],
    max_metrics: tuple[str, ...],
    ascending: bool,
    limit: int,
) -> None:
    """Rank factor-library research results by period and metric filters."""
    data = client_from_config().list_factor_research_runs(
        factor_family=factor_family,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type=test_type,
        start_date=start_date,
        end_date=end_date,
        overlap="0" if contained else "1",
        metric=metric,
        min_metric=list(min_metrics),
        max_metric=list(max_metrics),
        ascending="1" if ascending else "",
        limit=limit,
    )
    _print_research_runs(data.get("runs") or [], metric=metric)


@factor_library.command("history")
@click.option("--factor-family", "--factor_family", default="", help="因子家族。")
@click.option("--factor-alias", "--factor_alias", default="", help="因子 alias。")
@click.option("--product-group", "--product_group", default="", help="产品组。")
@click.option("--test-type", "--test_type", default="", help="测试类型。")
@click.option("--start-date", "--start_date", default="", help="查询开始日期。")
@click.option("--end-date", "--end_date", default="", help="查询结束日期。")
@click.option("--limit", default=50, show_default=True, type=int, help="返回数量。")
@friendly_errors
def factor_research_history(
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    start_date: str,
    end_date: str,
    limit: int,
) -> None:
    """List structured research history for factor-library candidates."""
    data = client_from_config().list_factor_research_runs(
        factor_family=factor_family,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type=test_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    _print_research_runs(data.get("runs") or [], metric="")


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


def _resolve_factor_from_catalog(
    payload: dict[str, Any],
    factor_family: str,
    *,
    source_mode: str,
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
    ]
    if not matches:
        raise click.ClickException(f"找不到因子家族: {factor_family}")
    return matches[0]


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
    "rolling_argmax": {"rolling_argmax"},
    "rolling_argmin": {"rolling_argmin"},
    "shift": {"shift"},
    "delta": {"delta"},
    "cs_rank": {"cs_rank"},
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


def parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("参数必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("参数 KEY 不能为空")
    return key, value.strip()


def _research_payloads_from_artifact(
    artifact_path: Path,
    *,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    report_path: str,
    note: str,
) -> list[dict[str, Any]]:
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise click.ClickException(f"artifact 顶层必须是 JSON 对象: {artifact_path}")
    detected = _detect_research_test_type(data) if test_type == "auto" else test_type
    if detected == "ic":
        return _ic_research_payloads(data, artifact_path, factor_family, factor_alias, product_group, report_path, note)
    if detected == "backtest":
        return [_backtest_research_payload(data, artifact_path, factor_family, factor_alias, product_group, report_path, note)]
    if detected == "bucket_label":
        return [_bucket_label_research_payload(data, artifact_path, factor_family, factor_alias, product_group, report_path, note)]
    return [_generic_research_payload(data, artifact_path, factor_family, factor_alias, product_group, detected, report_path, note)]


def _detect_research_test_type(data: dict[str, Any]) -> str:
    if isinstance(data.get("groups"), list):
        return "backtest"
    if isinstance(data.get("bucket_forward_returns"), list) or isinstance(data.get("product_bucket_stats"), dict):
        return "bucket_label"
    if isinstance(data.get("summary"), dict) or isinstance(data.get("ic"), dict):
        return "ic"
    return "factor_type"


def _base_research_payload(
    data: dict[str, Any],
    artifact_path: Path,
    *,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    report_path: str,
    note: str,
    metrics: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    family = factor_family or str(data.get("family") or data.get("ff_alias") or "")
    alias = (
        factor_alias
        or str(data.get("canonical_alias") or data.get("alias") or data.get("requested_alias") or data.get("factor_alias") or "")
    )
    if not alias:
        aliases = data.get("canonical_aliases") or data.get("aliases")
        if isinstance(aliases, list) and aliases:
            alias = str(aliases[0])
    return {
        "ff_alias": family,
        "factor_alias": alias,
        "factor_source": str(data.get("factor_source") or ""),
        "product_group": product_group or str(data.get("product_group") or ""),
        "start_date": str(data.get("start_date") or ""),
        "end_date": str(data.get("end_date") or ""),
        "test_type": test_type,
        "config": config or _artifact_config(data),
        "metrics": metrics,
        "report_path": report_path,
        "artifact_path": str(artifact_path),
        "note": note,
    }


def _artifact_config(data: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key in (
        "paths",
        "mask_products",
        "local_setting_overrides",
        "payload_local_settings",
        "strategy_kind",
        "threshold_settings",
        "fee_source",
        "return_price_basis",
    ):
        if key in data:
            config[key] = data.get(key)
    return config


def _ic_research_payloads(
    data: dict[str, Any],
    artifact_path: Path,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    report_path: str,
    note: str,
) -> list[dict[str, Any]]:
    summary = data.get("summary")
    if isinstance(summary, dict) and summary:
        payloads = []
        for alias, item in summary.items():
            metrics = _ic_metrics(item if isinstance(item, dict) else {})
            payloads.append(
                _base_research_payload(
                    {**data, "canonical_alias": str(alias)},
                    artifact_path,
                    factor_family=factor_family,
                    factor_alias=factor_alias or str(alias),
                    product_group=product_group,
                    test_type="ic",
                    report_path=report_path,
                    note=note,
                    metrics=metrics,
                )
            )
        return payloads
    return [
        _base_research_payload(
            data,
            artifact_path,
            factor_family=factor_family,
            factor_alias=factor_alias,
            product_group=product_group,
            test_type="ic",
            report_path=report_path,
            note=note,
            metrics=_ic_metrics(data.get("ic") if isinstance(data.get("ic"), dict) else data),
        )
    ]


def _ic_metrics(item: dict[str, Any]) -> dict[str, Any]:
    return _compact_metrics(
        {
            "ic_mean": item.get("mean"),
            "ic_std": item.get("std"),
            "ic_ir": item.get("ir"),
            "ic_t_stat": item.get("t_stat"),
            "ic_n": item.get("n"),
            "ic_positive_rate": item.get("positive_rate"),
            "ic_decay": item.get("decay"),
        }
    )


def _backtest_research_payload(
    data: dict[str, Any],
    artifact_path: Path,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    report_path: str,
    note: str,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "elapsed_s": data.get("elapsed_s"),
        "groups": data.get("groups"),
    }
    returns: dict[str, float] = {}
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        key = _metric_safe_name(str(group.get("name") or group.get("group_id") or "portfolio"))
        if group.get("return") is not None:
            metrics[f"{key}_return"] = group.get("return")
            returns[key] = float(group.get("return"))
        if group.get("max_drawdown") is not None:
            metrics[f"{key}_max_drawdown"] = group.get("max_drawdown")
        if key.startswith("ls_") and group.get("return") is not None:
            metrics.setdefault("ls_return", group.get("return"))
            if group.get("max_drawdown") is not None:
                metrics.setdefault("ls_max_drawdown", group.get("max_drawdown"))
    if "a1" in returns and "a5" in returns:
        metrics["a1_a5_return_spread"] = returns["a1"] - returns["a5"]
    return _base_research_payload(
        data,
        artifact_path,
        factor_family=factor_family,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type="backtest",
        report_path=report_path,
        note=note,
        metrics=_compact_metrics(metrics),
    )


def _bucket_label_research_payload(
    data: dict[str, Any],
    artifact_path: Path,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    report_path: str,
    note: str,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {"return_price_basis": data.get("return_price_basis")}
    if isinstance(data.get("ic"), dict):
        metrics.update(_ic_metrics(data["ic"]))
    bucket_rows = data.get("bucket_forward_returns") or []
    if bucket_rows and isinstance(bucket_rows[0], dict):
        first = bucket_rows[0]
        means = first.get("mean") if isinstance(first.get("mean"), dict) else {}
        for name, value in means.items():
            metrics[f"{_metric_safe_name(str(name))}_label_return"] = value
        if "A1" in means and "A5" in means:
            metrics["a1_a5_label_return_spread"] = means["A1"] - means["A5"]
    metrics["bucket_forward_returns"] = data.get("bucket_forward_returns")
    metrics["product_bucket_stats"] = data.get("product_bucket_stats")
    return _base_research_payload(
        data,
        artifact_path,
        factor_family=factor_family,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type="bucket_label",
        report_path=report_path,
        note=note,
        metrics=_compact_metrics(metrics),
    )


def _generic_research_payload(
    data: dict[str, Any],
    artifact_path: Path,
    factor_family: str,
    factor_alias: str,
    product_group: str,
    test_type: str,
    report_path: str,
    note: str,
) -> dict[str, Any]:
    return _base_research_payload(
        data,
        artifact_path,
        factor_family=factor_family,
        factor_alias=factor_alias,
        product_group=product_group,
        test_type=test_type,
        report_path=report_path,
        note=note,
        metrics=_compact_metrics({key: value for key, value in data.items() if isinstance(value, (int, float))}),
    )


def _metric_safe_name(name: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "_", name.strip().lower()).strip("_")
    return value or "portfolio"


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if value is not None}


def _research_run_line(run: dict[str, Any], *, metric: str = "") -> str:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    parts = [
        str(run.get("factor_alias") or ""),
        f"{run.get('test_type') or ''}",
        f"{run.get('start_date') or ''}..{run.get('end_date') or ''}",
    ]
    if run.get("product_group"):
        parts.append(f"产品组={run.get('product_group')}")
    for key in [metric, "ls_return", "a1_return", "a5_return", "ic_mean", "ic_t_stat", "max_drawdown"]:
        if key and key in metrics:
            parts.append(f"{key}={_format_metric(metrics.get(key))}")
    return " · ".join(part for part in parts if part)


def _print_research_runs(runs: list[dict[str, Any]], *, metric: str) -> None:
    if not runs:
        click.echo("暂无研究结果")
        return
    rows = []
    for run in runs:
        metrics = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
        rows.append(
            (
                run.get("factor_alias") or "",
                run.get("test_type") or "",
                run.get("product_group") or "",
                f"{run.get('start_date') or ''}..{run.get('end_date') or ''}",
                _format_metric(metrics.get(metric)) if metric else "",
                _format_metric(metrics.get("ls_return")),
                _format_metric(metrics.get("a1_return")),
                _format_metric(metrics.get("a5_return")),
                _format_metric(metrics.get("ic_mean")),
                run.get("report_path") or run.get("artifact_path") or "",
            )
        )
    headers = ("factor", "type", "product_group", "period", metric or "metric", "ls", "a1", "a5", "ic", "artifact/report")
    for line in render_table(headers, rows, max_widths=(40, 12, 18, 24, 10, 10, 10, 10, 10, 50)):
        click.echo(line)


def _format_metric(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4g}"
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def _print_workspace_git_action(payload: dict[str, Any]) -> None:
    stdout = str(payload.get("stdout") or "").rstrip()
    stderr = str(payload.get("stderr") or "").rstrip()
    if stdout:
        click.echo(stdout)
    if stderr:
        click.echo(stderr, err=True)
    if payload.get("commit_sha"):
        click.echo(f"commit: {payload.get('commit_sha')}")
