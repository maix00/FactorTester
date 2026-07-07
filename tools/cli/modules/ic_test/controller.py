"""IC-test CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.field_help import render_settings_help
from tools.cli.field_store import FieldStore
from tools.cli.modules.backtest.controller import _parse_raw_settings
from tools.cli.modules.backtest.shared.selectors import (
    FactorSelector,
    ProductGroupSelector,
    parse_add_group_selectors,
    resolve_factor_family_selector,
    selection_label,
)
from tools.cli.modules.single_factor_analysis_shared import parse_factor_grid_options, factor_grid_items
from tools.cli.modules.products.controller import product_group_selection
from tools.cli.modules.backtest.run_output import _multi_series_chart
from tools.cli.state import load_state, save_state
from tools.cli.table import render_table


SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}
SELECTOR_HELP_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}
IC_TEST_KEY = "ic_test"


@click.group("ic_test", invoke_without_command=True, context_settings=SELECTOR_CONTEXT)
@click.option("--run", is_flag=True, help="运行当前 IC 配置列表。")
@click.option("--verbose", is_flag=True, help="打印流式进度事件。")
@click.pass_context
@friendly_errors
def ic_test(ctx: click.Context, run: bool, verbose: bool) -> None:
    """IC 测试控制界面。

    \b
    常用命令:
      factortester single_factor_test --factor-family SgCCS ic_test
      factortester ic_test local-settings --ic-correlation rank --ic-lag 0
      factortester ic_test config --add --name 日盘RankIC --factor-family SgCCS --product-group 中国期货日盘 --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'
      factortester ic_test grid --factor-family SgCCS --product-group 中国期货日盘 --n 1m --n 2m
      factortester ic_test config list
      factortester ic_test --run
    """
    if ctx.invoked_subcommand is not None:
        return
    state = load_state()
    enter_ic_test_state(state)
    save_state(state)
    if run:
        _run_ic_configs(state, verbose=verbose)
        return
    _print_ic_welcome(state)


@ic_test.command("local-settings", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def local_settings(ctx: click.Context) -> None:
    """配置 IC 测试 local-settings。"""
    state = load_state()
    if state.current_parent != IC_TEST_KEY:
        enter_ic_test_state(state)
    args = tuple(ctx.args)
    show_help = "--help" in args or "-h" in args
    args = tuple(arg for arg in args if arg not in {"--help", "-h"})
    if args:
        values = _parse_raw_settings(args)
        _validate_ic_settings(state, values)
        state.ic_test_local_settings.update(values)
    if show_help:
        _print_ic_settings_help(state)
        return
    save_state(state)
    click.echo("已更新 IC local-settings")
    _print_ic_welcome(state)


@ic_test.command("config", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def config(ctx: click.Context) -> None:
    """管理 IC 配置列表。"""
    state = load_state()
    if state.current_parent != IC_TEST_KEY:
        enter_ic_test_state(state)
    args = tuple(ctx.args)
    verbose = "--verbose" in args
    args = tuple(arg for arg in args if arg != "--verbose")
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_config_help()
        return
    if args[0] in {"list", "ls"}:
        _print_config_list(state)
        return
    if "--run" in args:
        configs = _selected_configs(state, args, default_all=True)
        _run_ic_configs(state, configs=configs, verbose=verbose)
        return
    if "--describe" in args:
        for item in _selected_configs(state, args):
            _print_config(item)
        return
    if "--add" not in args:
        raise click.ClickException("ic_test config 需要动作：list、--add、--describe 或 --run")
    clean_args = tuple(arg for arg in args if arg != "--add")
    selectors = parse_add_group_selectors(clean_args)
    extra_values = _settings_after_selector_args(clean_args)
    _append_ic_config(state, selectors=selectors, extra_values=extra_values)
    save_state(state)
    click.echo("新增 IC 配置")
    _print_config(state.ic_test_configs[-1])


@ic_test.command("grid", context_settings=SELECTOR_CONTEXT)
@click.option("--verbose", is_flag=True, help="打印流式进度事件。")
@click.pass_context
@friendly_errors
def grid(ctx: click.Context, verbose: bool) -> None:
    """批量运行 IC 测试。"""
    state = load_state()
    if state.current_parent != IC_TEST_KEY:
        enter_ic_test_state(state)
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login")
    args = tuple(ctx.args)
    if not args or args[0] in {"help", "--help", "-h"}:
        _print_grid_help()
        return
    default_factor_family = str(state.factor_family or state.page_settings.get("factor_family") or "")
    options = parse_factor_grid_options(tuple(arg for arg in args if arg != "--verbose"), default_factor_family=default_factor_family)
    client = client_from_config()
    rows = []
    for item in factor_grid_items(state, options=options, settings=state.ic_test_local_settings, client=client):
        settings = dict(item["settings"])
        payload = {
            **item["payload_base"],
            "factors": [{"alias": item["factor"]}],
            "settings": settings,
            "ic_correlation": settings.get("ic_correlation", "rank"),
            "ic_lag": settings.get("ic_lag", 0),
            "ic_decay_lags": list(range(1, int(settings.get("ic_decay_lags") or 5) + 1)),
            "rolling_window": settings.get("rolling_window"),
        }
        click.echo(f"IC grid: {item['factor']} · {item['product_group']}")
        result = None
        for event in client.run_ic_test_stream(payload):
            event_name = str(event.get("event") or "message")
            data = event.get("data")
            if event_name == "error":
                message = data.get("error") if isinstance(data, dict) else data
                raise click.ClickException(f"IC 测试失败: {message}")
            if event_name == "progress" and verbose and isinstance(data, dict):
                click.echo(f"  进度: {data.get('phase')} {data.get('completed')}/{data.get('total')}")
            if event_name == "result" and isinstance(data, dict):
                result = data
        summary = _ic_summary_values(result or {}, item["factor"])
        rows.append((
            item["factor"],
            item["product_group"],
            summary.get("mean"),
            summary.get("std"),
            summary.get("ir"),
            summary.get("t_stat"),
            summary.get("n"),
            summary.get("ac1"),
            summary.get("half_life"),
        ))
    save_state(state)
    _print_grid_rows(rows, top=int(options.get("top") or 12))


def enter_ic_test_state(state) -> None:
    if state.current_parent == "single_factor_family_test":
        ensure_child_available(state.current_parent, IC_TEST_KEY)
    else:
        ensure_child_available("single_factor_family_test", IC_TEST_KEY)
    state.enter(IC_TEST_KEY)


def _print_ic_welcome(state) -> None:
    click.echo("IC 测试")
    click.echo("设置草稿:")
    if state.ic_test_local_settings:
        click.echo("  local-settings:")
        for key, value in state.ic_test_local_settings.items():
            click.echo(f"    {key}: {value}")
    else:
        click.echo("  local-settings: （空）")
    if state.ic_test_configs:
        click.echo("  configs:")
        for item in state.ic_test_configs:
            click.echo("    " + _config_summary(item))
    else:
        click.echo("  configs: （空）")
    click.echo("下一步: factortester ic_test config --add ... 或 factortester ic_test --run")


def print_ic_welcome(state) -> None:
    _print_ic_welcome(state)


def _print_config_help() -> None:
    click.echo("ic_test config 命令")
    click.echo("  list / ls                         列出 IC 配置")
    click.echo("  --add --name NAME ...             新增 IC 配置")
    click.echo("  --name NAME --describe            查看配置")
    click.echo("  --name NAME --run                 运行选中配置")
    click.echo("")
    click.echo("示例:")
    click.echo("  factortester ic_test config --add --name 日盘RankIC --factor-family SgCCS --product-group 中国期货日盘 --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'")


def _print_grid_help() -> None:
    click.echo("ic_test grid 命令")
    click.echo("  --factor-family NAME [--product-group NAME] [--n 1m --n 2m] [--f 1m] [--rev] [--no-rev] [--top 12]")
    click.echo("")
    click.echo("说明: grid = 因子参数 × 产品组 × 方向。产品组和方向可重复传入；方向不传默认使用 $Rev。")


def _stores_for_ic(state, client=None) -> tuple[FieldStore, FieldStore]:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    ic_store = FieldStore.from_manifest(client.manifest(IC_TEST_KEY), values=state.ic_test_local_settings, parent=page_store)
    return page_store, ic_store


def _validate_ic_settings(state, values: dict[str, Any]) -> None:
    _, store = _stores_for_ic(state)
    unknown = [key for key in values if key not in store.defaults]
    if unknown:
        raise click.ClickException("IC local-settings 包含未注册字段: " + ", ".join(sorted(unknown)))
    for key, value in values.items():
        try:
            store.validate_value(key, value)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None


def _print_ic_settings_help(state) -> None:
    _, store = _stores_for_ic(state)
    for line in render_settings_help(store, title="IC 设置上下文"):
        click.echo(line)


def _append_ic_config(state, *, selectors, extra_values: dict[str, Any] | None = None) -> None:
    client = client_from_config()
    page_store, ic_store = _stores_for_ic(state, client)
    _ensure_ic_candidates(state, client, page_store, ic_store)
    product_selection = _resolve_product_group(state, selectors.product_group)
    factor_family = resolve_factor_family_selector(state, client, selectors)
    factor_alias = _resolve_factor(state, client, selectors.factor, factor_family=factor_family, product_group_label=selection_label(product_selection))
    if not product_selection:
        raise click.ClickException("新增 IC 配置缺少产品路径；请传 --product-group")
    if not factor_alias:
        raise click.ClickException("新增 IC 配置缺少因子；请传 --factor")
    state.page_settings = page_store.to_payload()
    state.ic_test_local_settings = ic_store.to_payload()
    item: dict[str, Any] = {
        "id": f"ic-{len(state.ic_test_configs) + 1}",
        "name": selectors.group_name or f"IC-{len(state.ic_test_configs) + 1}",
        "factor_family_alias": factor_family,
        "product_path_selection": product_selection,
        "factor": factor_alias,
    }
    if extra_values:
        item["settings"] = dict(extra_values)
    state.ic_test_configs.append(item)


def _ensure_ic_candidates(state, client, page_store: FieldStore, ic_store: FieldStore) -> None:
    if "product_path_candidates" in page_store.defaults and not page_store.effective("product_path_candidates"):
        groups = client.list_candidates("product_path_candidates")
        page_store.set("product_path_candidates", groups)
    state.page_settings = page_store.to_payload()
    state.ic_test_local_settings = ic_store.to_payload()


def _resolve_product_group(state, selector: ProductGroupSelector) -> Any:
    if selector.mode == "add" or selector.paths:
        if not selector.name:
            raise click.ClickException("现场新增产品路径候选时必须传 --product-group add --name NAME")
        if not selector.paths:
            raise click.ClickException("现场新增产品路径候选时必须至少传一个 --path")
        selection = {
            "product_path_selection_id": f"manual:{selector.name}",
            "id": f"manual:{selector.name}",
            "label": selector.name,
            "name": selector.name,
            "paths": list(selector.paths),
            "selected_paths": list(selector.paths),
            "source_type": "runtime_manual_path_group",
        }
        candidates = list(state.ic_test_local_settings.get("product_path_candidates") or [])
        candidates.append(selection)
        state.ic_test_local_settings["product_path_candidates"] = candidates
        return selection
    candidates = list(state.page_settings.get("product_path_candidates") or []) + list(state.ic_test_local_settings.get("product_path_candidates") or [])
    if selector.mode == "from_candidates" or selector.name:
        for item in candidates:
            selected = product_group_selection(item)
            keys = {
                str(selected.get("id") or ""),
                str(selected.get("product_path_selection_id") or ""),
                str(selected.get("name") or ""),
                str(selected.get("label") or ""),
                str(selected.get("product_group") or ""),
            }
            if selector.name in keys:
                return selected
        return {"product_path_selection_id": selector.name, "label": selector.name}
    return None


def _resolve_factor(state, client, selector: FactorSelector, *, factor_family: str, product_group_label: str) -> str:
    if selector.mode == "alias" or selector.alias:
        return selector.alias
    if selector.mode == "add" or selector.params:
        if not factor_family:
            raise click.ClickException("现场新增因子参数时必须传 --factor-family")
        current = client.factor_library_configs(factor_family, product_group=product_group_label)
        rows = []
        for user in current.get("users") or []:
            if user.get("editable"):
                rows = list((user.get("config") or {}).get("params_list") or [])
                break
        from tools.cli.modules.custom_factors.controller import parse_key_value

        rows.append(dict(parse_key_value(item) for item in selector.params))
        data = client.save_factor_library_config(factor_family, product_group=product_group_label, params_list=rows)
        factors = list(data.get("factors") or [])
        factor = str((factors[-1] if factors else {}).get("factor_alias") or "")
        if not factor:
            raise click.ClickException("新增因子参数成功但后端未返回 factor_alias")
        return factor
    if selector.mode == "from_candidates":
        overview = client.factor_library_overview(factor_family=factor_family, product_group=selector.product_group or product_group_label)
        factors = list(overview.get("factors") or [])
        state.page_settings["factor_candidates"] = factors
        if selector.index is not None:
            if selector.index < 1 or selector.index > len(factors):
                raise click.ClickException(f"因子候选 index 超出范围: {selector.index}")
            return str(factors[selector.index - 1].get("factor_alias") or factors[selector.index - 1].get("alias") or "")
        if factors:
            return str(factors[0].get("factor_alias") or factors[0].get("alias") or "")
        raise click.ClickException("因子候选列表为空")
    return ""


def _settings_after_selector_args(args: tuple[str, ...]) -> dict[str, Any]:
    selector_options = {
        "--add", "--name", "--group-name", "--group_name", "--factor-family", "--factor_family",
        "--factor", "--alias", "--from-candidates", "--index", "--factor-product-group",
        "--product-group", "--product-path-candidates", "--product-path", "--product_path",
        "--product-path-name", "--product_path_name", "--product-path-path", "--product_path_path",
        "--path", "--param", "--factor-param", "--factor_param",
    }
    out: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in selector_options:
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                i += 1
            continue
        out.append(token)
        if token.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
            out.append(args[i + 1])
            i += 2
        else:
            i += 1
    return _parse_raw_settings(tuple(out)) if out else {}


def _selected_configs(state, args: tuple[str, ...], *, default_all: bool = False) -> list[dict[str, Any]]:
    names = _names_from_args(args)
    if not names:
        if default_all:
            return list(state.ic_test_configs)
        raise click.ClickException("请用 --name 选择 IC 配置")
    selected = []
    for name in names:
        for item in state.ic_test_configs:
            if name in {str(item.get("name") or ""), str(item.get("id") or "")}:
                selected.append(item)
                break
        else:
            raise click.ClickException(f"找不到 IC 配置: {name}")
    return selected


def _names_from_args(args: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--name":
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise click.ClickException("--name 缺少参数")
            names.append(args[i + 1])
            i += 2
            continue
        i += 1
    return names


def _print_config_list(state) -> None:
    click.echo("IC 配置列表")
    if not state.ic_test_configs:
        click.echo("  （空）")
        return
    rows = [
        (
            item.get("name") or item.get("id") or "",
            selection_label(item.get("product_path_selection")) or "（未设置）",
            item.get("factor") or "（未设置）",
        )
        for item in state.ic_test_configs
    ]
    for line in render_table(("名称", "产品路径", "因子"), rows, indent="  ", max_widths=(20, 20, 42)):
        click.echo(line)


def _print_config(item: dict[str, Any]) -> None:
    click.echo(_config_summary(item))
    if item.get("settings"):
        click.echo(f"  settings: {item['settings']}")


def _config_summary(item: dict[str, Any]) -> str:
    return (
        f"{item.get('name') or item.get('id')} · "
        f"产品路径={selection_label(item.get('product_path_selection')) or '（未设置）'} · "
        f"因子={item.get('factor') or '（未设置）'}"
    )


def _run_ic_configs(state, *, configs: list[dict[str, Any]] | None = None, verbose: bool = False) -> None:
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login 以创建页面上下文")
    configs = configs if configs is not None else list(state.ic_test_configs)
    if not configs:
        raise click.ClickException("没有可运行的 IC 配置；请先用 factortester ic_test config --add 新增配置")
    click.echo(f"开始运行 IC 测试: configs={len(configs)}")
    client = client_from_config()
    for item in configs:
        click.echo(f"配置: {_config_summary(item)}")
        payload = _run_payload(state, item)
        result = None
        for event in client.run_ic_test_stream(payload):
            event_name = str(event.get("event") or "message")
            data = event.get("data")
            if event_name == "error":
                message = data.get("error") if isinstance(data, dict) else data
                raise click.ClickException(f"IC 测试失败: {message}")
            if event_name == "progress" and isinstance(data, dict):
                if verbose:
                    click.echo(f"  进度: {data.get('phase')} {data.get('completed')}/{data.get('total')}")
            if event_name == "result":
                result = data
    if isinstance(result, dict):
        _print_ic_result(result)
        _print_ic_factor_outputs(result)
    else:
        click.echo("  未收到 IC 结果")


def _run_payload(state, item: dict[str, Any]) -> dict[str, Any]:
    settings = dict(state.ic_test_local_settings)
    if isinstance(item.get("settings"), dict):
        settings.update(item["settings"])
    product_selection = item.get("product_path_selection") or {}
    factor = str(item.get("factor") or "")
    return {
        "page_uuid": state.page_uuid,
        "factor_family_alias": item.get("factor_family_alias") or state.factor_family,
        "product_path_selection_id": product_selection.get("product_path_selection_id") if isinstance(product_selection, dict) else "",
        "product_path_selection": product_selection,
        "paths": list(product_selection.get("paths") or product_selection.get("selected_paths") or []) if isinstance(product_selection, dict) else [],
        "factors": [{"alias": factor}],
        "settings": settings,
        "ic_correlation": settings.get("ic_correlation", "rank"),
        "ic_lag": settings.get("ic_lag", 0),
        "ic_decay_lags": list(range(1, int(settings.get("ic_decay_lags") or 5) + 1)),
        "rolling_window": settings.get("rolling_window"),
    }


def _print_ic_result(result: dict[str, Any]) -> None:
    stats = result.get("ic_stats") if isinstance(result.get("ic_stats"), dict) else {}
    rows = stats.get("rows") if isinstance(stats.get("rows"), list) else []
    columns = [str(col) for col in (stats.get("columns") or []) if col != "index"]
    click.echo("  IC 结果摘要:")
    if not rows or not columns:
        click.echo("    （无统计结果）")
        return
    table_rows: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = str(row.get("index") or "")
        for col in columns:
            value = row.get(col)
            table_rows.append((_ic_metric_label(index), col, _format_number(value)))
    for line in render_table(("指标", "因子", "值"), table_rows, indent="    ", aligns=("left", "left", "right"), max_widths=(12, 42, 14)):
        click.echo(line)


def _print_ic_factor_outputs(result: dict[str, Any]) -> None:
    factors = result.get("factors") if isinstance(result.get("factors"), list) else []
    for factor in factors[:3]:
        if not isinstance(factor, dict):
            continue
        label = str(factor.get("alias") or factor.get("factor_alias") or factor.get("name") or "IC")
        series = factor.get("ic_series") if isinstance(factor.get("ic_series"), dict) else {}
        values = _numeric_values(series.get("values") if isinstance(series, dict) else [])
        if values:
            click.echo(f"  IC 序列图: {label}")
            for line in _multi_series_chart([(label, values, False)], width=72, height=14, title="IC 序列", ylabel="IC"):
                click.echo("    " + line)
        rolling = factor.get("rolling_ic") if isinstance(factor.get("rolling_ic"), dict) else {}
        if rolling:
            _print_rolling_ic(rolling)
        decay = factor.get("ic_decay") if isinstance(factor.get("ic_decay"), list) else []
        if decay:
            _print_ic_decay(decay)


def _print_rolling_ic(rolling: dict[str, Any]) -> None:
    mean = _numeric_values(rolling.get("mean"))
    ir = _numeric_values(rolling.get("ir"))
    click.echo(f"  Rolling IC: window={rolling.get('window')}")
    rows = []
    if mean:
        rows.append(("mean", f"{mean[-1]:.6g}", len(mean)))
    if ir:
        rows.append(("ir", f"{ir[-1]:.6g}", len(ir)))
    for line in render_table(("序列", "末值", "点数"), rows, indent="    ", aligns=("left", "right", "right"), max_widths=(12, 14, 8)):
        click.echo(line)


def _print_ic_decay(decay: list[Any]) -> None:
    rows = []
    for item in decay[:8]:
        if not isinstance(item, dict):
            continue
        rows.append((
            item.get("lag"),
            _format_number(item.get("mean")),
            _format_number(item.get("ir")),
            item.get("n"),
        ))
    if rows:
        click.echo("  IC 衰减:")
        for line in render_table(("lag", "mean", "ir", "n"), rows, indent="    ", aligns=("right", "right", "right", "right"), max_widths=(6, 14, 14, 8)):
            click.echo(line)


def _ic_summary_values(result: dict[str, Any], alias: str) -> dict[str, Any]:
    stats = result.get("ic_stats") if isinstance(result.get("ic_stats"), dict) else {}
    rows = stats.get("rows") if isinstance(stats.get("rows"), list) else []
    summary: dict[str, Any] = {
        "mean": None,
        "std": None,
        "ir": None,
        "t_stat": None,
        "n": None,
        "ac1": None,
        "half_life": None,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        index = str(row.get("index") or "").lower()
        value = _first_numeric_stat(row, alias)
        if index in {"mean", "ic_mean"}:
            summary["mean"] = value
        elif index in {"std", "ic_std"}:
            summary["std"] = value
        elif index in {"ir", "ic_ir"}:
            summary["ir"] = value
        elif index == "t_stat":
            summary["t_stat"] = value
        elif index == "n":
            summary["n"] = value
        elif index == "ac1":
            summary["ac1"] = value
        elif index == "half_life":
            summary["half_life"] = value
    factor = _first_factor_result(result, alias)
    if factor:
        primary_lag = result.get("primary_ic_lag")
        decay_rows = [item for item in factor.get("ic_decay") or [] if isinstance(item, dict)]
        decay_match = None
        for item in decay_rows:
            if not isinstance(item, dict):
                continue
            if primary_lag is not None and item.get("lag") != primary_lag and int(item.get("lag") or -1) != int(primary_lag):
                continue
            decay_match = item
            break
        decay_match = decay_match or (decay_rows[0] if decay_rows else None)
        if decay_match:
            summary["n"] = summary["n"] if summary["n"] is not None else decay_match.get("n")
            summary["mean"] = summary["mean"] if summary["mean"] is not None else decay_match.get("mean")
            summary["ir"] = summary["ir"] if summary["ir"] is not None else decay_match.get("ir")
            summary["t_stat"] = summary["t_stat"] if summary["t_stat"] is not None else decay_match.get("t_stat")
    return summary


def _first_factor_result(result: dict[str, Any], alias: str) -> dict[str, Any] | None:
    for item in result.get("factors") or []:
        if not isinstance(item, dict):
            continue
        keys = {str(item.get("alias") or ""), str(item.get("factor_alias") or ""), str(item.get("name") or "")}
        if alias in keys or not alias:
            return item
    return None


def _first_numeric_stat(row: dict[str, Any], alias: str) -> float | None:
    for key in (alias, "IC", "RankIC", "rank_ic", "ic"):
        parsed = _float_or_none(row.get(key))
        if parsed is not None:
            return parsed
    for key, value in row.items():
        if key == "index":
            continue
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _print_grid_rows(rows: list[tuple[Any, ...]], *, top: int) -> None:
    def score(row: tuple[Any, ...]) -> tuple[bool, float, float]:
        ir = _float_or_none(row[4])
        mean = _float_or_none(row[2])
        return (ir is not None, abs(ir or 0.0), abs(mean or 0.0))

    rows = sorted(rows, key=score, reverse=True)
    if top > 0:
        rows = rows[:top]
    click.echo("")
    click.echo("IC grid 摘要")
    table_rows = [
        (
            factor,
            product_group,
            _format_number(mean),
            _format_number(std),
            _format_number(ir),
            _format_number(t_stat),
            _format_number(n),
            _format_number(ac1),
            _format_number(half_life),
        )
        for factor, product_group, mean, std, ir, t_stat, n, ac1, half_life in rows
    ]
    for line in render_table(
        ("因子", "产品组", "mean", "std", "IR", "t", "n", "AC1", "half-life"),
        table_rows,
        indent="  ",
        aligns=("left", "left", "right", "right", "right", "right", "right", "right", "right"),
        max_widths=(36, 18, 10, 10, 10, 10, 8, 8, 10),
    ):
        click.echo(line)


def _numeric_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            if item is None:
                continue
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _format_number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{float(value):.6g}"
    return str(value)


def _ic_metric_label(value: str) -> str:
    labels = {
        "mean": "IC Mean",
        "std": "IC Std",
        "IR": "IR",
        "ir": "IR",
        "t_stat": "t-stat",
        "max": "IC Max",
        "min": "IC Min",
        "ac1": "IC AC1",
        "half_life": "Half-Life",
        "n": "n",
    }
    return labels.get(value, value)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
