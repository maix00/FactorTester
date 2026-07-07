"""Shared CLI presentation helpers."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.modules.keys import public_module_key
from tools.cli.state import BACKTEST_SPACE, SINGLE_FACTOR_BACKTEST_SPACE, CliState


def module_lines(modules: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for module in modules:
        key = public_module_key(str(module.get("key", "")))
        label = module.get("label", key)
        kind = module.get("kind", "module")
        marker = " +" if module.get("has_children") else ""
        lines.append(f"- [{kind}] {key}: {label}{marker}")
    return lines


def print_home_welcome() -> None:
    click.echo("欢迎使用 FactorTester CLI")
    click.echo("常用操作:")
    click.echo("  factortester list                         查看当前层级可进入模块")
    click.echo("  factortester single_factor_test           进入单因子测试")
    click.echo("  factortester products                     进入产品管理")
    click.echo("  factortester custom_factors               进入因子管理")
    click.echo("  factortester <module> --help              查看模块命令")
    click.echo("Agent 因子研究:")
    click.echo("  安装/使用 longbridge-quant、quantitative-research skill")
    click.echo("  阅读 tools/cli/docs/factor-research-cli.md 查看 CLI 接入流程")


def print_single_factor_family_welcome(state: CliState) -> None:
    click.echo("单因子家族测试")
    click.echo(f"已选择 factor_family: {state.factor_family}")
    click.echo("下一步: factortester single_factor_test list 查看测试模块；例如 factortester backtest 进入回测。")


def print_backtest_welcome(state: CliState) -> None:
    click.echo("回测")
    click.echo(f"草稿空间: {_backtest_scope_label(state)}")
    click.echo("设置草稿:")
    if state.backtest_local_settings:
        click.echo("  local-settings:")
        for key, value in state.backtest_local_settings.items():
            click.echo(f"    {key}: {value}")
    else:
        click.echo("  local-settings: （空）")
    if state.backtest_groups:
        click.echo("  groups:")
        for index, group in enumerate(state.backtest_groups, start=1):
            label = group.get("name") or f"group-{index}"
            parts = [str(label)]
            if group.get("split_count") is not None:
                parts.append(f"分组数={group['split_count']}")
            if group.get("group_index") is not None:
                parts.append(f"分组序号={group['group_index']}")
            product_path = _product_path_label(group.get("product_path_selection"))
            if product_path:
                parts.append(f"产品路径={product_path}")
            if group.get("factor"):
                parts.append(f"因子={group['factor']}")
            click.echo(f"    {index}. " + " · ".join(parts))
    else:
        click.echo("  groups: （空）")
    if state.backtest_ls_configs:
        click.echo("  long-short:")
        for index, config in enumerate(state.backtest_ls_configs, start=1):
            long_group = config.get("long_group") or {}
            short_group = config.get("short_group") or {}
            click.echo(
                f"    {index}. {config.get('name') or f'ls-{index}'} · "
                f"多头={long_group.get('name') or long_group.get('id')} · "
                f"空头={short_group.get('name') or short_group.get('id')}"
            )
    else:
        click.echo("  long-short: （空）")
    strategy_book = getattr(state, "backtest_strategy_book", {}) or {}
    if strategy_book:
        strategies = strategy_book.get("strategies") if isinstance(strategy_book, dict) else {}
        click.echo(f"  strategy-book: {len(strategies or {})} strategy 映射")
    else:
        click.echo("  strategy-book: StrategyBookSimple（每策略一个私有 ledger/cash pool）")
    ledger_configs = getattr(state, "backtest_ledger_configs", {}) or {}
    if ledger_configs:
        click.echo(f"  ledger-configs: {len(ledger_configs)} ledger")
    else:
        click.echo("  ledger-configs: （空）")
    command_prefix = "factortester backtest" if state.active_backtest_space == BACKTEST_SPACE else "factortester"
    click.echo("参数示例:")
    click.echo(f"  {command_prefix} local-settings allocation_mode=equal_notional")
    click.echo(f"  {command_prefix} strategy-book ledger --strategy A1 --ledger shared --cash-pool pool-main")
    click.echo(f"  {command_prefix} ledger-config --ledger shared --fee-mode auto --margin-mode auto")
    click.echo(f"  {command_prefix} group --add --group-name A1 --split-count 5 --group-index 1 --factor-family SgCCS")
    click.echo("  factortester backtest --run" if state.active_backtest_space == BACKTEST_SPACE else "  factortester group --run")
    click.echo("下一步: factortester backtest --help 查看回测命令。")


def print_location_welcome(state: CliState) -> None:
    if state.current_parent == "single_factor_family_test":
        print_single_factor_family_welcome(state)
        return
    if state.current_parent == "group_test":
        print_backtest_welcome(state)
        return
    if state.current_parent == "ic_test":
        from tools.cli.modules.ic_test.controller import print_ic_welcome

        print_ic_welcome(state)
        return
    if state.current_parent == "factor_evaluation":
        from tools.cli.modules.factor_evaluation.controller import print_factor_evaluation_welcome

        print_factor_evaluation_welcome(state)
        return
    if state.current_parent == "factor_type_analysis":
        from tools.cli.modules.factor_type_analysis.controller import print_factor_type_analysis_welcome

        print_factor_type_analysis_welcome(state)
        return
    click.echo(f"已进入: {state.location_label}")
    click.echo("下一步: factortester <module> list 或 factortester <module> --help 查看下一层。")


def _product_path_label(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("product_group") or value.get("label") or value.get("name") or value.get("product_path_selection_id") or "")
    return str(value or "")


def _backtest_scope_label(state: CliState) -> str:
    if state.active_backtest_space == SINGLE_FACTOR_BACKTEST_SPACE:
        family = f" · {state.factor_family}" if state.factor_family else ""
        return f"single_factor_test/backtest{family}"
    return "backtest"
