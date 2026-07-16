"""Factor-evaluation CLI controller."""

from __future__ import annotations

import click

from tools.cli.core.context import ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.core.context import client_from_config
from tools.cli.modules.backtest.run_output import _multi_series_chart
from tools.cli.modules.single_factor_analysis_shared import (
    apply_local_settings,
    base_payload,
    parse_run_selectors,
)
from tools.cli.modules.research_metadata import attach_research_metadata
from tools.cli.state import load_state, save_state
from tools.cli.table import render_table


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
    client = client_from_config()
    result = client.run_factor_evaluation(payload)
    _print_result(result)
    _save_factor_evaluation_research_result(client, state, payload, result)
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
    rows = []
    for item in (result.get("series") or [])[:5]:
        product = item.get("product")
        desc = item.get("desc")
        values = item.get("values") or []
        rows.append((product or "", desc or "", len(values)))
    for line in render_table(("产品", "描述", "点数"), rows, indent="  ", aligns=("left", "left", "right"), max_widths=(18, 32, 10)):
        click.echo(line)
    series_rows = _result_series(result.get("series") or [])
    if series_rows:
        click.echo("因子序列图:")
        for line in _multi_series_chart(series_rows, width=72, height=14, title="因子序列", ylabel="因子"):
            click.echo("  " + line)


def _result_series(items) -> list[tuple[str, list[float], bool]]:
    out: list[tuple[str, list[float], bool]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        values = _numeric_values(item.get("values"))
        if not values:
            continue
        product = str(item.get("product") or item.get("name") or "因子")
        desc = str(item.get("desc") or "").strip()
        label = f"{product}({desc})" if desc else product
        out.append((label, values, False))
    return out


def _numeric_values(value) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            if item is not None:
                out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _save_factor_evaluation_research_result(client, state, payload: dict, result: dict) -> None:
    try:
        factor = result.get("factor") if isinstance(result.get("factor"), dict) else {}
        factor_alias = str(
            factor.get("alias")
            or factor.get("name")
            or payload.get("factor_alias")
            or payload.get("factor")
            or ""
        )
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        start_date = str(settings.get("start_date") or "")
        end_date = str(settings.get("end_date") or "")
        if not factor_alias or not start_date or not end_date:
            return
        series = [item for item in (result.get("series") or []) if isinstance(item, dict)]
        counts = []
        product_metrics = []
        for item in series:
            values = _numeric_values(item.get("values"))
            counts.append(len(values))
            product_metrics.append({
                "product": item.get("product") or item.get("name"),
                "desc": item.get("desc") or "",
                "points": len(values),
                "first": values[0] if values else None,
                "last": values[-1] if values else None,
            })
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        product_selection = payload.get("product_path_selection")
        product_group = ""
        if isinstance(product_selection, dict):
            product_group = str(product_selection.get("label") or product_selection.get("name") or product_selection.get("product_group") or "")
        save_payload = {
            "ff_alias": str(payload.get("factor_family_alias") or state.factor_family or _factor_family_from_alias(factor_alias)),
            "factor_alias": factor_alias,
            "factor_source": str((state.page_settings or {}).get("factor_source") or ""),
            "product_group": product_group,
            "start_date": start_date,
            "end_date": end_date,
            "test_type": "factor_evaluation",
            "config": {"settings": settings, "paths": payload.get("paths") or []},
            "metrics": {
                "product_count": meta.get("product_count") if meta.get("product_count") is not None else len(series),
                "elapsed_ms": meta.get("elapsed_ms"),
                "series_count": len(series),
                "min_points": min(counts) if counts else 0,
                "max_points": max(counts) if counts else 0,
                "product_series": product_metrics,
            },
            "note": "auto-saved from factortester factor_evaluation run",
        }
        client.save_factor_research_run(attach_research_metadata(save_payload, settings=settings, extra=payload))
    except Exception as exc:
        click.echo(f"因子序列研究结果入库失败: {exc}", err=True)


def _factor_family_from_alias(factor_alias: str) -> str:
    return factor_alias.split("|", 1)[0] if "|" in factor_alias else factor_alias
