"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import print_backtest_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.field_help import field_flag, field_type_label, render_settings_help
from tools.cli.field_store import FieldStore
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY
from tools.cli.modules.products.controller import product_group_selection
from tools.cli.modules.backtest.shared.fields import resolve_backtest_public_fields
from tools.cli.modules.backtest.shared.selectors import (
    AddGroupSelectors,
    parse_add_group_selectors,
    parse_add_group_selector_groups,
    parse_long_short_selector,
    resolve_factor_family_selector,
    resolve_factor_selector,
    resolve_product_group_selector,
    selection_label,
)
from tools.cli.modules.backtest.run_output import BacktestRunRenderer
from tools.cli.modules.backtest.run_output import _chart_body_width, _multi_series_chart, _result_series
from tools.cli.state import BACKTEST_SPACE, load_state, save_state, switch_backtest_space
from tools.cli.table import render_table


SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}
SELECTOR_HELP_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}
_ADD_GROUP_SELECTOR_ROOTS = {
    "--add", "--batch",
    "--derive", "--copy",
    "--group-name", "--group_name",
    "--group-names", "--group_names",
    "--factor-family", "--factor_family",
    "--split-count", "--split_count",
    "--group-index", "--group_index",
    "--name",
    "--factor", "--factor-candidates", "--alias", "--from-candidates",
    "--param", "--factor-param", "--factor_param", "--index", "--factor-product-group",
    "--product-group", "--product-path-candidates",
    "--product-path", "--product_path",
    "--product-path-name", "--product_path_name",
    "--product-path-path", "--product_path_path",
    "--path",
}


@click.group("backtest", invoke_without_command=True, context_settings=SELECTOR_CONTEXT)
@click.option("--run", is_flag=True, help="运行当前 backtest 草稿中的全部策略。")
@click.option("--verbose", is_flag=True, help="运行时打印完整 SSE 进度事件摘要。")
@click.pass_context
@friendly_errors
def backtest(
    ctx: click.Context,
    run: bool,
    verbose: bool,
) -> None:
    """进入通用回测控制界面。

    \b
    回测与 single_factor_test 平行注册；因子家族在具体需要因子的动作中指定:
      factortester backtest group --add --factor-family SgCCS --factor 'SgCCS|N:2m|$F:1m|$Rev'

    \b
    常用草稿命令:
      factortester backtest local-settings --allocation-mode equal_notional
      factortester backtest group --add --group-name A1 --split-count 5 --group-index 1 --factor-family SgCCS
      factortester backtest group --add --factor-family SgCCS --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'
      factortester backtest group --add --factor-family SgCCS --factor add --param N=2m --param '$Rev=1'
      factortester backtest group --add --product-group from-candidates --name 中国期货日盘
      factortester backtest group --group-name A1 --derive --group-name A1a --product-path ...
      factortester backtest group --group-name A1 --copy --group-name A1-copy
      factortester backtest long-short --add --ls-name LS-A1-A5 --long-group A1 --short-group A5
      factortester backtest strategy-book ledger --strategy A1 --ledger shared --cash-pool pool-main
      factortester backtest ledger-config --ledger shared --fee-mode auto --margin-mode auto
      factortester backtest template --from-module-template single_factor_test load "2026-06-02 07:20:47"
      factortester backtest template save "CLI 草稿"
      factortester backtest clear

    \b
    字段级帮助:
      factortester group --add --group-name --help
      factortester group --add --group-name A1 --help
    """
    if ctx.invoked_subcommand is not None:
        state = load_state()
        switch_backtest_space(state, BACKTEST_SPACE)
        save_state(state)
        return
    state = load_state()
    enter_backtest_state(state, scope=BACKTEST_SPACE)
    save_state(state)
    if run:
        _run_backtest(state, groups=state.backtest_groups, verbose=verbose)
        return
    print_backtest_welcome(state)


@backtest.command("template", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def template(ctx: click.Context) -> None:
    """管理 backtest 设置模板的便捷入口。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    args = tuple(ctx.args)
    source_module = ""
    if args[:1] == ("--from-module-template",):
        if len(args) < 3:
            raise click.ClickException("--from-module-template 需要模块名和动作，例如: --from-module-template single_factor_test load <模板>")
        source_module = args[1]
        if source_module not in {"single_factor_test", "single_factor_family_test"}:
            raise click.ClickException(f"暂不支持从该模块模板导入: {source_module}")
        args = args[2:]
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_backtest_template_help(state)
        return
    if not state.factor_family:
        raise click.ClickException("template 命令需要先选择因子家族：factortester single_factor_test --factor-family SgCCS")
    if args[0] in {"list", "ls"}:
        _list_backtest_templates(state.factor_family)
        return
    if args[0] == "load":
        if len(args) < 2:
            raise click.ClickException("template load 需要模板 ID 或名称")
        _load_backtest_template_into_state(state, args[1], source_module=source_module)
        save_state(state)
        return
    if args[0] == "save":
        name = args[1] if len(args) >= 2 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_backtest_template_from_state(state, name)
        save_state(state)
        return
    raise click.ClickException("template 支持的动作: list, load, save, help")


@backtest.command("local-settings", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def local_settings(ctx: click.Context) -> None:
    """配置回测 local-settings。"""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state, scope=BACKTEST_SPACE)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    setting_args = _strip_context_help(args)
    if setting_args:
        _apply_raw_local_settings(state, setting_args)
    if show_help:
        _validate_registered_local_settings(state)
        _print_backtest_settings_help(state)
        return
    save_state(state)
    click.echo("已更新 local-settings")
    print_backtest_welcome(state)


@backtest.command("strategy-book", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def strategy_book(ctx: click.Context) -> None:
    """配置 strategy -> ledger -> cash pool 拓扑。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    args = tuple(ctx.args)
    if not args or args[0] in {"show", "list", "ls"}:
        _print_strategy_book(state)
        return
    if args[0] in {"help", "--help", "-h"}:
        _print_strategy_book_help()
        return
    if args[0] == "simple":
        state.backtest_strategy_book.clear()
        save_state(state)
        click.echo("已切换为 StrategyBookSimple: 每个 strategy 一个私有 ledger / cash pool")
        return
    if args[0] == "ledger":
        _apply_strategy_book_ledger(state, args[1:])
        save_state(state)
        _print_strategy_book(state)
        return
    if args[0] == "cash-pool":
        _apply_strategy_book_cash_pool(state, args[1:])
        save_state(state)
        _print_strategy_book(state)
        return
    raise click.ClickException("strategy-book 支持: show, simple, ledger, cash-pool")


@backtest.command("ledger-config", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def ledger_config(ctx: click.Context) -> None:
    """配置 ledger-owned 字段，如费用、保证金、DMTM、现金保留。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    args = tuple(ctx.args)
    if not args or args[0] in {"show", "list", "ls"}:
        _print_ledger_configs(state)
        return
    if args[0] in {"help", "--help", "-h"}:
        _print_ledger_config_help()
        return
    ledger = _arg_value(args, "--ledger")
    if not ledger:
        raise click.ClickException("ledger-config 必须传 --ledger LEDGER")
    values = _parse_ledger_config_args(args)
    if not values:
        raise click.ClickException("ledger-config 缺少要设置的字段；用 --help 查看支持字段")
    current = dict(state.backtest_ledger_configs.get(ledger) or {})
    current.update(values)
    state.backtest_ledger_configs[ledger] = current
    save_state(state)
    click.echo(f"已更新 ledger config: {ledger}")
    _print_ledger_configs(state)


@backtest.command("clear")
@click.option("--page-settings", is_flag=True, help="同时清空 single_factor_test 页面级设置。")
@friendly_errors
def clear(page_settings: bool) -> None:
    """清空当前 backtest 配置草稿。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    state.backtest_local_settings.clear()
    state.backtest_strategy_book.clear()
    state.backtest_ledger_configs.clear()
    state.backtest_groups.clear()
    state.backtest_ls_configs.clear()
    state.backtest_last_result.clear()
    if page_settings:
        state.page_settings.clear()
    save_state(state)
    click.echo("已清空 backtest 配置")
    if page_settings:
        click.echo("已同时清空页面级设置")


@backtest.command("results", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def results(ctx: click.Context) -> None:
    """查看最近一次 backtest 运行结果。

    \b
    常用命令:
      factortester backtest results summary
      factortester backtest results equity
      factortester backtest results snapshot --index 1
      factortester backtest results order-flow --group-name A1
    """
    state = load_state()
    args = tuple(ctx.args)
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_results_help()
        return
    action = args[0]
    if action == "summary":
        _print_stored_result_summary(state)
        return
    if action == "equity":
        _print_stored_equity_chart(state)
        return
    if action == "snapshot":
        _print_snapshot_result(state, args[1:])
        return
    if action in {"order-flow", "orders"}:
        _print_order_flow_result(state, args[1:])
        return
    raise click.ClickException("results 支持: summary, equity, snapshot, order-flow")


def _print_backtest_template_help(state) -> None:
    click.echo("backtest template 命令")
    current = state.factor_family or "（未选择）"
    click.echo(f"当前因子家族: {current}")
    click.echo("  list / ls                 列出当前因子家族的设置模板")
    click.echo("  load <模板ID或名称>        加载模板到顶层 backtest 草稿")
    click.echo("  --from-module-template single_factor_test load <模板>  从 single_factor_test 模板显式导入")
    click.echo("  save [模板名]              保存当前 CLI 草稿为设置模板")
    click.echo("")
    click.echo("示例:")
    click.echo("  factortester single_factor_test --factor-family SgCCS")
    click.echo("  factortester backtest template list")
    click.echo("  factortester backtest template --from-module-template single_factor_test load '2026-06-02 07:20:47'")
    click.echo("  factortester backtest template save 'CLI 草稿'")


def _list_backtest_templates(factor_family: str) -> None:
    templates = client_from_config().list_single_factor_setting_templates(factor_family)
    click.echo(f"{factor_family} 模板列表")
    if not templates:
        click.echo("  （空）")
        return
    for index, template in enumerate(templates, start=1):
        click.echo(f"  {index}. {template.get('name') or template.get('id')} · id={template.get('id')}")


def _load_backtest_template_into_state(state, selector: str, *, source_module: str = "") -> None:
    client = client_from_config()
    templates = client.list_single_factor_setting_templates(state.factor_family)
    template_id = _resolve_template_id(selector, templates)
    template = client.get_single_factor_setting_template(state.factor_family, template_id)
    snapshot = template.get("snapshot")
    if not isinstance(snapshot, dict):
        raise click.ClickException("模板缺少 snapshot")
    applied = _apply_snapshot_to_backtest_state(state, snapshot, template_name=str(template.get("name") or selector))
    registered = _register_template_factors(state, client)
    source = f"（来自 {source_module} 模板）" if source_module else ""
    click.echo(f"已加载模板: {template.get('name') or selector}{source}")
    factor_text = f" · 已注册因子: {registered}" if registered else ""
    click.echo(
        f"页面字段: {applied['page_settings']} · local-settings: {applied['local_settings']} "
        f"· groups: {applied['groups']} · long-short: {applied['ls_configs']}{factor_text}"
    )


def _save_backtest_template_from_state(state, name: str) -> None:
    snapshot = _snapshot_from_backtest_state(state)
    data = client_from_config().save_single_factor_setting_template(state.factor_family, name=name, snapshot=snapshot)
    template_id = data.get("id") or ""
    state.page_settings["setting_template"] = name
    click.echo(f"已保存模板: {name}")
    if template_id:
        click.echo(f"id={template_id}")


def _resolve_template_id(selector: str, templates: list[dict[str, Any]]) -> str:
    for index, template in enumerate(templates, start=1):
        keys = {str(index), str(template.get("id") or ""), str(template.get("name") or "")}
        if selector in keys:
            return str(template.get("id") or "")
    raise click.ClickException(f"找不到模板: {selector}")


def _apply_snapshot_to_backtest_state(state, snapshot: dict[str, Any], *, template_name: str) -> dict[str, int]:
    factors_raw = snapshot.get("factors")
    factors: dict[str, Any] = dict(factors_raw) if isinstance(factors_raw, dict) else {}
    for key in ("factor_candidates", "factor"):
        if key in factors:
            state.page_settings[key] = factors[key]
    state.page_settings["setting_template"] = template_name

    local_settings = snapshot.get("local_settings") if isinstance(snapshot.get("local_settings"), dict) else {}
    state.backtest_local_settings = dict(local_settings or {})

    group_settings_raw = snapshot.get("group_settings")
    group_settings: dict[str, Any] = dict(group_settings_raw) if isinstance(group_settings_raw, dict) else {}
    state.backtest_groups = [
        _normalize_template_group(item)
        for item in (group_settings.get("groups") or [])
        if isinstance(item, dict)
    ]
    state.backtest_ls_configs = [
        _normalize_template_ls(item)
        for item in (group_settings.get("lsConfigs") or [])
        if isinstance(item, dict)
    ]
    return {
        "page_settings": len(factors) + 1,
        "local_settings": len(state.backtest_local_settings),
        "groups": len(state.backtest_groups),
        "ls_configs": len(state.backtest_ls_configs),
    }


def _snapshot_from_backtest_state(state) -> dict[str, Any]:
    factors: dict[str, Any] = {}
    for key in ("factor_candidates", "factor", "setting_template"):
        if key in state.page_settings:
            factors[key] = state.page_settings[key]
    return {
        "factors": factors,
        "local_settings": dict(state.backtest_local_settings),
        "group_settings": {
            "groups": [dict(group) for group in state.backtest_groups],
            "lsConfigs": [dict(config) for config in state.backtest_ls_configs],
        },
    }


def _normalize_template_group(group: dict[str, Any]) -> dict[str, Any]:
    out = dict(group)
    _rename_if_present(out, "splitCount", "split_count")
    _rename_if_present(out, "groupIndex", "group_index")
    _rename_if_present(out, "factorAlias", "factor")
    _rename_if_present(out, "isAllGroups", "is_all_groups")
    return out


def _normalize_template_ls(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    _rename_if_present(out, "longGroupId", "long_group_id")
    _rename_if_present(out, "shortGroupId", "short_group_id")
    return out


def _rename_if_present(target: dict[str, Any], old: str, new: str) -> None:
    if old in target and new not in target:
        target[new] = target[old]


def _register_template_factors(state, client) -> int:
    aliases = _template_factor_aliases(state)
    if not aliases or not state.page_uuid:
        return 0
    candidates = list(state.page_settings.get("factor_candidates") or [])
    known = {
        str(item.get("factor_alias") or item.get("alias") or "")
        for item in candidates
        if isinstance(item, dict)
    }
    registered = 0
    for alias in aliases:
        params = _params_from_factor_alias(alias, state.factor_family)
        data = client.add_candidate("factor", {
            "factor_family_alias": state.factor_family,
            "params": params,
            "page_uuid": state.page_uuid,
        })
        factor_alias = str(data.get("factor_alias") or alias)
        if factor_alias not in known:
            candidates.append({"factor_alias": factor_alias, "params": params})
            known.add(factor_alias)
        registered += 1
    state.page_settings["factor_candidates"] = candidates
    if aliases:
        state.page_settings["factor"] = aliases[0]
    return registered


def _template_factor_aliases(state) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for group in state.backtest_groups:
        if not isinstance(group, dict):
            continue
        alias = str(group.get("factor") or group.get("factorAlias") or "").strip()
        if alias and alias not in seen:
            seen.add(alias)
            aliases.append(alias)
    return aliases


def _params_from_factor_alias(alias: str, factor_family: str) -> dict[str, Any]:
    prefix = f"{factor_family}|"
    if alias == factor_family:
        return {}
    if not alias.startswith(prefix):
        raise click.ClickException(f"模板因子 {alias} 不属于当前因子家族 {factor_family}")
    params: dict[str, Any] = {}
    for part in alias[len(prefix):].split("|"):
        if not part:
            continue
        if ":" in part:
            key, value = part.split(":", 1)
            if value.startswith("[") and value.endswith("]"):
                value = value[1:-1]
            params[key] = value
        elif part == "$Rev":
            params[part] = "1"
        else:
            params[part] = True
    return params


@backtest.command("group", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def group(
    ctx: click.Context,
) -> None:
    """管理回测分组草稿。

    常用动作:

      factortester group list
      factortester group --add --group-name A1 --split-count 5 --group-index 1
      factortester group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5
      factortester group --group-name A1 --edit --factor --alias SgCCS|N:2m
      factortester group --group-name A1 --derive --group-name A1a
      factortester group --group-name A1 --copy --group-name A1-copy
      factortester group --group-names A1 A5 --edit --allocation-policy equal_notional
      factortester group --group-name A1 --describe
      factortester group --group-name A1 --run

    字段说明模式:

      factortester group --add --group-name --help
      factortester group --add --batch --help

    上下文校验模式:

      factortester group --add --group-name A1 --help
    """
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state, scope=BACKTEST_SPACE)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    verbose = "--verbose" in args
    args = tuple(arg for arg in args if arg != "--verbose")
    help_target = _context_help_target(args)
    clean_args = _strip_context_help(args)
    if _is_list_action(clean_args):
        _print_group_list(state)
        return
    action = _group_action(clean_args)
    selector_args, setting_args = _split_selector_and_local_setting_args(_strip_group_action_args(clean_args), selector_roots=_ADD_GROUP_SELECTOR_ROOTS)
    group_settings = _parse_raw_settings(tuple(setting_args)) if setting_args else {}
    if show_help and help_target and not help_target.has_value:
        _print_group_field_help(state, help_target.option, batch="--batch" in clean_args)
        return
    if show_help:
        _validate_settings_dict(state, group_settings)
        if action == "add" and "--batch" in clean_args:
            _print_group_batch_help()
        else:
            _print_backtest_settings_help(state, values=group_settings)
        return
    if action == "add":
        selectors_list = _parse_group_add_selectors(tuple(selector_args), batch="--batch" in clean_args)
        for selectors in selectors_list:
            _append_group(state, selectors=selectors, extra_values=group_settings)
        click.echo(f"新增分组: {len(selectors_list)}")
        for group_item in state.backtest_groups[-len(selectors_list):]:
            _print_group(group_item)
    elif action == "edit":
        groups = _selected_groups(state, clean_args)
        selectors = parse_add_group_selectors(_remove_group_name_args(tuple(selector_args)))
        for group_item in groups:
            _edit_group(state, group_item, selectors=selectors, extra_values=group_settings)
        click.echo(f"已修改分组: {len(groups)}")
        for group_item in groups:
            _print_group(group_item)
    elif action in {"derive", "copy"}:
        created = _derive_or_copy_groups(state, clean_args, selectors_args=tuple(selector_args), extra_values=group_settings, derived=action == "derive")
        click.echo(f"新增{'派生' if action == 'derive' else '复制'}分组: {len(created)}")
        for group_item in created:
            _print_group(group_item)
    elif action == "describe":
        for group_item in _selected_groups(state, clean_args):
            _print_group(group_item)
    elif action == "run":
        _run_backtest(state, groups=_selected_groups(state, clean_args, default_all=True), verbose=verbose)
    else:
        raise click.ClickException("group 需要明确动作：list、--add、--edit、--describe 或 --run")
    save_state(state)
    if action == "add":
        click.echo("下一步: 这些参数会进入 backtest/group-test 的配置草稿；运行接口接好后可直接提交。")


@backtest.command("long-short", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def long_short(ctx: click.Context) -> None:
    """管理 Long-Short 策略草稿。"""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state, scope=BACKTEST_SPACE)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    clean_args = _strip_context_help(args)
    if _is_list_action(clean_args):
        _print_long_short_list(state)
        return
    if show_help:
        _validate_registered_local_settings(state)
        _print_backtest_settings_help(state)
        return
    if "--add" not in clean_args:
        raise click.ClickException("long-short 需要明确动作：list 或 --add")
    selector = parse_long_short_selector(tuple(arg for arg in clean_args if arg != "--add"))
    long_group = _resolve_ls_leg(state, selector.long_leg, side="long")
    short_group = _resolve_ls_leg(state, selector.short_leg, side="short")
    config: dict[str, Any] = {
        "name": selector.name or f"LS {long_group.get('name') or long_group.get('id')} / {short_group.get('name') or short_group.get('id')}",
        "long_group": _group_ref(long_group),
        "short_group": _group_ref(short_group),
    }
    state.backtest_ls_configs.append(config)
    save_state(state)
    click.echo("新增 Long-Short")
    click.echo(f"名称: {config['name']}")
    long_ref = config["long_group"]
    short_ref = config["short_group"]
    click.echo(f"多头: {long_ref.get('name') or long_ref.get('id')}")
    click.echo(f"空头: {short_ref.get('name') or short_ref.get('id')}")


def enter_backtest_state(state, *, scope: str = BACKTEST_SPACE) -> None:
    switch_backtest_space(state, scope)
    if state.current_parent == "single_factor_family_test":
        ensure_child_available(state.current_parent, BACKTEST_BACKEND_KEY)
        state.enter(BACKTEST_BACKEND_KEY)
        return
    ensure_child_available(None, BACKTEST_PUBLIC_KEY)
    state.enter(BACKTEST_PUBLIC_KEY)


def _apply_raw_local_settings(state, args: tuple[str, ...]) -> None:
    state.backtest_local_settings.update(_parse_raw_settings(args))


def _parse_raw_settings(args: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if "=" in token and not token.startswith("--"):
            key, value = _parse_key_value(token)
            values[key] = value
            i += 1
            continue
        if not token.startswith("--"):
            raise click.ClickException(f"无法识别设置参数: {token}")
        key = token[2:].replace("-", "_")
        if not key:
            raise click.ClickException("设置字段名不能为空")
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            parsed_value: Any = True
            i += 1
        else:
            parsed_value = args[i + 1]
            i += 2
        values[key] = parsed_value
    return values


def _parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("local-settings 必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("local-settings 的 KEY 不能为空")
    return key, value.strip()


def _has_context_help(args: tuple[str, ...]) -> bool:
    return "--help" in args or "-h" in args


class _HelpTarget:
    def __init__(self, option: str, *, has_value: bool) -> None:
        self.option = option
        self.has_value = has_value


def _context_help_target(args: tuple[str, ...]) -> _HelpTarget | None:
    help_positions = [index for index, token in enumerate(args) if token in {"--help", "-h"}]
    if not help_positions:
        return None
    help_index = help_positions[0]
    if help_index == 0:
        return None
    previous = args[help_index - 1]
    if previous.startswith("--"):
        return _HelpTarget(previous, has_value=False)
    for index in range(help_index - 2, -1, -1):
        token = args[index]
        if token.startswith("--"):
            return _HelpTarget(token, has_value=True)
    return None


def _strip_context_help(args: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(arg for arg in args if arg not in {"--help", "-h"})


def _is_list_action(args: tuple[str, ...]) -> bool:
    return bool(args) and args[0] == "list"


def _group_action(args: tuple[str, ...]) -> str:
    if "--add" in args:
        return "add"
    if "--derive" in args:
        return "derive"
    if "--copy" in args:
        return "copy"
    if "--edit" in args:
        return "edit"
    if "--describe" in args:
        return "describe"
    if "--run" in args:
        return "run"
    return ""


def _strip_group_action_args(args: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    removed_action_add = False
    for arg in args:
        if arg == "--add" and not removed_action_add:
            removed_action_add = True
            continue
        if arg in {"--edit", "--describe", "--run", "--batch", "--derive", "--copy"}:
            continue
        result.append(arg)
    return tuple(result)


def _group_names_from_args(args: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--group-name", "--group_name"}:
            names.append(_require_arg_value(args, i, token))
            i += 2
            continue
        if token in {"--group-names", "--group_names"}:
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                names.append(args[i])
                i += 1
            continue
        i += 1
    return names


def _require_arg_value(args: tuple[str, ...], index: int, option: str) -> str:
    if index + 1 >= len(args) or args[index + 1].startswith("--"):
        raise click.ClickException(f"{option} 缺少参数")
    return args[index + 1]


def _split_selector_and_local_setting_args(args: tuple[str, ...], *, selector_roots: set[str]) -> tuple[list[str], list[str]]:
    selector_args: list[str] = []
    setting_args: list[str] = []
    selector_mode = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--add":
            selector_mode = True
            selector_args.append(token)
            i += 1
            continue
        if token in selector_roots:
            selector_mode = True
            selector_args.append(token)
            if i + 1 < len(args) and not (args[i + 1].startswith("--") and args[i + 1] not in {"--from-candidates"}):
                selector_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if token.startswith("--") and not selector_mode:
            setting_args.append(token)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                setting_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if token.startswith("--"):
            setting_args.append(token)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                setting_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        selector_args.append(token)
        i += 1
    return selector_args, setting_args


def _validate_registered_local_settings(state) -> None:
    _validate_settings_dict(state, state.backtest_local_settings, prefix="local-settings")


def _validate_settings_dict(state, values: dict[str, Any], *, prefix: str = "设置") -> None:
    _, store = _stores_for_backtest(state)
    unknown = [key for key in values if key not in store.defaults]
    if unknown:
        raise click.ClickException(f"{prefix} 包含未注册字段: " + ", ".join(sorted(unknown)))
    for key, value in values.items():
        try:
            store.validate_value(key, value)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None


def _print_backtest_settings_help(state, *, values: dict[str, Any] | None = None) -> None:
    _, store = _stores_for_backtest(state)
    for key, value in (values or {}).items():
        store.set(key, value)
    for line in render_settings_help(store, title="回测设置上下文"):
        click.echo(line)


def _print_group_field_help(state, option: str, *, batch: bool = False) -> None:
    if option == "--add":
        _print_group_add_help()
        return
    if option == "--batch":
        _print_group_batch_help()
        return
    _print_add_group_field_help(state, option)
    if batch:
        click.echo("  批量新增中 --group-index 由 --group-names 的顺序自动生成。")


def _print_group_add_help() -> None:
    click.echo("group --add 动作说明")
    click.echo("  用途: 新增一个或多个分组策略草稿。")
    click.echo("  单个新增: group --add --group-name A1 --split-count 5 --group-index 1")
    click.echo("  批量新增: group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5")
    click.echo("  产品路径: --product-group from-candidates --name 中国期货日盘")
    click.echo("  因子: --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'")


def _print_group_batch_help() -> None:
    click.echo("group --add --batch 字段说明")
    click.echo("  用途: 一次新增一个分组集合中的所有组。")
    click.echo("  必填: --group-names NAME...，例如 A1 A2 A3 A4 A5")
    click.echo("  分组数: 省略 --split-count 时默认等于 group-names 个数。")
    click.echo("  分组序号: 不允许填写 --group-index；按 group-names 顺序自动生成 1..N。")
    click.echo("  写法: factortester group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5")


def _print_add_group_field_help(state, option: str) -> None:
    field_key = _field_key_for_option(option)
    if field_key is None:
        raise click.ClickException(f"无法识别 group 字段: {option}")
    _, store = _stores_for_backtest(state)
    meta = store.field(field_key)
    if meta:
        click.echo(f"{option} 字段说明")
        click.echo(f"  后端字段: {field_key}")
        click.echo(f"  中文名: {meta.get('label') or field_key}")
        click.echo(f"  类型: {field_type_label(meta)}")
        click.echo(f"  默认值: {meta.get('value')!r}")
        click.echo(f"  可见: {'是' if store.is_visible(field_key) else '否'}")
        click.echo(f"  可编辑: {'是' if store.is_editable(field_key) else '否'}")
        if meta.get("options"):
            options = ", ".join(
                f"{item.get('value')}({item.get('label') or item.get('value')})"
                for item in meta["options"]
                if isinstance(item, dict)
            )
            click.echo(f"  允许值: {options}")
        if meta.get("help_text"):
            click.echo(f"  说明: {meta['help_text']}")
        click.echo(f"  写法: {field_flag(field_key)} VALUE")
        return
    local = _ADD_GROUP_LOCAL_FIELD_HELP.get(field_key)
    if local is None:
        raise click.ClickException(f"字段尚未由后端注册: {field_key}")
    click.echo(f"{option} 字段说明")
    click.echo(f"  字段: {field_key}")
    click.echo(f"  中文名: {local['label']}")
    click.echo(f"  类型: {local['type']}")
    click.echo(f"  说明: {local['help']}")
    click.echo(f"  写法: {option} {local['metavar']}")


def _field_key_for_option(option: str) -> str | None:
    normalized = option.lstrip("-").replace("-", "_")
    aliases = {
        "name": "group_name",
        "group_name": "group_name",
        "factor_family": "factor_family",
        "split_count": "split_count",
        "group_index": "group_index",
        "product_group": "product_path_selection",
        "product_path": "product_path_selection",
        "product_path_candidates": "product_path_candidates",
        "factor": "factor",
        "factor_candidates": "factor_candidates",
    }
    return aliases.get(normalized, normalized or None)


_ADD_GROUP_LOCAL_FIELD_HELP = {
    "group_name": {
        "label": "分组名称",
        "type": "str",
        "metavar": "NAME",
        "help": "当前新增分组在回测草稿中的显示名称；不参与后端因子或交易语义。",
    },
    "factor_family": {
        "label": "因子家族",
        "type": "str",
        "metavar": "ALIAS",
        "help": "仅用于本次分组中解析或现场创建因子；backtest 模块本身不绑定因子家族。",
    },
}


def _parse_group_add_selectors(args: tuple[str, ...], *, batch: bool) -> list[AddGroupSelectors]:
    if not batch:
        names = _group_names_from_args(args)
        if not names:
            raise click.ClickException("group --add 必须传 --group-name；不再支持 group --group-name 直接新增")
        return parse_add_group_selector_groups(args)
    if "--group-index" in args or "--group_index" in args:
        raise click.ClickException("group --add --batch 不允许传 --group-index；序号由 --group-names 顺序自动生成")
    names = _group_names_from_args(args)
    if not names:
        raise click.ClickException("group --add --batch 必须传 --group-names NAME...")
    base_args = _remove_group_name_args(args)
    base = parse_add_group_selectors(base_args)
    split_count = base.split_count or len(names)
    selectors: list[AddGroupSelectors] = []
    for index, name in enumerate(names, start=1):
        item = parse_add_group_selectors(base_args)
        item.group_name = name
        item.split_count = split_count
        item.group_index = index
        selectors.append(item)
    return selectors


def _remove_group_name_args(args: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--group-name", "--group_name"}:
            i += 2
            continue
        if token in {"--group-names", "--group_names"}:
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                i += 1
            continue
        result.append(token)
        i += 1
    return tuple(result)


def _derive_or_copy_groups(
    state,
    args: tuple[str, ...],
    *,
    selectors_args: tuple[str, ...],
    extra_values: dict[str, Any] | None,
    derived: bool,
) -> list[dict[str, Any]]:
    names = _group_names_from_args(args)
    if len(names) < 2:
        raise click.ClickException("group --derive/--copy 需要先传源分组，再传至少一个新分组名：--group-name A1 --derive --group-name A1a")
    source = _find_group_by_name(state, names[0])
    selectors = parse_add_group_selectors(_remove_group_name_args(selectors_args))
    created: list[dict[str, Any]] = []
    for target_name in names[1:]:
        group_item = dict(source)
        group_item["id"] = f"group-{len(state.backtest_groups) + 1}"
        group_item["name"] = target_name
        if derived:
            group_item["parent_id"] = source.get("id")
            group_item["parentId"] = source.get("id")
        else:
            group_item.pop("parent_id", None)
            group_item.pop("parentId", None)
        _edit_group(state, group_item, selectors=selectors, extra_values=extra_values)
        state.backtest_groups.append(group_item)
        created.append(group_item)
    return created


def _append_group(
    state,
    *,
    selectors: AddGroupSelectors,
    extra_values: dict[str, Any] | None = None,
) -> None:
    client = client_from_config()
    _ensure_page_candidates(state, client)
    page_store, backtest_store = _stores_for_backtest(state, client)
    fields = resolve_backtest_public_fields(backtest_store)
    product_selection = resolve_product_group_selector(state, selectors.product_group, fields=fields)
    if product_selection:
        backtest_store.set(fields.product_path_selection, product_selection)
    product_group_label = selection_label(backtest_store.effective(fields.product_path_selection))
    factor_family = resolve_factor_family_selector(state, client, selectors)
    factor = resolve_factor_selector(
        state,
        client,
        selectors.factor,
        factor_family=factor_family,
        product_group_label=product_group_label,
        fields=fields,
    )
    if factor:
        backtest_store.set(fields.factor, factor)
    elif not selectors.factor_family_path and not backtest_store.effective(fields.factor):
        _load_default_factor_for_product_group(state, client, page_store, factor_family=factor_family, product_group_label=product_group_label)
    resolved_product_path = backtest_store.effective(fields.product_path_selection)
    resolved_factor = backtest_store.effective(fields.factor)
    if not resolved_product_path:
        raise click.ClickException("新增分组缺少 product_path_selection；请先配置产品组库或传 --product-path")
    if not resolved_factor:
        raise click.ClickException("新增分组缺少 factor；请先配置因子库或传 --factor/--factor-param")
    state.page_settings = page_store.to_payload()
    state.backtest_local_settings = backtest_store.to_payload()
    payload: dict[str, Any] = {}
    if selectors.split_count is not None:
        payload["split_count"] = selectors.split_count
    if selectors.group_index is not None:
        payload["group_index"] = selectors.group_index
    payload["product_path_selection"] = resolved_product_path
    payload["factor"] = resolved_factor
    if factor_family:
        payload["factor_family_alias"] = factor_family
    if selectors.group_name:
        payload["name"] = selectors.group_name
    if extra_values:
        payload.update(extra_values)
    payload.setdefault("id", f"group-{len(state.backtest_groups) + 1}")
    state.backtest_groups.append(payload)


def _edit_group(
    state,
    group: dict[str, Any],
    *,
    selectors: AddGroupSelectors,
    extra_values: dict[str, Any] | None = None,
) -> None:
    if selectors.group_name:
        group["name"] = selectors.group_name
    if selectors.split_count is not None:
        group["split_count"] = selectors.split_count
    if selectors.group_index is not None:
        group["group_index"] = selectors.group_index
    client = client_from_config()
    _ensure_page_candidates(state, client)
    page_store, backtest_store = _stores_for_backtest(state, client)
    fields = resolve_backtest_public_fields(backtest_store)
    product_selection = resolve_product_group_selector(state, selectors.product_group, fields=fields)
    if product_selection:
        group["product_path_selection"] = product_selection
    factor_family = resolve_factor_family_selector(state, client, selectors)
    factor = resolve_factor_selector(
        state,
        client,
        selectors.factor,
        factor_family=factor_family or str(group.get("factor_family_alias") or state.factor_family or ""),
        product_group_label=selection_label(group.get("product_path_selection")),
        fields=fields,
    )
    if factor:
        group["factor"] = factor
    if factor_family:
        group["factor_family_alias"] = factor_family
    if extra_values:
        group.update(extra_values)
    state.page_settings = page_store.to_payload()
    state.backtest_local_settings = backtest_store.to_payload()


def _resolve_ls_leg(state, leg, *, side: str) -> dict[str, Any]:
    if leg.group is not None:
        before = len(state.backtest_groups)
        _append_group(state, selectors=leg.group)
        group = state.backtest_groups[-1]
        if not group.get("name"):
            group["name"] = f"{side}-{before + 1}"
        return group
    if leg.group_name:
        return _find_group_by_name(state, leg.group_name)
    raise click.ClickException(f"long-short 缺少 {side} leg；请传 --{side}-group GROUP 或 --{side}-group --add ...")


def _find_group_by_name(state, name: str) -> dict[str, Any]:
    for group in state.backtest_groups:
        if name in {str(group.get("name") or ""), str(group.get("id") or "")}:
            return group
    raise click.ClickException(f"找不到分组: {name}")


def _selected_groups(state, args: tuple[str, ...], *, default_all: bool = False) -> list[dict[str, Any]]:
    names = _group_names_from_args(args)
    if not names:
        if default_all:
            return list(state.backtest_groups)
        raise click.ClickException("请用 --group-name 或 --group-names 选择分组")
    return [_find_group_by_name(state, name) for name in names]


def _print_group_list(state) -> None:
    click.echo("分组列表")
    if not state.backtest_groups:
        click.echo("  （空）")
        return
    for index, group_item in enumerate(state.backtest_groups, start=1):
        name = group_item.get("name") or group_item.get("id") or f"group-{index}"
        parts = [str(name)]
        split_count = group_item.get("split_count", group_item.get("splitCount"))
        group_index = group_item.get("group_index", group_item.get("groupIndex"))
        factor = group_item.get("factor", group_item.get("factorAlias"))
        if split_count is not None:
            parts.append(f"分组数={split_count}")
        if group_index is not None:
            parts.append(f"分组序号={group_index}")
        product_path = selection_label(group_item.get("product_path_selection"))
        if product_path:
            parts.append(f"产品路径={product_path}")
        if factor:
            parts.append(f"因子={factor}")
        click.echo(f"  {index}. " + " · ".join(parts))


def _print_long_short_list(state) -> None:
    click.echo("Long-Short 列表")
    if not state.backtest_ls_configs:
        click.echo("  （空）")
        return
    for index, config in enumerate(state.backtest_ls_configs, start=1):
        long_group = config.get("long_group") or {}
        short_group = config.get("short_group") or {}
        long_label = long_group.get("name") or long_group.get("id") or config.get("long_group_id") or config.get("longGroupId")
        short_label = short_group.get("name") or short_group.get("id") or config.get("short_group_id") or config.get("shortGroupId")
        click.echo(
            f"  {index}. {config.get('name') or f'ls-{index}'} · "
            f"多头={long_label} · "
            f"空头={short_label}"
        )


def _strategy_book_payload(state) -> dict[str, Any]:
    payload = dict(state.backtest_strategy_book or {})
    payload.setdefault("strategies", {})
    payload.setdefault("cash_pools", {})
    payload.setdefault("cash_pool_configs", {})
    return payload


def _apply_strategy_book_ledger(state, args: tuple[str, ...]) -> None:
    strategy = _arg_value(args, "--strategy")
    ledger = _arg_value(args, "--ledger")
    if not strategy or not ledger:
        raise click.ClickException("strategy-book ledger 必须传 --strategy STRATEGY --ledger LEDGER")
    cash_pool = _arg_value(args, "--cash-pool") or ledger
    make_default = "--default" in args
    payload = _strategy_book_payload(state)
    strategies = payload.setdefault("strategies", {})
    raw_entry = strategies.get(strategy)
    entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
    ledgers = list(entry.get("ledger_ids") or entry.get("ledgers") or [])
    if ledger not in ledgers:
        ledgers.append(ledger)
    entry["ledger_ids"] = ledgers
    if make_default or not entry.get("default_ledger_id"):
        entry["default_ledger_id"] = ledger
    strategies[strategy] = entry
    payload.setdefault("cash_pools", {})[ledger] = cash_pool
    state.backtest_strategy_book = payload


def _apply_strategy_book_cash_pool(state, args: tuple[str, ...]) -> None:
    cash_pool = _arg_value(args, "--cash-pool")
    if not cash_pool:
        raise click.ClickException("strategy-book cash-pool 必须传 --cash-pool ID")
    payload = _strategy_book_payload(state)
    configs = payload.setdefault("cash_pool_configs", {})
    config = dict(configs.get(cash_pool) or {})
    _set_optional_float_arg(config, args, "--initial-capital-major", "initial_capital_major")
    base_currency = _arg_value(args, "--base-currency")
    if base_currency:
        config["base_currency"] = base_currency
    _set_optional_float_arg(config, args, "--currency-conversion-fee-rate", "currency_conversion_fee_rate")
    configs[cash_pool] = config
    state.backtest_strategy_book = payload


def _print_strategy_book(state) -> None:
    payload = _strategy_book_payload(state)
    strategies = payload.get("strategies") or {}
    cash_pools = payload.get("cash_pools") or {}
    cash_pool_configs = payload.get("cash_pool_configs") or {}
    click.echo("StrategyBook")
    if not strategies:
        click.echo("  模式: StrategyBookSimple · 每个 strategy 一个私有 ledger / cash pool")
    else:
        rows = []
        for strategy, entry in strategies.items():
            entry_map = entry if isinstance(entry, dict) else {"ledger_ids": [entry], "default_ledger_id": entry}
            ledger_ids = list(entry_map.get("ledger_ids") or entry_map.get("ledgers") or [])
            default = str(entry_map.get("default_ledger_id") or (ledger_ids[0] if ledger_ids else ""))
            pools = ", ".join(f"{ledger}->{cash_pools.get(ledger, ledger)}" for ledger in ledger_ids)
            rows.append((strategy, ", ".join(ledger_ids), default, pools))
        for line in render_table(("strategy", "ledgers", "default", "cash pools"), rows, indent="  ", max_widths=(20, 28, 18, 42)):
            click.echo(line)
    if cash_pool_configs:
        click.echo("Cash pools")
        rows = [
            (
                pool_id,
                config.get("initial_capital_major", ""),
                config.get("base_currency", ""),
                config.get("currency_conversion_fee_rate", ""),
            )
            for pool_id, config in cash_pool_configs.items()
            if isinstance(config, dict)
        ]
        for line in render_table(("cash_pool", "initial", "currency", "fx_fee"), rows, indent="  ", max_widths=(24, 14, 10, 10)):
            click.echo(line)


def _print_strategy_book_help() -> None:
    click.echo("backtest strategy-book 命令")
    click.echo("  show                         查看当前 strategy/ledger/cash pool 拓扑")
    click.echo("  simple                       恢复默认: 每个 strategy 一个私有 ledger/cash pool")
    click.echo("  ledger --strategy A1 --ledger shared --cash-pool pool-main [--default]")
    click.echo("                               让 strategy A1 可操作 ledger shared，并映射到 cash pool")
    click.echo("  cash-pool --cash-pool pool-main --initial-capital-major 100000000 --base-currency CNY")
    click.echo("                               设置 cash pool 的初始资金与币种")


def _parse_ledger_config_args(args: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    string_fields = {
        "--fee-mode": "fee_mode",
        "--margin-mode": "margin_mode",
        "--margin-call-mode": "margin_call_mode",
        "--accounting-mode": "accounting_mode",
        "--cost-basis-method": "cost_basis_method",
        "--tradability-policy": "tradability_policy",
        "--clearing-rounding-policy": "clearing_rounding_policy",
    }
    float_fields = {
        "--fixed-fee-rate": "fixed_fee_rate",
        "--fixed-margin-ratio": "fixed_margin_ratio",
        "--liquidation-target-buffer": "liquidation_target_buffer",
        "--cash-reserve-ratio": "cash_reserve_ratio",
        "--cash-reserve-major": "cash_reserve_major",
    }
    bool_fields = {
        "--daily-mark-to-market-enabled": "daily_mark_to_market_enabled",
        "--use-int-position": "use_int_position",
    }
    for flag, key in string_fields.items():
        value = _arg_value(args, flag)
        if value:
            values[key] = value
    for flag, key in float_fields.items():
        value = _arg_value(args, flag)
        if value:
            values[key] = float(value)
    for flag, key in bool_fields.items():
        value = _arg_value(args, flag)
        if value:
            values[key] = _parse_bool(value, flag)
    extra = _parse_raw_settings(tuple(_strip_known_ledger_config_args(args)))
    values.update(extra)
    return values


def _strip_known_ledger_config_args(args: tuple[str, ...]) -> list[str]:
    known_with_value = {
        "--ledger",
        "--fee-mode",
        "--fixed-fee-rate",
        "--margin-mode",
        "--fixed-margin-ratio",
        "--margin-call-mode",
        "--liquidation-target-buffer",
        "--accounting-mode",
        "--daily-mark-to-market-enabled",
        "--cost-basis-method",
        "--use-int-position",
        "--tradability-policy",
        "--clearing-rounding-policy",
        "--cash-reserve-ratio",
        "--cash-reserve-major",
    }
    result: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in known_with_value:
            i += 2
            continue
        result.append(args[i])
        i += 1
    return result


def _print_ledger_configs(state) -> None:
    click.echo("Ledger configs")
    if not state.backtest_ledger_configs:
        click.echo("  （空；使用后端注册字段的默认/推断规则）")
        return
    rows = []
    for ledger, config in state.backtest_ledger_configs.items():
        summary = ", ".join(f"{key}={value}" for key, value in sorted(config.items()))
        rows.append((ledger, summary))
    for line in render_table(("ledger", "config"), rows, indent="  ", max_widths=(24, 90)):
        click.echo(line)


def _print_ledger_config_help() -> None:
    click.echo("backtest ledger-config 命令")
    click.echo("  show / list")
    click.echo("  --ledger LEDGER --fee-mode auto --margin-mode auto --accounting-mode Auto")
    click.echo("  --daily-mark-to-market-enabled true --cost-basis-method fifo")
    click.echo("  --cash-reserve-ratio 0.1 --cash-reserve-major 1000000")
    click.echo("说明:")
    click.echo("  这些字段属于 ledger-owned 配置，会传给后端 LedgerConfig；不是普通 per-strategy 字段。")
    click.echo("  其他字段可用 --field value 或 field=value 透传，但后端会按 LedgerConfig 校验/忽略未知 metadata。")


def _set_optional_float_arg(target: dict[str, Any], args: tuple[str, ...], flag: str, key: str) -> None:
    value = _arg_value(args, flag)
    if value:
        target[key] = float(value)


def _parse_bool(value: str, flag: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise click.ClickException(f"{flag} 需要布尔值: {value}")


def _group_ref(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "split_count": group.get("split_count"),
        "group_index": group.get("group_index"),
    }


def _print_group(group: dict[str, Any]) -> None:
    if group.get("name"):
        click.echo(f"名称: {group['name']}")
    split_count = group.get("split_count", group.get("splitCount"))
    group_index = group.get("group_index", group.get("groupIndex"))
    factor = group.get("factor", group.get("factorAlias"))
    if split_count is not None:
        click.echo(f"分组数: {split_count}")
    if group_index is not None:
        click.echo(f"分组序号: {group_index}")
    click.echo(f"产品路径: {selection_label(group.get('product_path_selection'))}")
    click.echo(f"因子: {factor}")


def _run_backtest(state, *, groups: list[dict[str, Any]], verbose: bool = False) -> None:
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login 以创建页面上下文")
    if not groups:
        raise click.ClickException("没有可运行的分组；请先用 factortester group --add 新增分组")
    payload = _run_payload(state, groups=groups)
    click.echo(f"开始运行回测: groups={len(groups)}, long-short={len(state.backtest_ls_configs)}")
    _print_run_strategy_info(groups, state.backtest_ls_configs)
    if state.backtest_strategy_book:
        _print_strategy_book(state)
    if state.backtest_ledger_configs:
        _print_ledger_configs(state)
    client = client_from_config()
    renderer = BacktestRunRenderer(verbose=verbose, live=_equity_curve_live_enabled(state, client=client))
    for event in client.run_group_test_stream(payload):
        event_name = str(event.get("event") or "message")
        data = event.get("data")
        if event_name == "error":
            message = data.get("error") if isinstance(data, dict) else data
            raise click.ClickException(f"分组测试失败: {message}")
        if event_name in {"activity_manifest", "runtime_info", "progress", "activity", "signal_progress", "result", "complete", "done"}:
            renderer.handle(event_name, data)
    renderer.handle("complete", {})
    if renderer.last_result:
        state.backtest_last_result = renderer.last_result
        save_state(state)
    _print_backtest_result_hints()


def _run_payload(state, *, groups: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": dict(state.backtest_local_settings),
        "groups": [dict(group) for group in groups],
        "ls_configs": list(state.backtest_ls_configs),
    }
    if state.backtest_strategy_book:
        payload["strategy_book"] = _strategy_book_payload(state)
    if state.backtest_ledger_configs:
        payload["ledger_configs"] = {
            str(ledger): dict(config)
            for ledger, config in state.backtest_ledger_configs.items()
        }
    return payload


def _print_results_help() -> None:
    click.echo("backtest results 命令")
    click.echo("  summary                         最近一次运行的统计表格")
    click.echo("  equity                          最近一次运行的多策略净值图")
    click.echo("  snapshot --index N              查看第 N 个时间点的持仓/资金快照")
    click.echo("  snapshot --timestamp-ms MS      查看指定 epoch 毫秒附近的快照")
    click.echo("  order-flow [--group-name NAME]  查看订单流明细(时间/品种/数量/成交价/状态)")
    click.echo("    --order-id ID                 只看某笔订单的完整生命周期")
    click.echo("    --limit N                     每个策略最多显示的记录数(默认20, 0=全部)")
    click.echo("    --counts-only                 只显示记录条数，不展开明细")


def _require_last_result(state) -> dict[str, Any]:
    if not state.backtest_last_result:
        raise click.ClickException("没有最近一次 backtest 结果；请先运行 factortester backtest --run")
    return state.backtest_last_result


def _print_stored_result_summary(state) -> None:
    data = _require_last_result(state)
    series = _result_series(data.get("groups") or [])
    rows = [
        (f"{name} · LS" if is_ls else name, f"{curve[-1]:.2f}", len(curve))
        for name, curve, is_ls in series
        if curve
    ]
    click.echo("最近一次回测摘要")
    for line in render_table(("策略", "最终权益", "点数"), rows, indent="  ", aligns=("left", "right", "right"), max_widths=(28, 16, 8)):
        click.echo(line)


def _print_stored_equity_chart(state) -> None:
    data = _require_last_result(state)
    series = _result_series(data.get("groups") or [])
    if not series:
        raise click.ClickException("最近一次结果没有可画的净值曲线")
    for line in ["净值曲线:", *_multi_series_chart(series, width=_chart_body_width())]:
        click.echo(line)


def _print_snapshot_result(state, args: tuple[str, ...]) -> None:
    data = _require_last_result(state)
    product_path_selection_id = str(data.get("product_path_selection_id") or "")
    if not product_path_selection_id:
        raise click.ClickException("最近一次结果没有 product_path_selection_id，无法请求快照")
    timestamp_ms = _result_timestamp_ms(data, args)
    result = client_from_config().group_snapshot({
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
        "timestamp_ms": timestamp_ms,
    })
    summary = result.get("summary") or {}
    click.echo(f"快照: timestamp_ms={result.get('timestamp_ms')}")
    click.echo(f"事件: {result.get('event_label') or result.get('event_type') or '（未知）'}")
    click.echo(f"摘要: changed={summary.get('total_changed')} products={summary.get('total_prod_count')} turnover={summary.get('avg_turnover')}")
    matrices = result.get("matrices") if isinstance(result.get("matrices"), list) else []
    for matrix in matrices[:1]:
        columns_raw = matrix.get("columns") if isinstance(matrix, dict) else []
        rows_raw = matrix.get("rows") if isinstance(matrix, dict) else []
        columns = columns_raw if isinstance(columns_raw, list) else []
        rows = rows_raw if isinstance(rows_raw, list) else []
        click.echo(f"矩阵: {matrix.get('label') if isinstance(matrix, dict) else ''} · 列={len(columns)} · 行={len(rows)}")


def _print_order_flow_result(state, args: tuple[str, ...]) -> None:
    """默认显示每个策略最近的订单流明细（时间、品种、步骤、数量、成交价、
    状态），而不只是记录条数 -- 记录条数看不出策略实际交易了什么、有没有
    在期望的品种上下单。

    \b
    可选参数:
      --group-name NAME    只看指定策略
      --timestamp-ms MS    只看某个时间点的记录
      --order-id ID        只看某笔订单的完整生命周期
      --limit N            每个策略最多显示的记录数(默认 20, 0=全部)
      --counts-only        只显示每个策略的记录条数(旧行为)
    """
    data = _require_last_result(state)
    payload: dict[str, Any] = {"page_uuid": state.page_uuid}
    group_name = _arg_value(args, "--group-name")
    if group_name:
        group_id = _group_id_for_name(data, group_name)
        if group_id:
            payload["group_id"] = group_id
        else:
            raise click.ClickException(f"最近一次结果中找不到策略: {group_name}")
    timestamp_ms = _arg_value(args, "--timestamp-ms")
    if timestamp_ms:
        payload["timestamp_ms"] = int(timestamp_ms)
    order_id = _arg_value(args, "--order-id")
    if order_id:
        payload["order_id"] = order_id
    result = client_from_config().group_order_flow(payload)
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    click.echo(f"订单流: records={result.get('record_count', 0)}")

    counts_only = "--counts-only" in args
    limit_raw = _arg_value(args, "--limit")
    limit = int(limit_raw) if limit_raw else 20

    rows = []
    for group in groups:
        records = group.get("records") if isinstance(group, dict) else []
        rows.append((group.get("group_name") or group.get("group_id") or "", len(records or [])))
    for line in render_table(("策略", "记录数"), rows, indent="  ", aligns=("left", "right"), max_widths=(28, 8)):
        click.echo(line)

    if counts_only:
        return

    for group in groups:
        records = list(group.get("records") or []) if isinstance(group, dict) else []
        if not records:
            continue
        name = group.get("group_name") or group.get("group_id") or ""
        shown = records if limit <= 0 else records[:limit]
        click.echo(f"\n{name} 订单流明细 (显示 {len(shown)}/{len(records)} 条):")
        detail_rows = [
            (
                str(r.get("timestamp") or ""),
                str(r.get("product") or ""),
                str(r.get("step") or ""),
                str(r.get("label") or ""),
                f"{r.get('quantity') or 0.0:.4g}",
                "" if r.get("effective_price") is None else f"{r.get('effective_price'):.6g}",
                str(r.get("status") or ""),
                str(r.get("reject_reason") or ""),
            )
            for r in shown
        ]
        for line in render_table(
            ("时间", "品种", "步骤", "说明", "数量", "成交价", "状态", "拒绝原因"),
            detail_rows, indent="  ", aligns=("left", "left", "left", "left", "right", "right", "left", "left"),
            max_widths=(24, 14, 14, 16, 10, 10, 10, 20),
        ):
            click.echo(line)
        if limit > 0 and len(records) > limit:
            click.echo(f"  ... 还有 {len(records) - limit} 条，用 --limit 0 查看全部")


def _result_timestamp_ms(data: dict[str, Any], args: tuple[str, ...]) -> int:
    explicit = _arg_value(args, "--timestamp-ms")
    if explicit:
        return int(explicit)
    index_raw = _arg_value(args, "--index")
    index = int(index_raw or "1") - 1
    groups_raw = data.get("groups")
    groups = groups_raw if isinstance(groups_raw, list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        timestamps = group.get("timestamps")
        if isinstance(timestamps, list) and timestamps:
            index = max(0, min(index, len(timestamps) - 1))
            return _timestamp_value_to_ms(timestamps[index])
    raise click.ClickException("最近一次结果没有时间索引，无法请求快照")


def _timestamp_value_to_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        raise click.ClickException("时间索引为空，无法请求快照")
    try:
        return int(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise click.ClickException(f"无法解析时间索引: {text}") from exc
    return int(parsed.timestamp() * 1000)


def _group_id_for_name(data: dict[str, Any], name: str) -> str:
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        keys = {str(group.get("name") or ""), str(group.get("id") or ""), str(group.get("group_id") or "")}
        if name in keys:
            return str(group.get("id") or group.get("group_id") or "")
    return ""


def _arg_value(args: tuple[str, ...], flag: str) -> str:
    for index, token in enumerate(args):
        if token == flag and index + 1 < len(args):
            return str(args[index + 1])
    return ""


def _print_backtest_result_hints() -> None:
    click.echo("结果查看:")
    click.echo("  factortester backtest results summary")
    click.echo("  factortester backtest results equity")
    click.echo("  factortester backtest results snapshot --index 1")
    click.echo("  factortester backtest results order-flow --group-name <策略名>")


def _print_run_strategy_info(groups: list[dict[str, Any]], ls_configs: list[dict[str, Any]]) -> None:
    click.echo("策略信息:")
    for index, group in enumerate(groups, start=1):
        name = group.get("name") or group.get("id") or f"group-{index}"
        split_count = group.get("split_count", group.get("splitCount"))
        group_index = group.get("group_index", group.get("groupIndex"))
        factor = group.get("factor", group.get("factorAlias")) or "（未设置）"
        product_path = selection_label(group.get("product_path_selection")) or "（未设置）"
        pieces = [str(name)]
        if split_count is not None:
            pieces.append(f"分组数={split_count}")
        if group_index is not None:
            pieces.append(f"分组序号={group_index}")
        pieces.append(f"产品路径={product_path}")
        pieces.append(f"因子={factor}")
        if group.get("parent_id") or group.get("parentId"):
            pieces.append(f"派生自={group.get('parent_id') or group.get('parentId')}")
        click.echo("  " + " · ".join(pieces))
    for index, config in enumerate(ls_configs, start=1):
        long_group = config.get("long_group") or {}
        short_group = config.get("short_group") or {}
        long_label = long_group.get("name") or long_group.get("id") or config.get("long_group_id") or config.get("longGroupId") or "?"
        short_label = short_group.get("name") or short_group.get("id") or config.get("short_group_id") or config.get("shortGroupId") or "?"
        name = config.get("name") or f"ls-{index}"
        click.echo(f"  {name} · Long-Short · 多头={long_label} · 空头={short_label}")


def _equity_curve_live_enabled(state, *, client=None) -> bool:
    _, store = _stores_for_backtest(state, client=client)
    curve_mode = store.effective("equity_curve_mode")
    if curve_mode is not None:
        return str(curve_mode).strip().lower() == "live"
    return _truthy(store.effective("equity_compute_live"))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on", "live"}


def _print_run_event(event_name: str, data: Any) -> None:
    if isinstance(data, dict):
        if event_name == "runtime_info":
            row_type = data.get("type") or data.get("status") or "运行信息"
            detail = data.get("detail") or data.get("message") or data
            click.echo(f"[运行信息] {row_type}: {detail}")
            return
        if event_name in {"complete", "done"}:
            click.echo("回测完成")
            return
        label = data.get("label") or data.get("message") or data.get("phase") or data.get("status")
        if label:
            click.echo(f"[{event_name}] {label}")
            return
    elif data:
        click.echo(f"[{event_name}] {data}")


def _stores_for_backtest(state, client=None) -> tuple[FieldStore, FieldStore]:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    backtest_store = FieldStore.from_manifest(client.manifest(BACKTEST_BACKEND_KEY), values=state.backtest_local_settings, parent=page_store)
    return page_store, backtest_store


def _ensure_page_candidates(state, client) -> None:
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    fields = resolve_backtest_public_fields(page_store)
    if not page_store.effective(fields.product_path_candidates):
        groups = client.list_candidates(fields.product_path_candidates)
        page_store.set(fields.product_path_candidates, groups)
        if groups and not page_store.effective(fields.product_path_selection):
            page_store.set(fields.product_path_selection, product_group_selection(groups[0]))
    state.page_settings = page_store.to_payload()


def _load_default_factor_for_product_group(state, client, page_store: FieldStore, *, factor_family: str, product_group_label: str) -> None:
    if not factor_family:
        return
    overview = client.factor_library_overview(factor_family=factor_family, product_group=product_group_label)
    factors = list(overview.get("factors") or [])
    fields = resolve_backtest_public_fields(page_store)
    page_store.set(fields.factor_candidates, factors)
    if factors:
        page_store.set(fields.factor, str(factors[0].get("factor_alias") or factors[0].get("alias") or ""))
