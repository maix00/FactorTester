"""Backtest compare command handlers."""

from __future__ import annotations

from collections.abc import Callable

import click

from tools.cli.modules.backtest import compare_payloads as compare_payload_helpers
from tools.cli.modules.backtest import compare_views as compare_view_formatter
from tools.cli.modules.backtest import results_commands as results_command_handlers


RunBacktest = Callable[..., None]


def print_compare_help() -> None:
    for line in compare_view_formatter.COMPARE_HELP_LINES:
        click.echo(line)


def handle_compare_command(
    state,
    args: tuple[str, ...],
    *,
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
    run_backtest: RunBacktest,
) -> None:
    if not args or args[0] in {"help", "--help", "-h"}:
        print_compare_help()
        return
    preset = args[0]
    if preset == "volume-capacity-margin":
        _run_volume_capacity_margin(
            state,
            volume_rate=volume_rate,
            verbose=verbose,
            run_backtest=run_backtest,
        )
        return
    if preset == "factor-grid":
        _run_factor_grid(
            state,
            factor_family=factor_family,
            n_values=n_values,
            f_values=f_values,
            product_groups=product_groups,
            rev=rev,
            top=top,
            liquidity_mode=liquidity_mode,
            participation_rate=participation_rate if participation_rate is not None else volume_rate,
            verbose=verbose,
            run_backtest=run_backtest,
        )
        return
    raise click.ClickException("compare 支持 preset: volume-capacity-margin, factor-grid")


def _run_volume_capacity_margin(
    state,
    *,
    volume_rate: float,
    verbose: bool,
    run_backtest: RunBacktest,
) -> None:
    if volume_rate <= 0:
        raise click.ClickException("--volume-rate 必须大于 0")
    payload, groups, ls_configs, scenarios = compare_payload_helpers.volume_capacity_margin_compare_payload(
        state,
        volume_rate=volume_rate,
    )
    click.echo("批量对比场景:")
    for scenario in scenarios:
        click.echo(f"  {scenario['label']}: {scenario['description']}")
    run_backtest(
        state,
        groups=groups,
        ls_configs=ls_configs,
        payload=payload,
        verbose=verbose,
        title="批量对比回测",
        show_topology=False,
    )
    print_compare_result_summary(state, scenarios)


def _run_factor_grid(
    state,
    *,
    factor_family: str,
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    product_groups: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
    participation_rate: float,
    verbose: bool,
    run_backtest: RunBacktest,
) -> None:
    payload, groups, ls_configs, scenarios = compare_payload_helpers.factor_grid_payload(
        state,
        factor_family=factor_family,
        n_values=n_values,
        f_values=f_values,
        product_groups=product_groups,
        rev=rev,
        liquidity_mode=liquidity_mode,
        participation_rate=participation_rate,
    )
    click.echo("因子参数/产品组批量研究:")
    for scenario in scenarios:
        click.echo(f"  {scenario['label']}: {scenario['description']}")
    run_backtest(
        state,
        groups=groups,
        ls_configs=ls_configs,
        payload=payload,
        verbose=verbose,
        title="因子参数网格回测",
        show_topology=False,
    )
    print_factor_grid_result_summary(state, scenarios, top=top)


def print_compare_result_summary(state, scenarios: list[dict[str, str]]) -> None:
    data = results_command_handlers.require_last_result(state)
    for line in compare_view_formatter.compare_result_summary_lines(data, scenarios):
        click.echo(line)


def print_factor_grid_result_summary(state, scenarios: list[dict[str, str]], *, top: int) -> None:
    data = results_command_handlers.require_last_result(state)
    for line in compare_view_formatter.factor_grid_result_summary_lines(data, scenarios, top=top):
        click.echo(line)
