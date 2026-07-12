"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

import contextlib
import io
import json
import ast
import shutil
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
from tools.testers.backtest.engines.native.flow import phase_label
# Module-level mapping from group ID to short alias, populated at run time
_short_alias_map: dict[str, str] = {}

# Field metadata comes from the executable-module registry, not a hand-picked
# controller list. Adding a registered backtest module automatically makes its
# labels and chip ordering available to this renderer.
_field_labels: dict[str, str] = {}
_field_tab_order: dict[str, int] = {}
_field_display_order: dict[str, int] = {}
_field_display_offsets: dict[str, int] = {}
try:
    from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

    for _mod in _ALL_MODULE_CLASSES:
        if hasattr(_mod, 'fields'):
            for _fn, _fd in _mod.fields.items():
                _qualified = f"{_mod.__name__}.{_fn}"
                _label = getattr(_fd, 'label', '') or ''
                if _label:
                    _field_labels[_fn] = _label
                    _field_labels[_qualified] = _label
                    _to = getattr(_fd, 'tab_order', None)
                    if _to is not None:
                        _field_tab_order[_fn] = _to
                        _field_tab_order[_qualified] = _to
                    _serialization = getattr(_fd, "serialization", None) or {}
                    if isinstance(_serialization, dict) and _serialization.get("display_order") is not None:
                        _display_order = int(_serialization["display_order"])
                        _field_display_order[_fn] = _display_order
                        _field_display_order[_qualified] = _display_order
                    _offset = getattr(_fd, "display_offset", 0)
                    if _offset:
                        _field_display_offsets[_fn] = int(_offset)
                        _field_display_offsets[_qualified] = int(_offset)
except Exception:
    pass


def _flabel(name: str) -> str:
    """Return field name with Chinese label: 'margin_mode (保证金模式)'"""
    cn = _field_labels.get(name) or _field_labels.get(name.rsplit(".", 1)[-1])
    return f"{name} ({cn})" if cn else name


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
@click.option("--step", is_flag=True, help="单步调试模式：每步暂停，按 Enter 继续，显示每个 Flow 的处理和字段变更。")
@click.option("--verbose", is_flag=True, help="运行时打印完整 SSE 进度事件摘要。")
@click.pass_context
@friendly_errors
def backtest(
    ctx: click.Context,
    run: bool,
    step: bool,
    verbose: bool,
) -> None:
    """进入通用回测控制界面。

    \b
    回测与 single_factor_test 平行注册；因子家族在具体需要因子的动作中指定:
      factortester backtest group --add --factor-family SgCCS --factor 'SgCCS|N:2m|$F:1m|$Rev'

    \b
    常用草稿命令:
      factortester backtest local-settings --allocation-mode equal_notional
      factortester backtest local-settings --liquidity-mode infinite
      factortester backtest local-settings --liquidity-mode volume_participation --participation-rate 0.02
      factortester backtest group --add --group-name A1 --split-count 5 --group-index 1 --factor-family SgCCS
      factortester backtest group --add --factor-family SgCCS --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'
      factortester backtest group --add --factor-family SgCCS --factor add --param N=2m --param '$Rev=1'
      factortester backtest group --add --product-group from-candidates --name 中国期货日盘
      factortester backtest group --group-name A1 --derive --group-name A1a --product-path ...
      factortester backtest group --group-name A1 --copy --group-name A1-copy
      factortester backtest long-short --add --ls-name LS-A1-A5 --long-group A1 --short-group A5
      factortester backtest strategy-book ledger --strategy A1 --ledger shared --cash-pool pool-main
      factortester backtest ledger-config --ledger shared --fee-mode auto --margin-mode auto
      factortester backtest ledger-config --ledger private:A1 --margin-mode none
      factortester backtest compare volume-capacity-margin --volume-rate 0.02
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
        _run_backtest(state, groups=state.backtest_groups, verbose=verbose, step_mode=step)
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
    # Parse --factor-family from args before other commands
    factor_family_from_args = ""
    cleaned_args: list[str] = []
    _skip_next = False
    for i, arg in enumerate(args):
        if _skip_next:
            _skip_next = False
            continue
        if arg == "--factor-family":
            if i + 1 < len(args):
                factor_family_from_args = str(args[i + 1])
                _skip_next = True
            continue
        cleaned_args.append(arg)
    args = tuple(cleaned_args)
    if factor_family_from_args:
        state.factor_family = factor_family_from_args

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
        raise click.ClickException("template 命令需要先选择因子家族，例如加上 --factor-family SgCCS")
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
    _ensure_active_backtest_scope(state)
    args = tuple(ctx.args)
    if not args or args[0] in {"show", "list", "ls"}:
        _print_backtest_local_settings(state)
        return
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
    _print_backtest_local_settings(state, validate=False)


@backtest.command("compare", context_settings=SELECTOR_HELP_CONTEXT)
@click.option("--volume-rate", type=float, default=0.02, show_default=True, help="成交量容量限制场景的参与率。")
@click.option("--factor-family", default="", help="因子家族名；factor-grid 未传时使用当前上下文。")
@click.option("--n", "n_values", multiple=True, help="N 参数候选，可重复。默认: 1m,2m,3m,5m,10m")
@click.option("--f", "f_values", multiple=True, help="$F 参数候选，可重复。默认: 1m")
@click.option("--product-group", "product_groups", multiple=True, help="产品组候选名称，可重复。默认继承当前草稿。")
@click.option("--rev/--no-rev", default=True, show_default=True, help="是否使用 $Rev 标志。")
@click.option("--top", type=int, default=12, show_default=True, help="factor-grid 摘要显示前 N 个结果。")
@click.option(
    "--volume-capacity-mode",
    "--liquidity-mode",
    "liquidity_mode",
    type=click.Choice(["inherit", "infinite", "volume_participation"]),
    default="inherit",
    show_default=True,
    help="factor-grid 覆盖成交量容量模式；--liquidity-mode 是旧别名。",
)
@click.option("--participation-rate", type=float, default=None, help="factor-grid 成交量参与率；默认沿用 --volume-rate。")
@click.option("--verbose", is_flag=True, help="运行时打印完整 SSE 进度事件摘要。")
@click.pass_context
@friendly_errors
def compare(
    ctx: click.Context,
    volume_rate: float,
    factor_family: str,
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    product_groups: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
    participation_rate: float | None,
    verbose: bool,
) -> None:
    """在一次 backend run 中克隆当前草稿，批量对比关键执行/保证金场景。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    args = tuple(ctx.args)
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_backtest_compare_help()
        return
    preset = args[0]
    if preset == "volume-capacity-margin":
        if volume_rate <= 0:
            raise click.ClickException("--volume-rate 必须大于 0")
        payload, groups, ls_configs, scenarios = _volume_capacity_margin_compare_payload(
            state,
            volume_rate=volume_rate,
        )
        click.echo("批量对比场景:")
        for scenario in scenarios:
            click.echo(f"  {scenario['label']}: {scenario['description']}")
        _run_backtest(
            state,
            groups=groups,
            ls_configs=ls_configs,
            payload=payload,
            verbose=verbose,
            title="批量对比回测",
            show_topology=False,
        )
        _print_compare_result_summary(state, scenarios)
        return
    if preset == "factor-grid":
        payload, groups, ls_configs, scenarios = _factor_grid_payload(
            state,
            factor_family=factor_family,
            n_values=n_values,
            f_values=f_values,
            product_groups=product_groups,
            rev=rev,
            liquidity_mode=liquidity_mode,
            participation_rate=participation_rate if participation_rate is not None else volume_rate,
        )
        click.echo("因子参数/产品组批量研究:")
        for scenario in scenarios:
            click.echo(f"  {scenario['label']}: {scenario['description']}")
        _run_backtest(
            state,
            groups=groups,
            ls_configs=ls_configs,
            payload=payload,
            verbose=verbose,
            title="因子参数网格回测",
            show_topology=False,
        )
        _print_factor_grid_result_summary(state, scenarios, top=top)
        return
    raise click.ClickException("compare 支持 preset: volume-capacity-margin, factor-grid")


@backtest.command("strategy-book", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def strategy_book(ctx: click.Context) -> None:
    """配置 strategy -> ledger -> cash pool 拓扑。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
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
    _ensure_active_backtest_scope(state)
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
      factortester backtest results attribution --group-name A1:1 --by product
      factortester backtest results detail --group-name A1
      factortester backtest results ranking
      factortester backtest results snapshot --index 1
      factortester backtest results order-flow --group-name A1

    所有 results 子命令都支持:
      --output PATH     同时写入文件
      --no-terminal    只写文件，不打印到终端
      --append         追加写入文件
    """
    state = load_state()
    output_options, args = _parse_result_output_options(tuple(ctx.args))
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_results_help()
        return
    action = args[0]

    def dispatch() -> None:
        if action == "summary":
            _print_stored_result_summary(state)
            return
        if action == "equity":
            _print_stored_equity_chart(state)
            return
        if action in {"attribution", "attr"}:
            _print_attribution_result(state, args[1:])
            return
        if action in {"ledgers", "ledger", "cash-pools", "cash-pool"}:
            _print_ledger_replay_result(state, args[1:])
            return
        if action == "detail":
            _print_group_detail_result(state, args[1:])
            return
        if action in {"ranking", "rank"}:
            _print_group_ranking_result(state, args[1:])
            return
        if action == "snapshot":
            _print_snapshot_result(state, args[1:])
            return
        if action in {"order-flow", "orders"}:
            _print_order_flow_result(state, args[1:])
            return
        raise click.ClickException("results 支持: summary, equity, attribution, ledgers, detail, ranking, snapshot, order-flow")

    _emit_result_output(output_options, dispatch)


def _print_backtest_template_help(state) -> None:
    click.echo("backtest template 命令")
    current = state.factor_family or "（未选择）"
    click.echo(f"当前因子家族: {current}")
    click.echo("  list --factor-family <因子家族>    列出指定因子家族的设置模板")
    click.echo("  load <模板ID或名称>               加载模板到 backtest 草稿")
    click.echo("  --from-module-template single_factor_test load <模板>  从 single_factor_test 模块显式导入模板")
    click.echo("  save [模板名]                     保存当前 CLI 草稿为设置模板")
    click.echo("")
    click.echo("示例:")
    click.echo("  factortester backtest template --factor-family SgCCS list")
    click.echo("  factortester backtest template --from-module-template single_factor_test --factor-family SgCCS load 1")
    click.echo("  factortester backtest template --factor-family SgCCS save 'CLI 草稿'")


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
        f"· groups: {applied['groups']} · long-short: {applied['ls_configs']} "
        f"· strategy-book: {applied['strategy_book']} · ledger-configs: {applied['ledger_configs']}{factor_text}"
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


def _ensure_active_backtest_scope(state) -> None:
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state, scope=BACKTEST_SPACE)


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
    strategy_book = snapshot.get("strategy_book")
    state.backtest_strategy_book = dict(strategy_book) if isinstance(strategy_book, dict) else {}
    ledger_configs = snapshot.get("ledger_configs")
    ledger_config_items = ledger_configs.items() if isinstance(ledger_configs, dict) else ()
    state.backtest_ledger_configs = {
        str(key): dict(value)
        for key, value in ledger_config_items
        if isinstance(value, dict)
    }
    return {
        "page_settings": len(factors) + 1,
        "local_settings": len(state.backtest_local_settings),
        "groups": len(state.backtest_groups),
        "ls_configs": len(state.backtest_ls_configs),
        "strategy_book": len(state.backtest_strategy_book.get("strategies") or {}) if state.backtest_strategy_book else 0,
        "ledger_configs": len(state.backtest_ledger_configs),
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
        "strategy_book": dict(state.backtest_strategy_book),
        "ledger_configs": {
            str(key): dict(value)
            for key, value in state.backtest_ledger_configs.items()
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
        # A generic backtest draft may contain several factor families and
        # does not require the page-level ``state.factor_family`` selector.
        factor_family = alias.split("|", 1)[0]
        params = _params_from_factor_alias(alias, factor_family)
        data = client.add_candidate("factor", {
            "factor_family_alias": factor_family,
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


def _print_backtest_local_settings(state, *, validate: bool = True) -> None:
    if validate:
        _validate_registered_local_settings(state)
    _, store = _stores_for_backtest(state)
    click.echo("Backtest local-settings")
    if state.backtest_local_settings:
        for key in sorted(state.backtest_local_settings):
            click.echo(f"  {key}: {state.backtest_local_settings[key]}")
        rows = []
        for key in sorted(state.backtest_local_settings):
            meta = store.field(key)
            rows.append((
                field_flag(key),
                str(meta.get("label") or key),
                repr(state.backtest_local_settings.get(key)),
                repr(store.effective(key)),
            ))
        for line in render_table(("字段", "名称", "显式值", "有效值"), rows, indent="  ", max_widths=(30, 18, 28, 34)):
            click.echo(line)
    else:
        click.echo("  （无显式 local-settings；使用页面/后端注册默认值）")
    focus = ("engine_mode", "liquidity_mode", "participation_rate", "margin_mode", "allocation_policy")
    rows = []
    for key in focus:
        meta = store.field(key)
        if meta:
            rows.append((field_flag(key), str(meta.get("label") or key), repr(meta.get("value")), repr(store.effective(key))))
    if rows:
        click.echo("")
        click.echo("关键有效字段")
        for line in render_table(("字段", "名称", "默认值", "有效值"), rows, indent="  ", max_widths=(30, 18, 24, 34)):
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
    _print_strategy_book_payload(payload)


def _print_strategy_book_payload(payload: dict[str, Any]) -> None:
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
        "--transaction-fee-source": "transaction_fee_source",
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
        "--transaction-fee-source",
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
    _print_ledger_config_payload(state.backtest_ledger_configs)


def _print_ledger_config_payload(configs: dict[str, Any]) -> None:
    if not configs:
        click.echo("  （空；使用后端注册字段的默认/推断规则）")
        return
    rows = []
    for ledger, config in configs.items():
        config_map = config if isinstance(config, dict) else {}
        summary = ", ".join(f"{key}={value}" for key, value in sorted(config_map.items()))
        rows.append((ledger, summary))
    for line in render_table(("ledger", "config"), rows, indent="  ", max_widths=(24, 90)):
        click.echo(line)


def _print_ledger_config_help() -> None:
    click.echo("backtest ledger-config 命令")
    click.echo("  show / list")
    click.echo("  --ledger LEDGER --fee-mode auto --transaction-fee-source exchange --margin-mode auto --accounting-mode Auto")
    click.echo("  --transaction-fee-source 可选: exchange, openctp")
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


def _print_backtest_compare_help() -> None:
    click.echo("backtest compare 命令")
    click.echo("  volume-capacity-margin [--volume-rate 0.02]")
    click.echo("    在一次后端 run 中复制当前草稿为三套场景:")
    click.echo("      1. 成交量容量=无限 / 保证金=关闭")
    click.echo("      2. 成交量容量=成交量参与率 / 保证金=关闭")
    click.echo("      3. 成交量容量=无限 / 保证金=auto")
    click.echo("  factor-grid --factor-family NAME [--n 1m --n 2m] [--f 1m] [--product-group 中国期货日盘]")
    click.echo("    继承当前草稿和已注册 policy/local-settings，批量替换因子参数和可选产品组。")
    click.echo("    可加 --volume-capacity-mode infinite|volume_participation 覆盖模板内成交量容量设置。")
    click.echo("")
    click.echo("示例:")
    click.echo("  factortester backtest compare volume-capacity-margin --volume-rate 0.02")
    click.echo("  factortester backtest compare factor-grid --factor-family SgCCS --product-group 中国期货夜盘 --product-group 中国期货日盘 --n 2m --f 1m --volume-capacity-mode infinite")


def _volume_capacity_margin_compare_payload(
    state,
    *,
    volume_rate: float,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if not state.backtest_groups:
        raise click.ClickException("没有可对比的分组；请先加载模板或新增分组")
    scenarios: list[dict[str, str]] = [
        {
            "key": "cap_inf_margin_none",
            "label": "无限容量/无保证金",
            "description": "liquidity_mode=infinite, margin_mode=none",
        },
        {
            "key": "cap_limited_margin_none",
            "label": f"容量{volume_rate:g}/无保证金",
            "description": f"liquidity_mode=volume_participation, participation_rate={volume_rate:g}, margin_mode=none",
        },
        {
            "key": "cap_inf_margin_auto",
            "label": "无限容量/保证金auto",
            "description": "liquidity_mode=infinite, margin_mode=auto",
        },
    ]
    groups: list[dict[str, Any]] = []
    ls_configs: list[dict[str, Any]] = []
    ledger_configs: dict[str, dict[str, Any]] = {}
    strategy_book: dict[str, Any] = {"strategies": {}, "cash_pools": {}}
    for scenario in scenarios:
        id_map = {
            _draft_group_id(group): _scenario_strategy_id(scenario["key"], _draft_group_id(group))
            for group in state.backtest_groups
        }
        for group in state.backtest_groups:
            old_id = _draft_group_id(group)
            new_id = id_map[old_id]
            cloned = dict(group)
            cloned["id"] = new_id
            cloned["group_id"] = new_id
            cloned["strategy_id"] = new_id
            old_short = str(group.get("shortAlias") or group.get("short_alias") or group.get("name") or old_id)
            cloned["shortAlias"] = f"{scenario['label']} · {old_short}"
            cloned["name"] = f"{scenario['label']} · {group.get('name') or old_short}"
            for parent_key in ("parentId", "parent_id"):
                parent = str(cloned.get(parent_key) or "")
                if parent in id_map:
                    cloned[parent_key] = id_map[parent]
            _apply_compare_scenario_settings(cloned, scenario["key"], volume_rate=volume_rate)
            groups.append(cloned)
            _register_compare_ledger(strategy_book, ledger_configs, new_id, scenario["key"])
        for index, config in enumerate(state.backtest_ls_configs):
            old_id = str(config.get("strategy_id") or config.get("id") or f"ls-{index}")
            new_id = _scenario_strategy_id(scenario["key"], old_id)
            cloned_ls = dict(config)
            cloned_ls["id"] = new_id
            cloned_ls["strategy_id"] = new_id
            old_short = str(config.get("shortAlias") or config.get("name") or old_id)
            cloned_ls["shortAlias"] = f"{scenario['label']} · {old_short}"
            cloned_ls["name"] = f"{scenario['label']} · {config.get('name') or old_short}"
            _remap_long_short_leg_ids(cloned_ls, id_map)
            _apply_compare_scenario_settings(cloned_ls, scenario["key"], volume_rate=volume_rate)
            ls_configs.append(cloned_ls)
            _register_compare_ledger(strategy_book, ledger_configs, new_id, scenario["key"])
    local_settings = dict(state.backtest_local_settings)
    for key in ("liquidity_mode", "participation_rate", "margin_mode"):
        local_settings.pop(key, None)
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": local_settings,
        "groups": groups,
        "ls_configs": ls_configs,
        "strategy_book": strategy_book,
        "ledger_configs": ledger_configs,
    }
    return payload, groups, ls_configs, scenarios


def _factor_grid_payload(
    state,
    *,
    factor_family: str,
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    product_groups: tuple[str, ...],
    rev: bool,
    liquidity_mode: str = "inherit",
    participation_rate: float = 0.02,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    if not state.backtest_groups:
        raise click.ClickException("没有可研究的分组；请先加载模板或新增分组")
    factor_family = str(factor_family or state.factor_family or state.page_settings.get("factor_family") or "").strip()
    if not factor_family:
        raise click.ClickException("factor-grid 缺少因子家族；请传 --factor-family")
    n_list = [str(item).strip() for item in (n_values or ("1m", "2m", "3m", "5m", "10m")) if str(item).strip()]
    f_list = [str(item).strip() for item in (f_values or ("1m",)) if str(item).strip()]
    if not n_list or not f_list:
        raise click.ClickException("--n 和 --f 至少各有一个候选")
    client = client_from_config()
    product_group_selections = _factor_grid_product_group_selections(client, product_groups)
    scenarios: list[dict[str, str]] = []
    groups: list[dict[str, Any]] = []
    ls_configs: list[dict[str, Any]] = []
    ledger_configs: dict[str, dict[str, Any]] = {}
    strategy_book: dict[str, Any] = {"strategies": {}, "cash_pools": {}}
    for n_value in n_list:
        for f_value in f_list:
            alias = _factor_grid_alias(factor_family, n_value, f_value, rev=rev)
            _register_factor_alias(state, client, alias, factor_family=factor_family)
            product_items = product_group_selections or [None]
            for product_group_selection_item in product_items:
                product_label = (
                    selection_label(product_group_selection_item)
                    if product_group_selection_item is not None
                    else "继承产品组"
                )
                scenario_key = _factor_grid_key(alias, product_label)
                scenario_label = f"{alias} · {product_label}"
                scenarios.append({
                    "key": scenario_key,
                    "label": scenario_label,
                    "description": f"factor={alias}, product_group={product_label}",
                })
                scenario_source_groups = _factor_grid_source_groups(
                    state.backtest_groups,
                    overrides_product_group=product_group_selection_item is not None,
                )
                id_map = {
                    _draft_group_id(group): _scenario_strategy_id(scenario_key, _draft_group_id(group))
                    for group in scenario_source_groups
                }
                for group in scenario_source_groups:
                    old_id = _draft_group_id(group)
                    new_id = id_map[old_id]
                    cloned = dict(group)
                    cloned["id"] = new_id
                    cloned["group_id"] = new_id
                    cloned["strategy_id"] = new_id
                    old_short = str(group.get("shortAlias") or group.get("short_alias") or group.get("name") or old_id)
                    cloned["shortAlias"] = f"{scenario_label} · {old_short}"
                    cloned["name"] = f"{scenario_label} · {group.get('name') or old_short}"
                    cloned["factor"] = alias
                    cloned["factorAlias"] = alias
                    cloned["factor_family_alias"] = factor_family
                    _apply_factor_grid_capacity_override(cloned, liquidity_mode=liquidity_mode, participation_rate=participation_rate)
                    if product_group_selection_item is not None:
                        cloned["product_path_selection"] = dict(product_group_selection_item)
                    for parent_key in ("parentId", "parent_id"):
                        parent = str(cloned.get(parent_key) or "")
                        if parent in id_map:
                            cloned[parent_key] = id_map[parent]
                    cloned["compare_scenario"] = scenario_key
                    groups.append(cloned)
                    _register_factor_grid_ledger(strategy_book, ledger_configs, new_id, cloned)
                for index, config in enumerate(state.backtest_ls_configs):
                    old_id = str(config.get("strategy_id") or config.get("id") or f"ls-{index}")
                    new_id = _scenario_strategy_id(scenario_key, old_id)
                    cloned_ls = dict(config)
                    cloned_ls["id"] = new_id
                    cloned_ls["strategy_id"] = new_id
                    old_short = str(config.get("shortAlias") or config.get("name") or old_id)
                    cloned_ls["shortAlias"] = f"{scenario_label} · {old_short}"
                    cloned_ls["name"] = f"{scenario_label} · {config.get('name') or old_short}"
                    _apply_factor_grid_capacity_override(cloned_ls, liquidity_mode=liquidity_mode, participation_rate=participation_rate)
                    _remap_long_short_leg_ids(cloned_ls, id_map)
                    cloned_ls["compare_scenario"] = scenario_key
                    ls_configs.append(cloned_ls)
                    _register_factor_grid_ledger(strategy_book, ledger_configs, new_id, cloned_ls)
    payload = {
        "page_uuid": state.page_uuid,
        "local_settings": dict(state.backtest_local_settings),
        "groups": groups,
        "ls_configs": ls_configs,
        "strategy_book": strategy_book,
        "ledger_configs": ledger_configs,
    }
    return payload, groups, ls_configs, scenarios


def _factor_grid_alias(factor_family: str, n_value: str, f_value: str, *, rev: bool) -> str:
    alias = f"{factor_family}|N:{n_value}|$F:{f_value}"
    if rev:
        alias += "|$Rev"
    return alias


def _factor_grid_key(alias: str, product_label: str) -> str:
    raw = f"{alias}__{product_label}"
    return "fg_" + "".join(ch if ch.isalnum() else "_" for ch in raw)[:96]


def _factor_grid_source_groups(groups: list[dict[str, Any]], *, overrides_product_group: bool) -> list[dict[str, Any]]:
    if not overrides_product_group:
        return list(groups)
    return [group for group in groups if not _group_has_product_mask(group)]


def _group_has_product_mask(group: dict[str, Any]) -> bool:
    for key in ("productMask", "product_mask", "product_mask_names"):
        value = group.get(key)
        if isinstance(value, dict) and any(bool(item) for item in value.values()):
            return True
        if isinstance(value, (list, tuple, set)) and bool(value):
            return True
    return False


def _apply_factor_grid_capacity_override(target: dict[str, Any], *, liquidity_mode: str, participation_rate: float) -> None:
    if liquidity_mode == "inherit":
        return
    target["liquidity_mode"] = liquidity_mode
    if liquidity_mode == "volume_participation":
        target["participation_rate"] = participation_rate


def _register_factor_grid_ledger(
    strategy_book: dict[str, Any],
    ledger_configs: dict[str, dict[str, Any]],
    strategy_id: str,
    settings: dict[str, Any],
) -> None:
    ledger_id = f"private:{strategy_id}"
    strategy_book.setdefault("strategies", {})[strategy_id] = {
        "ledger_ids": [ledger_id],
        "default_ledger_id": ledger_id,
    }
    strategy_book.setdefault("cash_pools", {})[ledger_id] = ledger_id
    ledger_config_keys = {
        "fee_mode",
        "fixed_fee_rate",
        "margin_mode",
        "fixed_margin_ratio",
        "accounting_mode",
        "daily_mark_to_market_enabled",
        "cost_basis_method",
        "use_int_position",
        "tradability_policy",
        "clearing_rounding_policy",
        "cash_reserve_ratio",
        "cash_reserve_major",
        "margin_call_mode",
        "liquidation_target_buffer",
    }
    ledger_configs[ledger_id] = {
        key: settings[key]
        for key in ledger_config_keys
        if key in settings
    }


def _factor_grid_product_group_selections(client, product_groups: tuple[str, ...]) -> list[dict[str, Any]]:
    names = [str(item).strip() for item in product_groups if str(item).strip()]
    if not names:
        return []
    candidates = client.list_candidates("product_path_candidates")
    selections: list[dict[str, Any]] = []
    for name in names:
        match = next(
            (
                item for item in candidates
                if name in {
                    str(item.get("name") or ""),
                    str(item.get("label") or ""),
                    str(item.get("id") or ""),
                    str(item.get("product_path_selection_id") or ""),
                }
            ),
            None,
        )
        if match is None:
            raise click.ClickException(f"未找到产品组候选: {name}")
        selections.append(product_group_selection(match))
    return selections


def _register_factor_alias(state, client, alias: str, *, factor_family: str) -> None:
    candidates = list(state.page_settings.get("factor_candidates") or [])
    known = {str(item.get("factor_alias") or item.get("alias") or "") for item in candidates if isinstance(item, dict)}
    if alias in known:
        return
    params = _params_from_factor_alias(alias, factor_family)
    data = client.add_candidate("factor", {
        "factor_family_alias": factor_family,
        "params": params,
        "page_uuid": state.page_uuid,
    })
    factor_alias = str(data.get("factor_alias") or alias)
    candidates.append({"factor_alias": factor_alias, "params": params})
    state.page_settings["factor_candidates"] = candidates


def _apply_compare_scenario_settings(target: dict[str, Any], scenario_key: str, *, volume_rate: float) -> None:
    if scenario_key == "cap_limited_margin_none":
        target["liquidity_mode"] = "volume_participation"
        target["participation_rate"] = volume_rate
        target["margin_mode"] = "none"
    elif scenario_key == "cap_inf_margin_auto":
        target["liquidity_mode"] = "infinite"
        target.pop("participation_rate", None)
        target["margin_mode"] = "auto"
    else:
        target["liquidity_mode"] = "infinite"
        target.pop("participation_rate", None)
        target["margin_mode"] = "none"
    target["compare_scenario"] = scenario_key


def _register_compare_ledger(
    strategy_book: dict[str, Any],
    ledger_configs: dict[str, dict[str, Any]],
    strategy_id: str,
    scenario_key: str,
) -> None:
    ledger_id = f"private:{strategy_id}"
    strategy_book.setdefault("strategies", {})[strategy_id] = {
        "ledger_ids": [ledger_id],
        "default_ledger_id": ledger_id,
    }
    strategy_book.setdefault("cash_pools", {})[ledger_id] = ledger_id
    ledger_configs[ledger_id] = {
        "margin_mode": "auto" if scenario_key == "cap_inf_margin_auto" else "none",
    }


def _scenario_strategy_id(scenario_key: str, raw_id: str) -> str:
    clean = str(raw_id).replace(":", "_").replace("/", "_").replace(" ", "_")
    return f"cmp_{scenario_key}__{clean}"


def _draft_group_id(group: dict[str, Any]) -> str:
    group_id = str(group.get("id") or group.get("group_id") or group.get("strategy_id") or "").strip()
    if not group_id:
        raise click.ClickException(f"分组缺少 id: {group.get('name') or group}")
    return group_id


def _remap_long_short_leg_ids(config: dict[str, Any], id_map: dict[str, str]) -> None:
    for key in ("longGroupId", "long_group_id", "shortGroupId", "short_group_id"):
        value = str(config.get(key) or "")
        if value in id_map:
            config[key] = id_map[value]
    for key in ("long", "short"):
        legs = config.get(key)
        if not isinstance(legs, list):
            continue
        remapped = []
        for leg in legs:
            if isinstance(leg, dict):
                item = dict(leg)
                for leg_key in ("group_id", "strategy_id", "id"):
                    value = str(item.get(leg_key) or "")
                    if value in id_map:
                        item[leg_key] = id_map[value]
                remapped.append(item)
            else:
                value = str(leg)
                remapped.append(id_map.get(value, value))
        config[key] = remapped


def _print_compare_result_summary(state, scenarios: list[dict[str, str]]) -> None:
    data = _require_last_result(state)
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    scenario_labels = [scenario["label"] for scenario in scenarios]
    rows = []
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        scenario_label = next((label for label in scenario_labels if name.startswith(f"{label} · ")), "")
        if not scenario_label:
            continue
        base_name = name[len(scenario_label) + 3:]
        curve = _group_equity_curve(group)
        initial = curve[0] if curve else 0.0
        final = curve[-1] if curve else 0.0
        rows.append((
            scenario_label,
            base_name,
            f"{final:,.2f}" if curve else "",
            _pct(final / initial - 1.0) if initial else "",
            len(curve),
        ))
    if not rows:
        return
    click.echo("")
    click.echo("批量对比摘要")
    for line in render_table(
        ("场景", "策略", "最终权益", "收益率", "点数"),
        rows,
        indent="  ",
        aligns=("left", "left", "right", "right", "right"),
        max_widths=(22, 24, 16, 10, 8),
    ):
        click.echo(line)


def _print_factor_grid_result_summary(state, scenarios: list[dict[str, str]], *, top: int) -> None:
    data = _require_last_result(state)
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    scenario_by_key = {scenario["key"]: scenario for scenario in scenarios}
    rows: list[tuple[float, str, str, float, int]] = []
    for group in groups:
        scenario_key = str(group.get("compare_scenario") or "")
        scenario = scenario_by_key.get(scenario_key)
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        if scenario is None:
            scenario = next((item for item in scenarios if name.startswith(f"{item['label']} · ")), None)
        if scenario is None:
            continue
        prefix = f"{scenario['label']} · "
        strategy_name = name[len(prefix):] if name.startswith(prefix) else name
        curve = _group_equity_curve(group)
        if not curve:
            continue
        initial = curve[0]
        final = curve[-1]
        ret = final / initial - 1.0 if initial else 0.0
        rows.append((ret, scenario["label"], strategy_name, final, len(curve)))
    rows.sort(key=lambda item: item[0], reverse=True)
    if top > 0:
        rows = rows[:top]
    if not rows:
        return
    click.echo("")
    click.echo("因子参数/产品组收益率排行")
    for line in render_table(
        ("排名", "收益率", "最终权益", "策略", "候选", "点数"),
        [
            (index, _pct(ret), f"{final:,.2f}", strategy, scenario_label, points)
            for index, (ret, scenario_label, strategy, final, points) in enumerate(rows, start=1)
        ],
        indent="  ",
        aligns=("right", "right", "right", "left", "left", "right"),
        max_widths=(6, 10, 16, 24, 48, 8),
    ):
        click.echo(line)




def _audit_text(value: Any) -> str:
    if isinstance(value, str):
        parsed = _parse_audit_literal(value)
        if parsed is not None:
            parsed = _compact_audit_display_aliases(parsed)
            special_text = _audit_special_text(parsed)
            if special_text is not None:
                return special_text
            pandas_text = _audit_pandas_text(parsed)
            if pandas_text is not None:
                return pandas_text
            return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        return value
    value = _compact_audit_display_aliases(value)
    special_text = _audit_special_text(value)
    if special_text is not None:
        return special_text
    pandas_text = _audit_pandas_text(value)
    if pandas_text is not None:
        return pandas_text
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _audit_special_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") == "ContractMetadataTable":
        return _audit_contract_metadata_text(value)
    if value.get("type") == "PriceTablesSummary":
        return _audit_price_tables_text(value)
    return None


def _audit_contract_metadata_text(value: dict[str, Any]) -> str:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return "contract_metadata: (no rows)"
    table_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        table_rows.append((
            row.get("product") or "",
            row.get("contract") or "",
            row.get("start") or "",
            row.get("end") or "",
        ))
    if not table_rows:
        return "contract_metadata: (empty)"
    return "\n".join(render_table(
        ("原产品", "新合约", "起始时间", "终止时间"),
        table_rows,
        max_widths=(18, 24, 16, 16),
    ))


def _audit_price_tables_text(value: dict[str, Any]) -> str:
    rows = value.get("rows")
    if not isinstance(rows, list):
        return "price_tables: (no rows)"
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        shape = row.get("shape")
        if isinstance(shape, list | tuple) and len(shape) == 2:
            shape_text = f"{shape[0]} x {shape[1]}"
        else:
            shape_text = str(shape or "")
        index_value = row.get("index")
        if isinstance(index_value, dict) and {"start", "end"} <= set(index_value):
            index_text = f"{index_value.get('start')} → {index_value.get('end')}"
        else:
            index_text = str(index_value or "")
        if lines:
            lines.append("")
        lines.append(f"价格字段: {row.get('basis') or ''}")
        lines.append(f"  shape   = {shape_text}")
        lines.append(f"  index   = {index_text}")
        lines.append(f"  columns = {_audit_columns_summary(row.get('columns'))}")
    if not lines:
        return "price_tables: (empty)"
    return "\n".join(lines)


def _audit_columns_summary(columns: Any) -> str:
    if isinstance(columns, dict):
        count = columns.get("count")
        sampled = columns.get("sampled")
        sampled_count = len(sampled) if isinstance(sampled, list) else 0
        if count is not None and sampled_count:
            return f"{count} columns; sample shows {sampled_count} columns"
        if count is not None:
            return f"{count} columns"
    if isinstance(columns, list):
        if len(columns) <= 20:
            return json.dumps(columns, ensure_ascii=False, default=str)
        return f"{len(columns)} columns"
    return str(columns or "")


def _audit_pandas_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    value_type = value.get("type")
    if value_type == "DataFrame":
        return _audit_dataframe_text(value)
    if value_type == "Series":
        return _audit_series_text(value)
    return None


def _audit_dataframe_text(value: dict[str, Any]) -> str:
    lines: list[str] = []
    shape = value.get("shape")
    if isinstance(shape, list | tuple) and len(shape) == 2:
        header = f"pd.DataFrame shape=({shape[0]}, {shape[1]})"
    else:
        rows = value.get("rows")
        columns = value.get("columns")
        row_count = len(rows) if isinstance(rows, list) else "?"
        column_count = len(columns) if isinstance(columns, list) else "?"
        header = f"pd.DataFrame shape=({row_count}, {column_count})"
    index_bounds = value.get("index")
    if isinstance(index_bounds, dict) and {"start", "end"} <= set(index_bounds):
        header = f"{header} index={index_bounds.get('start')} → {index_bounds.get('end')}"
    if value.get("truncated"):
        header = f"{header} truncated=True"
    lines.append(header)
    columns = value.get("columns")
    if value.get("truncated"):
        if isinstance(columns, list):
            lines.append(f"columns = {json.dumps(columns, ensure_ascii=False, default=str)}")
        elif isinstance(columns, dict):
            count = columns.get("count")
            sampled = columns.get("sampled")
            sampled_count = len(sampled) if isinstance(sampled, list) else 0
            if count is not None and sampled_count:
                lines.append(f"columns = {count} columns; sample shows {sampled_count} columns")
            elif count is not None:
                lines.append(f"columns = {count} columns")

    if isinstance(value.get("sample"), dict):
        sample = value["sample"]
        for name in ("head", "tail"):
            part = sample.get(name)
            if isinstance(part, dict):
                lines.append(f"sample.{name}:")
                lines.extend(_audit_dataframe_table_lines(part, indent="  "))
    else:
        lines.extend(_audit_dataframe_table_lines(value, indent="  "))
    return "\n".join(lines)


def _audit_dataframe_table_lines(value: dict[str, Any], *, indent: str = "") -> list[str]:
    columns = [str(column) for column in value.get("columns", [])]
    indexes = value.get("index", [])
    rows = value.get("rows", [])
    if not isinstance(indexes, list) or not isinstance(rows, list):
        return [f"{indent}(no tabular rows)"]
    table_rows = []
    for index, row in zip(indexes, rows, strict=False):
        row_values = row if isinstance(row, list) else [row]
        table_rows.append((str(index), *[str(item) for item in row_values]))
    if not table_rows:
        return [f"{indent}(empty)"]
    return render_table(("index", *columns), table_rows, indent=indent)


def _audit_series_text(value: dict[str, Any]) -> str:
    name = value.get("name")
    length = value.get("length")
    if length is not None:
        header = f"pd.Series name={name!r} length={length}"
    else:
        values = value.get("values")
        header = f"pd.Series name={name!r} length={len(values) if isinstance(values, list) else '?'}"
    index_bounds = value.get("index")
    if isinstance(index_bounds, dict) and {"start", "end"} <= set(index_bounds):
        header = f"{header} index={index_bounds.get('start')} → {index_bounds.get('end')}"
    if value.get("truncated"):
        header = f"{header} truncated=True"

    lines = [header]
    if isinstance(value.get("sample"), dict):
        sample = value["sample"]
        for name in ("head", "tail"):
            part = sample.get(name)
            if isinstance(part, dict):
                lines.append(f"sample.{name}:")
                lines.extend(_audit_series_table_lines(part, indent="  "))
    else:
        lines.extend(_audit_series_table_lines(value, indent="  "))
    return "\n".join(lines)


def _audit_series_table_lines(value: dict[str, Any], *, indent: str = "") -> list[str]:
    indexes = value.get("index", [])
    values = value.get("values", [])
    if not isinstance(indexes, list) or not isinstance(values, list):
        return [f"{indent}(no series rows)"]
    table_rows = [(str(index), str(item)) for index, item in zip(indexes, values, strict=False)]
    if not table_rows:
        return [f"{indent}(empty)"]
    return render_table(("index", "value"), table_rows, indent=indent)


def _parse_audit_literal(value: str) -> Any | None:
    text = value.strip()
    if len(text) < 2 or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return None
    if isinstance(parsed, (dict, list, tuple)):
        return parsed
    return None


def _compact_audit_display_aliases(value: Any) -> Any:
    if isinstance(value, dict):
        compacted = {
            str(key): _compact_audit_display_aliases(item)
            for key, item in value.items()
        }
        if _looks_like_product_path_selection(compacted):
            return _compact_product_path_selection_for_audit(compacted)
        return compacted
    if isinstance(value, list):
        return [_compact_audit_display_aliases(item) for item in value]
    if isinstance(value, tuple):
        return [_compact_audit_display_aliases(item) for item in value]
    return value


def _looks_like_product_path_selection(value: dict[str, Any]) -> bool:
    return bool(
        "product_path_selection_id" in value
        or ("id" in value and ("selected_paths" in value or "paths" in value))
        or ("selected_paths" in value and "paths" in value)
        or ("product_group_template_id" in value and "path_id" in value)
    )


def _compact_product_path_selection_for_audit(value: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    selection_id = value.get("product_path_selection_id") or value.get("selection_id") or value.get("id")
    if selection_id not in (None, ""):
        compacted["product_path_selection_id"] = selection_id
    label = value.get("label") or value.get("product_group")
    if label not in (None, ""):
        compacted["label"] = label
    product_group = value.get("product_group")
    if product_group not in (None, "", label):
        compacted["product_group"] = product_group
    template_id = value.get("product_group_template_id") or value.get("path_id")
    if template_id not in (None, ""):
        compacted["product_group_template_id"] = template_id
    paths = value.get("paths") if "paths" in value else value.get("selected_paths")
    if paths not in (None, ""):
        compacted["paths"] = paths
    source_type = value.get("source_type")
    if source_type not in (None, ""):
        compacted["source_type"] = source_type
    source_key = value.get("source_key")
    if source_key not in (None, "", selection_id, template_id):
        compacted["source_key"] = source_key
    return compacted


def _display_field_value(qualified_name: str, value: Any) -> Any:
    if qualified_name == "MarketDataModule.required_data_source" and value in ((), []):
        return "auto（自动选择）"
    offset = _field_display_offsets.get(qualified_name, _field_display_offsets.get(qualified_name.rsplit(".", 1)[-1], 0))
    if offset and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value + offset
    return value


def _print_audit_value(prefix: str, label: str, value: Any) -> None:
    grouped = _audit_repeated_owner_groups(value)
    if grouped:
        click.echo(f"{prefix}{label} =")
        for owner_label, owner_value in grouped:
            _print_audit_value(f"{prefix}  ", owner_label, owner_value)
        return
    lines = _audit_text(value).splitlines() or [""]
    if len(lines) == 1:
        _print_wrapped_line(f"{prefix}{label} = {lines[0]}", continuation_indent=f"{prefix}  ")
        return
    click.echo(f"{prefix}{label} =")
    for line in lines:
        _print_wrapped_line(f"{prefix}  {line}", continuation_indent=f"{prefix}    ")


def _step_section_title(title: str) -> str:
    return f"━━ {title} ━━"


def _print_step_section(title: str) -> None:
    click.secho(_step_section_title(title), fg="cyan", bold=True, color=True)


def _print_wrapped_line(line: str, *, continuation_indent: str) -> None:
    width = max(40, min(shutil.get_terminal_size((120, 20)).columns, 120))
    if len(line) <= width:
        click.echo(line)
        return
    wrapped = textwrap.wrap(
        line,
        width=width,
        subsequent_indent=continuation_indent,
        break_long_words=True,
        break_on_hyphens=False,
    )
    if not wrapped:
        click.echo(line)
        return
    for wrapped_line in wrapped:
        click.echo(wrapped_line)


def _audit_display_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _audit_normalized_value(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _parse_audit_literal(value)
        if parsed is not None:
            return _compact_audit_display_aliases(parsed)
    return _compact_audit_display_aliases(value)


def _audit_repeated_owner_groups(value: Any) -> list[tuple[str, Any]]:
    normalized = _audit_normalized_value(value)
    if not isinstance(normalized, dict) or len(normalized) <= 1:
        return []
    items = list(normalized.items())
    if not all(isinstance(item_value, (dict, list)) for _, item_value in items):
        return []
    groups: dict[str, dict[str, Any]] = {}
    for item_key, item_value in items:
        group_key = _audit_display_key(item_value)
        bucket = groups.setdefault(group_key, {"keys": [], "value": item_value})
        bucket["keys"].append(str(item_key))
    if len(groups) >= len(items):
        return []
    return [
        (f"策略 {', '.join(sorted(bucket['keys']))}", bucket["value"])
        for bucket in groups.values()
    ]


def _audit_join(values: list[Any]) -> str:
    unique = sorted({str(value) for value in values if value not in (None, "")})
    return ", ".join(unique) if unique else "无"


def _audit_source_group_label(entries: list[dict[str, Any]]) -> str:
    scopes = {str(entry.get("scope") or "") for entry in entries}
    strategies = _audit_join([
        strategy
        for entry in entries
        for strategy in (
            entry.get("strategies")
            if isinstance(entry.get("strategies"), list)
            else [entry.get("strategy")]
        )
    ])
    ledgers = _audit_join([entry.get("ledger") for entry in entries])
    cash_pools = _audit_join([entry.get("cash_pool") for entry in entries])

    if scopes <= {"strategy_config"}:
        if strategies == "无":
            return "[共享]"
        return f"策略配置 {strategies}"
    if scopes <= {"strategy_context"}:
        if strategies == "无":
            return "[共享]"
        return f"策略上下文 {strategies}"
    if scopes <= {"ledger"}:
        if len(entries) > 1:
            return _audit_ledger_group_label(entries, prefix="合并")
        return f"账本 {ledgers} | 现金池 {cash_pools} | 策略 {strategies}"
    if scopes <= {"ledger_config"}:
        if len(entries) > 1:
            return _audit_ledger_group_label(entries, prefix="合并账本配置")
        return f"账本配置 {ledgers} | 现金池 {cash_pools} | 策略 {strategies}"
    if scopes <= {"context"}:
        return "[共享]"
    if scopes <= {"context", "strategy_context"}:
        if strategies == "无":
            return "[共享]"
        return f"共享上下文 + 策略上下文 {strategies}"
    if scopes <= {"context", "strategy_config"}:
        if strategies == "无":
            return "[共享]"
        return f"共享上下文 + 策略配置 {strategies}"
    return "[合并] " + "；".join(_audit_source_label(entry) for entry in entries)


def _audit_ledger_group_label(entries: list[dict[str, Any]], *, prefix: str) -> str:
    ledgers = {str(entry.get("ledger") or "") for entry in entries if entry.get("ledger") not in (None, "")}
    cash_pools = {str(entry.get("cash_pool") or "") for entry in entries if entry.get("cash_pool") not in (None, "")}
    strategies = {
        str(strategy)
        for entry in entries
        for strategy in (entry.get("strategies") if isinstance(entry.get("strategies"), list) else [])
        if strategy not in (None, "")
    }
    parts = [f"{prefix} {len(ledgers)} 个账本"]
    if cash_pools:
        parts.append(f"{len(cash_pools)} 个现金池")
    if strategies:
        parts.append(f"{len(strategies)} 个策略")
    return " / ".join(parts)


def _audit_source_route_rows(entries: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    scopes = {str(entry.get("scope") or "") for entry in entries}
    if len(entries) <= 1 or not scopes <= {"ledger", "ledger_config"}:
        return []
    rows = []
    for entry in entries:
        rows.append((
            str(entry.get("ledger") or "?"),
            str(entry.get("cash_pool") or "?"),
            ", ".join(str(strategy) for strategy in (entry.get("strategies") or [])) or "无",
        ))
    return sorted(rows)


def _print_audit_source_routes(prefix: str, entries: list[dict[str, Any]]) -> bool:
    rows = _audit_source_route_rows(entries)
    if not rows:
        return False
    for line in render_table(
        ("ledger", "cash pool", "strategies"),
        rows,
        indent=prefix,
        max_widths=(34, 34, 52),
    ):
        click.echo(line)
    return True


def _audit_grouped_values(field_name: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for entry in values:
        if not isinstance(entry, dict):
            continue
        display_value = _display_field_value(field_name, entry.get("value"))
        key = _audit_display_key(display_value)
        bucket = groups.setdefault(key, {"value": display_value, "entries": []})
        bucket["entries"].append(entry)
    return list(groups.values())


def _print_audit_diff_value(prefix: str, label: str, before: Any, after: Any) -> None:
    if _audit_repeated_owner_groups(before) or _audit_repeated_owner_groups(after):
        click.echo(f"{prefix}{label}:")
        _print_audit_value(f"{prefix}  ", "before", before)
        _print_audit_value(f"{prefix}  ", "after", after)
        return
    before_lines = _audit_text(before).splitlines() or [""]
    after_lines = _audit_text(after).splitlines() or [""]
    if len(before_lines) == 1 and len(after_lines) == 1:
        _print_wrapped_line(
            f"{prefix}{label} = {before_lines[0]} -> {after_lines[0]}",
            continuation_indent=f"{prefix}  ",
        )
        return
    click.echo(f"{prefix}{label}:")
    click.echo(f"{prefix}  before =")
    for line in before_lines:
        _print_wrapped_line(f"{prefix}    {line}", continuation_indent=f"{prefix}      ")
    click.echo(f"{prefix}  after =")
    for line in after_lines:
        _print_wrapped_line(f"{prefix}    {line}", continuation_indent=f"{prefix}      ")


def _audit_field_label(qualified_name: str) -> str:
    field_name = qualified_name.rsplit(".", 1)[-1]
    return f"{_flabel(field_name)} [{qualified_name}]"


def _audit_field_sort_key(qualified_name: str) -> tuple[int, int, str]:
    field_name = qualified_name.rsplit(".", 1)[-1]
    display_order = _field_display_order.get(qualified_name, _field_display_order.get(field_name))
    tab_order = _field_tab_order.get(qualified_name, _field_tab_order.get(field_name))
    return (
        int(display_order) if display_order is not None else 1_000_000,
        int(tab_order) if tab_order is not None else 1_000_000,
        qualified_name,
    )


def _audit_source_label(entry: dict[str, Any]) -> str:
    scope = str(entry.get("scope") or "")
    if scope == "strategy_config":
        return f"策略配置 {entry.get('strategy') or '?'}"
    if scope == "strategy_context":
        return f"策略上下文 {entry.get('strategy') or '?'}"
    if scope == "ledger":
        strategies = ", ".join(entry.get("strategies") or []) or "无"
        return (
            f"账本 {entry.get('ledger') or '?'} | 现金池 {entry.get('cash_pool') or '?'}"
            f" | 策略 {strategies}"
        )
    if scope == "ledger_config":
        strategies = ", ".join(entry.get("strategies") or []) or "无"
        return (
            f"账本配置 {entry.get('ledger') or '?'} | 现金池 {entry.get('cash_pool') or '?'}"
            f" | 策略 {strategies}"
        )
    return "共享上下文"


def _print_audit_fields(title: str, records: list[dict[str, Any]], *, empty_message: str = "（无字段）") -> None:
    _print_step_section(title)
    if not records:
        click.echo(f"  {empty_message}")
        return
    for record in sorted(records, key=lambda item: _audit_field_sort_key(str(item.get("field") or ""))):
        click.echo(f"  {_audit_field_label(str(record.get('field') or ''))}:")
        values = record.get("values") or []
        if not values:
            click.echo("    （当前无值）")
            continue
        field_name = str(record.get("field") or "")
        for bucket in _audit_grouped_values(field_name, values):
            label = _audit_source_group_label(bucket["entries"])
            if _audit_source_route_rows(bucket["entries"]):
                click.echo(f"    {label}:")
                _print_audit_source_routes("      ", bucket["entries"])
                _print_audit_value("      ", "value", bucket["value"])
            else:
                _print_audit_value("    ", label, bucket["value"])
        

def _print_audit_changes(title: str, changes: list[dict[str, Any]]) -> None:
    _print_step_section(title)
    if not changes:
        click.echo("  （无变化）")
        return
    by_field: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        by_field.setdefault(str(change.get("field") or ""), []).append(change)
    for field_name, field_changes in sorted(by_field.items(), key=lambda item: _audit_field_sort_key(item[0])):
        click.echo(f"  {_audit_field_label(field_name)}:")
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for change in field_changes:
            before = _display_field_value(field_name, change.get("before"))
            after = _display_field_value(field_name, change.get("after"))
            key = (_audit_display_key(before), _audit_display_key(after))
            bucket = grouped.setdefault(key, {"before": before, "after": after, "entries": []})
            bucket["entries"].append(change)
        for bucket in grouped.values():
            label = _audit_source_group_label(bucket["entries"])
            if _audit_source_route_rows(bucket["entries"]):
                click.echo(f"    {label}:")
                _print_audit_source_routes("      ", bucket["entries"])
                _print_audit_diff_value("      ", "value", bucket["before"], bucket["after"])
            else:
                _print_audit_diff_value("    ", label, bucket["before"], bucket["after"])


def _print_ledger_snapshot(ledgers: list[dict[str, Any]]) -> None:
    _print_step_section("本次 flow 的 active ledgers / cash pools（执行前）")
    if not ledgers:
        click.echo("  （此 flow 尚未关联账本）")
        return
    rows = [
        (
            ledger.get("ledger") or "?",
            ledger.get("cash_pool") or "?",
            ", ".join(ledger.get("strategies") or []) or "无",
            _audit_text(ledger.get("cash")).replace("\n", " "),
        )
        for ledger in ledgers
    ]
    for line in render_table(("ledger", "cash pool", "strategies", "cash"), rows, indent="  ", max_widths=(32, 32, 36, 24)):
        click.echo(line)


def _unchanged_output_records(
    records: list[dict[str, Any]], changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changed_fields = {str(change.get("field") or "") for change in changes}
    return [record for record in records if str(record.get("field") or "") not in changed_fields]


def _print_strategy_context(strategies: list[dict[str, Any]]) -> None:
    _print_step_section("本次 flow 的 active strategies")
    if not strategies:
        click.echo("  （此 flow 尚未关联策略）")
        return
    rows = [
        (
            str(strategy.get("strategy") or "?"),
            ", ".join(strategy.get("ledgers") or []) or "无",
        )
        for strategy in strategies
    ]
    for line in render_table(("strategy", "ledgers"), rows, indent="  ", max_widths=(24, 52)):
        click.echo(line)


def _print_event_payloads(payloads: list[dict[str, Any]]) -> None:
    if not payloads:
        return
    _print_step_section("本批事件草稿载荷（执行前，非完整事件队列）")
    for payload in payloads:
        if payload.get("scope") == "strategy":
            label = f"策略 {payload.get('strategy') or '?'}"
        else:
            label = f"账本 {payload.get('ledger') or '?'} | 现金池 {payload.get('cash_pool') or '?'}"
        _print_audit_value("  ", label, payload.get("payloads"))


def _print_event_payload_changes(changes: list[dict[str, Any]]) -> None:
    _print_step_section("本批事件草稿载荷变化（非完整事件队列）")
    if not changes:
        click.echo("  （无变化）")
        return
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for change in changes:
        key = (_audit_display_key(change.get("before")), _audit_display_key(change.get("after")))
        bucket = grouped.setdefault(key, {"before": change.get("before"), "after": change.get("after"), "entries": []})
        bucket["entries"].append(change)
    for bucket in grouped.values():
        _print_audit_diff_value(
            "  ",
            _audit_source_group_label(bucket["entries"]),
            bucket["before"],
            bucket["after"],
        )


def _print_contract_audit(violations: list[dict[str, Any]]) -> None:
    _print_step_section("字段声明审计")
    if not violations:
        click.echo("  已通过：本 flow 未读取未声明输入字段，也未写入未声明输出字段")
        return
    for violation in violations:
        access = str(violation.get("access") or "")
        action = "读取未声明输入" if access == "read" else "写入未声明输出" if access == "write" else f"未声明 {access}"
        field = violation.get("field") or "?"
        click.echo(f"  {action}: {field}")


@dataclass
class _StepNavigator:
    until: datetime | None = None
    to_end: bool = False

    def should_display(self, timestamp: Any) -> bool:
        if self.to_end:
            return False
        if self.until is None:
            return True
        current = _parse_step_timestamp(timestamp)
        if current is None or current < self.until:
            return False
        self.until = None
        return True


def _parse_step_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        # Compare the wall-clock timestamp exactly as printed by the server;
        # the remote CLI machine may live in a different local timezone.
        parsed = parsed.replace(tzinfo=None)
    return parsed


def _set_step_navigation(navigator: _StepNavigator, command: str) -> str | None:
    text = command.strip()
    if not text:
        return None
    if text.lower() in {"end", "finish"}:
        navigator.to_end = True
        navigator.until = None
        return None
    if text.lower().startswith("until "):
        target = _parse_step_timestamp(text[6:].strip())
        if target is None:
            return "无法解析时刻；示例: until 2026-01-15 10:30:00"
        navigator.until = target
        navigator.to_end = False
        return None
    return "未知命令；使用 Enter、until <时刻> 或 end"


def _continue_step(client, run_token: str, navigator: _StepNavigator | None = None) -> None:
    payload: dict[str, Any] = {"run_token": run_token, "action": "continue"}
    if navigator is not None and navigator.to_end:
        payload["action"] = "end"
    elif navigator is not None and navigator.until is not None:
        payload["action"] = "until"
        payload["until"] = navigator.until.isoformat(sep=" ")
    try:
        client.session.post("/step_continue", payload)
    except Exception as exc:
        raise click.ClickException(f"无法继续单步回测: {exc}") from exc


def _handle_step_event(
    data: dict[str, Any],
    client,
    run_token: str,
    navigator: _StepNavigator,
) -> None:
    """Render one complete, post-compute audit record and continue once."""
    if str(data.get("phase") or "") != "step":
        return
    if not navigator.should_display(data.get("timestamp")):
        _continue_step(client, run_token, navigator)
        return

    flow_phase = str(data.get("flow_phase") or "")
    flow_name = str(data.get("flow_name") or "")
    flow_id = str(data.get("flow_id") or "")
    phase_text = f"{flow_phase.upper()} ({phase_label(flow_phase)})"
    click.echo("")
    click.secho(f"flow: {phase_text} · {flow_id} ({flow_name})", fg="red", color=True)
    description = str(data.get("description") or "")
    if description:
        click.echo(f"说明: {description}")

    strategies = list(data.get("strategies") or [])
    _print_strategy_context(strategies)
    _print_ledger_snapshot(list(data.get("ledgers_before") or []))
    _print_event_payloads(list(data.get("event_payloads") or []))
    _print_audit_fields(
        "输入字段",
        list(data.get("inputs") or []),
        empty_message="（此 flow 未声明输入字段）",
    )
    output_changes = list(data.get("output_changes") or [])
    outputs = list(data.get("outputs") or [])
    unchanged_outputs = _unchanged_output_records(outputs, output_changes)
    if not outputs:
        unchanged_output_message = "（此 flow 未声明输出字段）"
    elif output_changes:
        unchanged_output_message = "（所有声明输出字段均发生变化，见下方“声明输出的变化”）"
    else:
        unchanged_output_message = "（没有未变化的声明输出字段）"
    _print_audit_fields(
        "声明输出字段（未变化）",
        unchanged_outputs,
        empty_message=unchanged_output_message,
    )
    _print_audit_changes("声明输出的变化", output_changes)
    _print_event_payload_changes(list(data.get("event_payload_changes") or []))
    _print_audit_changes("账本与现金池变化", list(data.get("ledger_changes") or []))
    _print_contract_audit(list(data.get("input_contract_violations") or []))

    click.echo("")
    while True:
        click.echo("命令: Enter=下一步 | until <时刻>=快进到时刻 | end=快进到底")
        error = _set_step_navigation(navigator, input("step> "))
        if error is None:
            break
        click.echo(f"  {error}")
    _continue_step(client, run_token, navigator)

def _run_backtest(
    state,
    *,
    groups: list[dict[str, Any]],
    verbose: bool = False,
    step_mode: bool = False,
    ls_configs: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    title: str = "回测",
    show_topology: bool = True,
) -> None:
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login 以创建页面上下文")
    if not groups:
        raise click.ClickException("没有可运行的分组；请先用 factortester group --add 新增分组")
    display_ls_configs = ls_configs if ls_configs is not None else state.backtest_ls_configs
    run_payload = payload or _run_payload(state, groups=groups)
    if step_mode:
        import uuid as _uuid
        _run_token_id = _uuid.uuid4().hex
        run_payload["run_token"] = _run_token_id
        run_payload["step_mode"] = True
    else:
        _run_token_id = run_payload.get("run_token", "")
    click.echo(f"开始运行{title}: groups={len(groups)}, long-short={len(display_ls_configs)}")
    if not step_mode:
        _print_run_strategy_info(groups, display_ls_configs)
    payload_strategy_book = run_payload.get("strategy_book")
    payload_ledger_configs = run_payload.get("ledger_configs")
    if show_topology:
        if state.backtest_strategy_book and payload is None:
            _print_strategy_book(state)
        elif isinstance(payload_strategy_book, dict) and payload_strategy_book:
            _print_strategy_book_payload(payload_strategy_book)
        if state.backtest_ledger_configs and payload is None:
            _print_ledger_configs(state)
        elif isinstance(payload_ledger_configs, dict) and payload_ledger_configs:
            _print_ledger_config_payload(payload_ledger_configs)
    client = client_from_config()
    # A saved template/CLI draft persists aliases and parameters, never Factor
    # instances.  Recreate one-off Factors in the current page before every
    # run so a new login/page_uuid cannot depend on an older page cache.
    _register_template_factors(state, client)
    renderer = BacktestRunRenderer(verbose=verbose, live=_equity_curve_live_enabled(state, client=client), step_mode=step_mode)
    step_navigator = _StepNavigator()
    # Build shortAlias mapping
    import tools.cli.modules.backtest.controller as _ctrl_mod
    _ctrl_mod._short_alias_map.clear()
    for _g in state.backtest_groups:
        _gid = str(_g.get("id", "") or "")
        _sa = str(_g.get("shortAlias", "") or "")
        if _gid and _sa:
            _ctrl_mod._short_alias_map[_gid] = _sa
    for _ls in state.backtest_ls_configs or []:
        _ls_id = str(_ls.get("id", "") or "")
        _ls_sa = str(_ls.get("shortAlias", "") or "")
        if _ls_id and _ls_sa:
            _ctrl_mod._short_alias_map[_ls_id] = _ls_sa
    for event in client.run_group_test_stream(run_payload):
        event_name = str(event.get("event") or "message")
        data = event.get("data")
        if event_name == "error":
            message = data.get("error") if isinstance(data, dict) else data
            traceback_text = str(data.get("traceback") or "").strip() if isinstance(data, dict) else ""
            if traceback_text:
                message = f"{message}\n{traceback_text}"
            raise click.ClickException(f"分组测试失败: {message}")
        if event_name == "step" and isinstance(data, dict):
            _handle_step_event(
                data,
                client,
                _run_token_id,
                step_navigator,
            )
        elif event_name in {"activity_manifest", "runtime_info", "progress", "activity", "signal_progress", "result", "complete", "done"}:
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
        "groups": [_serialize_group_for_run(group) for group in groups],
        "ls_configs": list(state.backtest_ls_configs),
    }
    if state.backtest_strategy_book:
        payload["strategy_book"] = _serialize_strategy_book_for_run(state, groups)
    if state.backtest_ledger_configs:
        payload["ledger_configs"] = {
            str(ledger): dict(config)
            for ledger, config in state.backtest_ledger_configs.items()
        }
    return payload


def _serialize_strategy_book_for_run(state, groups: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _strategy_book_payload(state)
    strategy_ids: dict[str, str] = {}
    for group in groups:
        strategy_id = str(group.get("id") or "")
        if not strategy_id:
            continue
        for candidate in (group.get("shortAlias"), group.get("name"), strategy_id):
            alias = str(candidate or "")
            if alias:
                strategy_ids[alias] = strategy_id
    strategies = payload.get("strategies")
    if isinstance(strategies, dict):
        payload["strategies"] = {
            strategy_ids.get(str(alias), str(alias)): value
            for alias, value in strategies.items()
        }
    return payload


def _serialize_group_for_run(group: dict[str, Any]) -> dict[str, Any]:
    """Translate the CLI's registered field names at the HTTP boundary."""
    payload = dict(group)
    if "split_count" in group:
        payload["splitCount"] = group["split_count"]
    if "group_index" in group:
        payload["groupIndex"] = group["group_index"]
    if "factor" in group:
        payload["factorAlias"] = group["factor"]
    return payload


def _print_results_help() -> None:
    click.echo("backtest results 命令")
    click.echo("  summary                         最近一次运行的统计表格")
    click.echo("  equity                          最近一次运行的多策略净值图")
    click.echo("  attribution [--group-name NAME]  归因摘要: gross / fee / net / final")
    click.echo("    --by product|ledger|cash-pool 按产品/账本/资金池聚合手续费")
    click.echo("    --top N                       聚合表显示前 N 行(默认10)")
    click.echo("  ledgers [--group-name NAME]      按 ledger/cash pool 汇总成交落账回放")
    click.echo("  detail --group-name NAME         查看 web 组内 overlay 的贡献/费率摘要")
    click.echo("    --level product|contract      产品或合约层级(默认product)")
    click.echo("  ranking                          查看分组排序能力摘要")
    click.echo("  snapshot --index N              查看第 N 个时间点的持仓/资金快照")
    click.echo("  snapshot --timestamp-ms MS      查看指定 epoch 毫秒附近的快照")
    click.echo("  order-flow [--group-name NAME]  查看订单流明细(时间/品种/数量/成交价/状态)")
    click.echo("    --show fee                    显示 fee_cost / cash / margin 诊断列")
    click.echo("    --ledger ID                   只显示指定账本的记录")
    click.echo("    --cash-pool ID                只显示指定资金池的记录")
    click.echo("    --order-id ID                 只看某笔订单的完整生命周期")
    click.echo("    --limit N                     每个策略最多显示的记录数(默认20, 0=全部)")
    click.echo("    --counts-only                 只显示记录条数，不展开明细")
    click.echo("")
    click.echo("输出选项（所有 results 子命令通用）:")
    click.echo("  --output PATH                   写入文件")
    click.echo("  --no-terminal                   不打印到终端，仅写文件")
    click.echo("  --append                        追加写入文件而不是覆盖")


def _parse_result_output_options(args: tuple[str, ...]) -> tuple[dict[str, Any], tuple[str, ...]]:
    options: dict[str, Any] = {
        "output": "",
        "terminal": True,
        "append": False,
    }
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--output", "-o"}:
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise click.ClickException(f"{token} 缺少文件路径")
            options["output"] = args[i + 1]
            i += 2
            continue
        if token.startswith("--output="):
            options["output"] = token.split("=", 1)[1]
            i += 1
            continue
        if token == "--no-terminal":
            options["terminal"] = False
            i += 1
            continue
        if token == "--append":
            options["append"] = True
            i += 1
            continue
        cleaned.append(token)
        i += 1
    if not options["terminal"] and not options["output"]:
        raise click.ClickException("--no-terminal 必须搭配 --output PATH")
    return options, tuple(cleaned)


def _emit_result_output(options: dict[str, Any], callback) -> None:
    output_path = str(options.get("output") or "")
    terminal = bool(options.get("terminal", True))
    append = bool(options.get("append", False))
    if terminal and not output_path:
        callback()
        return
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        callback()
    text = buffer.getvalue()
    if output_path:
        path = Path(output_path).expanduser()
        if path.parent and str(path.parent) not in {"", "."}:
            path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            fh.write(text)
            if text and not text.endswith("\n"):
                fh.write("\n")
    if terminal and text:
        click.echo(text, nl=False)


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


def _print_attribution_result(state, args: tuple[str, ...]) -> None:
    data = _require_last_result(state)
    groups = _selected_result_groups(data, _arg_value(args, "--group-name"))
    if not groups:
        raise click.ClickException("最近一次结果中找不到可归因的策略")
    by = (_arg_value(args, "--by") or "").strip().lower()
    top_raw = _arg_value(args, "--top")
    top_n = int(top_raw) if top_raw else 10
    rows = []
    bucket_fee: dict[str, float] = {}
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        curve = _group_equity_curve(group)
        initial = curve[0] if curve else 0.0
        final = curve[-1] if curve else 0.0
        flow = _fetch_order_flow_for_group(state, data, name)
        fee_sum = 0.0
        for record in flow:
            fee = _float(record.get("fee_cost") or record.get("fee") or 0.0)
            fee_sum += fee
            bucket = _attribution_bucket(record, by)
            if bucket:
                bucket_fee[bucket] = bucket_fee.get(bucket, 0.0) + fee
        net_return = final / initial - 1.0 if initial else 0.0
        fee_return = fee_sum / initial if initial else 0.0
        gross_return = net_return + fee_return
        rows.append((
            name,
            _pct(gross_return),
            _pct(-fee_return),
            _pct(net_return),
            f"{final:,.2f}",
            f"{fee_sum:,.2f}",
            len(flow),
        ))
    click.echo("归因摘要")
    for line in render_table(
        ("策略", "gross", "fee", "net", "最终权益", "费用", "订单流"),
        rows,
        indent="  ",
        aligns=("left", "right", "right", "right", "right", "right", "right"),
        max_widths=(28, 10, 10, 10, 16, 16, 8),
    ):
        click.echo(line)
    if by in {"product", "products", "contract", "contracts", "ledger", "ledgers", "cash-pool", "cash_pool", "cashpool"}:
        table = sorted(bucket_fee.items(), key=lambda item: abs(item[1]), reverse=True)
        if top_n > 0:
            table = table[:top_n]
        click.echo("")
        click.echo(_attribution_table_title(by))
        for line in render_table(
            (_attribution_table_header(by), "费用"),
            [(bucket, f"{fee:,.2f}") for bucket, fee in table],
            indent="  ",
            aligns=("left", "right"),
            max_widths=(32, 16),
        ):
            click.echo(line)


def _print_ledger_replay_result(state, args: tuple[str, ...]) -> None:
    data = _require_last_result(state)
    groups = _selected_result_groups(data, _arg_value(args, "--group-name"))
    if not groups:
        raise click.ClickException("最近一次结果中找不到可汇总的策略")
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for group in groups:
        name = str(group.get("name") or group.get("group_id") or group.get("id") or "")
        for record in _fetch_order_flow_for_group(state, data, name):
            ledger_id = _record_ledger_id(record)
            cash_pool_id = _record_cash_pool_id(record)
            if not ledger_id and not cash_pool_id:
                continue
            key = (name, ledger_id or "(未记录账本)", cash_pool_id or "(未记录资金池)")
            row = rows_by_key.setdefault(key, {
                "records": 0,
                "fee": 0.0,
                "last_cash": "",
                "last_margin": "",
            })
            row["records"] += 1
            row["fee"] += _float(record.get("fee_cost") or record.get("fee") or 0.0)
            cash_after = _fmt_detail_number(record, "cash_after")
            if cash_after:
                row["last_cash"] = cash_after
            margin_after = _fmt_detail_number(record, "margin_after")
            if margin_after:
                row["last_margin"] = margin_after
    click.echo("Ledger 回放摘要")
    if not rows_by_key:
        click.echo("  最近一次 order-flow 没有记录 ledger/cash pool 信息；请重新运行回测以生成新的成交落账 trace。")
        return
    rows = [
        (
            strategy,
            ledger_id,
            cash_pool_id,
            values["records"],
            f"{values['fee']:,.2f}",
            values["last_cash"],
            values["last_margin"],
        )
        for (strategy, ledger_id, cash_pool_id), values in sorted(rows_by_key.items())
    ]
    for line in render_table(
        ("策略", "账本", "资金池", "记录数", "费用", "最后现金", "最后保证金"),
        rows,
        indent="  ",
        aligns=("left", "left", "left", "right", "right", "right", "right"),
        max_widths=(20, 22, 22, 8, 14, 16, 16),
    ):
        click.echo(line)


def _print_group_detail_result(state, args: tuple[str, ...]) -> None:
    data = _require_last_result(state)
    group_name = _arg_value(args, "--group-name")
    if not group_name:
        raise click.ClickException("detail 需要 --group-name NAME")
    group = _result_group_for_name(data, group_name)
    if not group:
        raise click.ClickException(f"最近一次结果中找不到策略: {group_name}")
    payload = _group_detail_payload(state, data, group)
    detail = client_from_config().group_detail(payload).get("detail") or {}
    product_analysis = detail.get("product_analysis") or {}
    level = (_arg_value(args, "--level") or product_analysis.get("default_level") or "products").lower()
    if level in {"product", "products"}:
        analysis = (product_analysis.get("by_level") or {}).get("products") or product_analysis
        title = "产品层级贡献"
    elif level in {"contract", "contracts"}:
        analysis = (product_analysis.get("by_level") or {}).get("contracts") or product_analysis
        title = "合约层级贡献"
    else:
        raise click.ClickException("--level 只能是 product 或 contract")
    rows = []
    for row in list(analysis.get("rows") or [])[:20]:
        product = row.get("product") or {}
        product_label = _product_display(product)
        fee = product.get("fee") or {}
        market_rule = row.get("market_rule") or {}
        rows.append((
            product_label,
            _pct(_float(row.get("gross_contribution"))),
            str(row.get("active_period_count") or ""),
            _fmt_optional(fee.get("open")),
            _fmt_optional(fee.get("close_today")),
            _fmt_optional(market_rule.get("multiplier")),
            _fmt_optional(market_rule.get("margin_ratio")),
        ))
    click.echo(f"{group_name} · {title}")
    for line in render_table(
        ("产品", "gross贡献", "活跃期", "开仓费", "平今费", "乘数", "保证金率"),
        rows,
        indent="  ",
        aligns=("left", "right", "right", "right", "right", "right", "right"),
        max_widths=(32, 12, 8, 10, 10, 8, 10),
    ):
        click.echo(line)
    concentration = []
    if analysis.get("top1_positive_contribution_ratio") is not None:
        concentration.append(f"top1正贡献占比={_pct(_float(analysis.get('top1_positive_contribution_ratio')))}")
    if analysis.get("top3_positive_contribution_ratio") is not None:
        concentration.append(f"top3正贡献占比={_pct(_float(analysis.get('top3_positive_contribution_ratio')))}")
    if concentration:
        click.echo("  " + " · ".join(concentration))


def _print_group_ranking_result(state, args: tuple[str, ...]) -> None:
    data = _require_last_result(state)
    product_path_selection_id = str(data.get("product_path_selection_id") or "")
    if not product_path_selection_id:
        raise click.ClickException("最近一次结果没有 product_path_selection_id，无法请求排序分析")
    detail = client_from_config().group_ranking_detail({
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
    }).get("detail") or {}
    rows = []
    for key, value in sorted(detail.items()):
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append((key, _fmt_optional(value)))
    click.echo("分组排序能力摘要")
    if rows:
        for line in render_table(("字段", "值"), rows, indent="  ", max_widths=(32, 48)):
            click.echo(line)
    else:
        click.echo("  后端返回了排序分析对象；当前 CLI 只显示标量摘要，可用 web overlay 查看完整图表。")


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

    counts_only = "--counts-only" in args
    limit_raw = _arg_value(args, "--limit")
    limit = int(limit_raw) if limit_raw else 20
    ledger_filter = _arg_value(args, "--ledger")
    cash_pool_filter = _arg_value(args, "--cash-pool") or _arg_value(args, "--cash_pool")

    filtered_groups = []
    total_records = 0
    for group in groups:
        if not isinstance(group, dict):
            continue
        records = list(group.get("records") or [])
        if ledger_filter:
            records = [record for record in records if _record_ledger_id(record) == ledger_filter]
        if cash_pool_filter:
            records = [record for record in records if _record_cash_pool_id(record) == cash_pool_filter]
        group_copy = dict(group)
        group_copy["records"] = records
        filtered_groups.append(group_copy)
        total_records += len(records)
    groups = filtered_groups
    if ledger_filter or cash_pool_filter:
        filters = []
        if ledger_filter:
            filters.append(f"ledger={ledger_filter}")
        if cash_pool_filter:
            filters.append(f"cash_pool={cash_pool_filter}")
        click.echo(f"订单流: records={total_records} ({', '.join(filters)})")
    else:
        click.echo(f"订单流: records={result.get('record_count', 0)}")

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
        show_fee = (_arg_value(args, "--show") == "fee") or ("--show-fee" in args)
        if show_fee:
            detail_rows = [
                (
                    str(r.get("timestamp") or ""),
                    str(r.get("product") or ""),
                    str(r.get("step") or ""),
                    f"{_float(r.get('quantity')):.4g}",
                    "" if r.get("effective_price") is None else f"{_float(r.get('effective_price')):.6g}",
                    f"{_float(r.get('fee_cost')):,.2f}",
                    _record_ledger_id(r),
                    _record_cash_pool_id(r),
                    _fmt_detail_number(r, "cash_after"),
                    _fmt_detail_number(r, "margin_after"),
                    str(r.get("status") or ""),
                )
                for r in shown
            ]
            headers = ("时间", "品种", "步骤", "数量", "成交价", "费用", "账本", "资金池", "现金", "保证金", "状态")
            widths = (24, 16, 14, 10, 10, 12, 16, 16, 14, 14, 10)
            aligns = ("left", "left", "left", "right", "right", "right", "left", "left", "right", "right", "left")
        else:
            detail_rows = [
                (
                    str(r.get("timestamp") or ""),
                    str(r.get("product") or ""),
                    str(r.get("step") or ""),
                    str(r.get("label") or ""),
                    f"{_float(r.get('quantity')):.4g}",
                    "" if r.get("effective_price") is None else f"{_float(r.get('effective_price')):.6g}",
                    str(r.get("status") or ""),
                    str(r.get("reject_reason") or ""),
                )
                for r in shown
            ]
            headers = ("时间", "品种", "步骤", "说明", "数量", "成交价", "状态", "拒绝原因")
            widths = (24, 14, 14, 16, 10, 10, 10, 20)
            aligns = ("left", "left", "left", "left", "right", "right", "left", "left")
        for line in render_table(headers, detail_rows, indent="  ", aligns=aligns, max_widths=widths):
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


def _selected_result_groups(data: dict[str, Any], group_name: str = "") -> list[dict[str, Any]]:
    groups = [group for group in (data.get("groups") or []) if isinstance(group, dict)]
    if not group_name:
        return groups
    group = _result_group_for_name(data, group_name)
    return [group] if group else []


def _result_group_for_name(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        keys = {
            str(group.get("name") or ""),
            str(group.get("id") or ""),
            str(group.get("group_id") or ""),
        }
        if name in keys:
            return group
    return None


def _group_equity_curve(group: dict[str, Any]) -> list[float]:
    values = group.get("total_equity") or group.get("equity_curve") or []
    if isinstance(values, dict):
        values = list(values.values())
    return [_float(value) for value in values]


def _fetch_order_flow_for_group(state, data: dict[str, Any], group_name: str) -> list[dict[str, Any]]:
    group_id = _group_id_for_name(data, group_name)
    if not group_id:
        return []
    result = client_from_config().group_order_flow({
        "page_uuid": state.page_uuid,
        "group_id": group_id,
    })
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    if not groups:
        return []
    return list(groups[0].get("records") or [])


def _attribution_bucket(record: dict[str, Any], by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return _record_ledger_id(record) or "(未记录账本)"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return _record_cash_pool_id(record) or "(未记录资金池)"
    if by in {"product", "products", "contract", "contracts"}:
        return str(record.get("product") or record.get("instrument") or "")
    return ""


def _attribution_table_title(by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return "费用按账本聚合"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return "费用按资金池聚合"
    return "费用按产品/合约聚合"


def _attribution_table_header(by: str) -> str:
    if by in {"ledger", "ledgers"}:
        return "账本"
    if by in {"cash-pool", "cash_pool", "cashpool"}:
        return "资金池"
    return "产品/合约"


def _record_ledger_id(record: dict[str, Any]) -> str:
    return _record_detail_value(record, "ledger_id")


def _record_cash_pool_id(record: dict[str, Any]) -> str:
    return _record_detail_value(record, "cash_pool_id")


def _record_detail_value(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value not in (None, ""):
        return str(value)
    details = record.get("details")
    if isinstance(details, dict):
        value = details.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _group_detail_payload(state, data: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    product_path_selection_id = str(
        group.get("product_path_selection_id")
        or data.get("product_path_selection_id")
        or ""
    )
    if not product_path_selection_id:
        raise click.ClickException("最近一次结果没有 product_path_selection_id，无法请求组内详情")
    return {
        "page_uuid": state.page_uuid,
        "product_path_selection_id": product_path_selection_id,
        "group_index": group.get("group_index", group.get("groupIndex", 1)),
        "group_id": group.get("group_id") or group.get("id"),
    }


def _product_display(product: Any) -> str:
    if not isinstance(product, dict):
        return str(product or "")
    name = str(product.get("name") or product.get("product") or product.get("display_ref") or "")
    desc = str(product.get("desc") or product.get("description") or "")
    if desc and desc not in name:
        return f"{name}({desc})"
    return name


def _float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_optional(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _fmt_detail_number(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if value is None and isinstance(record.get("details"), dict):
        value = record["details"].get(key)
    if value is None:
        return ""
    return f"{_float(value):,.2f}"


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
    click.echo("  factortester backtest results attribution --group-name <策略名> --by product")
    click.echo("  factortester backtest results detail --group-name <策略名>")
    click.echo("  factortester backtest results ranking")
    click.echo("  factortester backtest results snapshot --index 1")
    click.echo("  factortester backtest results order-flow --group-name <策略名> --show fee")


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
