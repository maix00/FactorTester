"""Factor-evaluation CLI controller."""

from __future__ import annotations

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.core.context import client_from_config
from tools.cli.modules.single_factor_analysis_shared import (
    apply_local_settings,
    base_payload,
    parse_run_selectors,
)
from tools.cli.state import load_state, save_state


FACTOR_EVALUATION_KEY = "factor_evaluation"
SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}
SELECTOR_HELP_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}


@click.group("factor_evaluation", invoke_without_command=True, context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def factor_evaluation(ctx: click.Context) -> None:
    """因子评估 CLI。

    \b
    常用命令:
      factortester single_factor_test --factor-family SgCCS factor_evaluation
      factortester factor_evaluation local-settings --start-date 2026-01-01 --end-date 2026-01-31
      factortester factor_evaluation run --factor-family SgCCS --product-group add --name 单品种 --path Product/... --factor --alias 'SgCCS|N:2m'
    """
    state = load_state()
    enter_factor_evaluation_state(state)
    save_state(state)
    if ctx.invoked_subcommand is None:
        _print_welcome(state)


@factor_evaluation.command("local-settings", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def local_settings(ctx: click.Context) -> None:
    state = load_state()
    if apply_local_settings(
        state,
        application=FACTOR_EVALUATION_KEY,
        values_attr="factor_evaluation_local_settings",
        args=tuple(ctx.args),
    ):
        return
    save_state(state)
    click.echo("已更新因子评估 local-settings")


@factor_evaluation.command("run", context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def run(ctx: click.Context) -> None:
    state = load_state()
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login")
    selectors = parse_run_selectors(tuple(ctx.args))
    payload = base_payload(state, selectors=selectors, settings=state.factor_evaluation_local_settings)
    if not payload["paths"]:
        raise click.ClickException("因子评估需要具体 paths；请用 --product-group add --path ... 或选择带 paths 的产品组")
    click.echo("开始因子评估: " + str(payload.pop("_summary")))
    result = client_from_config().run_factor_evaluation(payload)
    _print_result(result)
    save_state(state)


def enter_factor_evaluation_state(state) -> None:
    if state.current_parent == "single_factor_family_test":
        ensure_child_available(state.current_parent, FACTOR_EVALUATION_KEY)
    else:
        ensure_child_available("single_factor_family_test", FACTOR_EVALUATION_KEY)
    state.enter(FACTOR_EVALUATION_KEY)


def print_factor_evaluation_welcome(state) -> None:
    _print_welcome(state)


def _print_welcome(state) -> None:
    click.echo("因子评估")
    click.echo(f"local-settings: {state.factor_evaluation_local_settings or '（空）'}")
    click.echo("下一步: factortester factor_evaluation run --factor-family ... --product-group ... --factor ...")


def _print_result(result: dict) -> None:
    factor = result.get("factor") or {}
    click.echo(f"因子: {factor.get('alias') or factor.get('name') or '（未知）'}")
    meta = result.get("meta") or {}
    if meta:
        click.echo(f"序列数: {meta.get('product_count')} · 耗时: {meta.get('elapsed_ms')}ms")
    for item in (result.get("series") or [])[:5]:
        product = item.get("product")
        desc = item.get("desc")
        values = item.get("values") or []
        click.echo(f"  {product}({desc}) points={len(values)}")
