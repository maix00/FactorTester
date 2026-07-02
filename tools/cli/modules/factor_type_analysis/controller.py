"""Factor-type-analysis CLI controller."""

from __future__ import annotations

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.modules.single_factor_analysis_shared import (
    apply_local_settings,
    base_payload,
    parse_run_selectors,
)
from tools.cli.state import load_state, save_state


FACTOR_TYPE_ANALYSIS_KEY = "factor_type_analysis"
SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}


@click.group("factor_type_analysis", invoke_without_command=True, context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def factor_type_analysis(ctx: click.Context) -> None:
    """因子类型分析 CLI。

    \b
    常用命令:
      factortester single_factor_test --factor-family SgCCS factor_type_analysis
      factortester factor_type_analysis local-settings --correlation-method spearman
      factortester factor_type_analysis run --factor-family SgCCS --product-group 中国期货日盘 --factor --alias 'SgCCS|N:2m'
    """
    state = load_state()
    enter_factor_type_analysis_state(state)
    save_state(state)
    if ctx.invoked_subcommand is None:
        _print_welcome(state)


@factor_type_analysis.command("local-settings", context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def local_settings(ctx: click.Context) -> None:
    state = load_state()
    if apply_local_settings(
        state,
        application=FACTOR_TYPE_ANALYSIS_KEY,
        values_attr="factor_type_analysis_local_settings",
        args=tuple(ctx.args),
    ):
        return
    save_state(state)
    click.echo("已更新因子类型分析 local-settings")


@factor_type_analysis.command("run", context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def run(ctx: click.Context) -> None:
    state = load_state()
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login")
    selectors = parse_run_selectors(tuple(ctx.args))
    payload = base_payload(state, selectors=selectors, settings=state.factor_type_analysis_local_settings)
    summary = str(payload.pop("_summary"))
    click.echo("开始因子类型分析: " + summary)
    result = client_from_config().run_factor_type_analysis(payload)
    _print_result(result)
    save_state(state)


def enter_factor_type_analysis_state(state) -> None:
    if state.current_parent == "single_factor_family_test":
        ensure_child_available(state.current_parent, FACTOR_TYPE_ANALYSIS_KEY)
    else:
        ensure_child_available("single_factor_family_test", FACTOR_TYPE_ANALYSIS_KEY)
    state.enter(FACTOR_TYPE_ANALYSIS_KEY)


def print_factor_type_analysis_welcome(state) -> None:
    _print_welcome(state)


def _print_welcome(state) -> None:
    click.echo("因子类型分析")
    click.echo(f"local-settings: {state.factor_type_analysis_local_settings or '（空）'}")
    click.echo("下一步: factortester factor_type_analysis run --factor-family ... --product-group ... --factor ...")


def _print_result(result: dict) -> None:
    best = result.get("best_match") or result.get("best_category") or {}
    if isinstance(best, dict) and best:
        click.echo(
            "最佳类型: "
            + str(best.get("category_label") or best.get("category") or best.get("name") or "（未知）")
            + f" · corr={best.get('correlation')}"
        )
    categories = result.get("category_summary") or result.get("category_correlations") or []
    if isinstance(categories, dict):
        categories = [
            {"category": key, **(value if isinstance(value, dict) else {"correlation": value})}
            for key, value in categories.items()
        ]
    if categories:
        click.echo("类别相关性:")
        for item in list(categories)[:8]:
            if not isinstance(item, dict):
                continue
            name = item.get("category_label") or item.get("category") or item.get("name")
            click.echo(f"  {name}: {item.get('correlation')}")
    refs = result.get("reference_factors") or result.get("reference_correlations") or []
    if isinstance(refs, dict):
        refs = [
            {"key": key, **(value if isinstance(value, dict) else {"correlation": value})}
            for key, value in refs.items()
        ]
    if refs:
        click.echo("参照因子:")
        for item in list(refs)[:8]:
            if not isinstance(item, dict):
                continue
            click.echo(f"  {item.get('name') or item.get('key')}: {item.get('correlation')}")
