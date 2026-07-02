"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import print_backtest_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.field_store import FieldStore
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY
from tools.cli.modules.products.controller import product_group_selection
from tools.cli.modules.backtest.shared.selectors import (
    AddGroupSelectors,
    parse_add_group_selectors,
    parse_add_group_selector_groups,
    resolve_factor_selector,
    resolve_product_group_selector,
    selection_label,
)
from tools.cli.state import load_state, save_state


SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}


@click.group("backtest", invoke_without_command=True, context_settings=SELECTOR_CONTEXT)
@click.option("--factor-family", "--factor_family", default="", help="从顶层进入回测时使用的因子家族。")
@click.option(
    "--config-local-settings",
    "--config_local_settings",
    "local_settings",
    multiple=True,
    metavar="KEY=VALUE",
    help="写入回测 local-settings 草稿，可重复传入。",
)
@click.option("--time-range", "--time_range", nargs=2, metavar="START END", help="写入 local-settings 的起止时间。")
@click.option("--add-group", "--add_group", is_flag=True, help="在当前回测草稿中新增一个分组。")
@click.option("--name", default="", help="新增分组名称。")
@click.option("--split-count", "--split_count", type=int, default=None, help="新增分组的分组数。")
@click.option("--group-index", "--group_index", type=int, default=None, help="新增分组的分组序号。")
@click.option("--factor", default="", help="新增分组使用的因子 alias；为空时走 FieldStore fallback。")
@click.option("--factor-param", "factor_params", multiple=True, metavar="KEY=VALUE", help="现场新增因子参数并选中，可重复传入。")
@click.option("--product-path", "--product_path", default="", help="新增分组使用的产品组 id/名称；为空时走 FieldStore fallback。")
@click.option("--product-path-name", "--product_path_name", default="", help="现场新增产品路径候选名称。")
@click.option("--product-path-path", "--product_path_path", "product_path_paths", multiple=True, help="现场新增产品路径，可重复传入。")
@click.pass_context
@friendly_errors
def backtest(
    ctx: click.Context,
    factor_family: str,
    local_settings: tuple[str, ...],
    time_range: tuple[str, str] | None,
    add_group: bool,
    name: str,
    split_count: int | None,
    group_index: int | None,
    factor: str,
    factor_params: tuple[str, ...],
    product_path: str,
    product_path_name: str,
    product_path_paths: tuple[str, ...],
) -> None:
    """Enter the generic backtest controller."""
    if ctx.invoked_subcommand is not None:
        return
    state = load_state()
    enter_backtest_state(state, factor_family=factor_family)
    _apply_local_settings(state, local_settings, time_range)
    if add_group:
        selectors = _legacy_selectors(
            name=name,
            split_count=split_count,
            group_index=group_index,
            factor=factor,
            factor_params=factor_params,
            product_path=product_path,
            product_path_name=product_path_name,
            product_path_paths=product_path_paths,
        )
        _append_group(
            state,
            selectors=selectors,
        )
    save_state(state)
    print_backtest_welcome(state)


@backtest.command("add-group", context_settings=SELECTOR_CONTEXT)
@click.pass_context
@friendly_errors
def add_group(
    ctx: click.Context,
) -> None:
    """Start a group-test add-group action in the backtest controller."""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state)
    selectors_list = parse_add_group_selector_groups(tuple(ctx.args))
    for selectors in selectors_list:
        _append_group(
            state,
            selectors=selectors,
        )
    save_state(state)
    click.echo(f"新增分组: {len(selectors_list)}")
    for group in state.backtest_groups[-len(selectors_list):]:
        _print_group(group)
    click.echo("下一步: 这些参数会进入 backtest/group-test 的配置草稿；运行接口接好后可直接提交。")


def enter_backtest_state(state, *, factor_family: str = "") -> None:
    if state.current_parent == "single_factor_family_test":
        if factor_family:
            state.factor_family = factor_family
        ensure_child_available(state.current_parent, BACKTEST_BACKEND_KEY)
        state.enter(BACKTEST_BACKEND_KEY)
        return
    if factor_family:
        state.factor_family = factor_family
    if not state.factor_family:
        state.factor_family = click.prompt("因子家族", default="", show_default=False)
    if not state.factor_family:
        raise click.ClickException("从顶层进入 backtest 时必须选择 factor-family")
    ensure_child_available(None, BACKTEST_PUBLIC_KEY)
    state.enter(BACKTEST_PUBLIC_KEY)


def _apply_local_settings(
    state,
    local_settings: tuple[str, ...],
    time_range: tuple[str, str] | None,
) -> None:
    for item in local_settings:
        key, value = _parse_key_value(item)
        state.backtest_local_settings[key] = value
    if time_range is not None:
        start, end = time_range
        state.backtest_local_settings["start_date"] = start
        state.backtest_local_settings["end_date"] = end


def _parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("--config-local-settings 必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("--config-local-settings 的 KEY 不能为空")
    return key, value.strip()


def _legacy_selectors(
    *,
    name: str,
    split_count: int | None,
    group_index: int | None,
    factor: str,
    factor_params: tuple[str, ...],
    product_path: str,
    product_path_name: str,
    product_path_paths: tuple[str, ...],
) -> AddGroupSelectors:
    args: list[str] = []
    if name:
        args.extend(["--group-name", name])
    if split_count is not None:
        args.extend(["--split-count", str(split_count)])
    if group_index is not None:
        args.extend(["--group-index", str(group_index)])
    if product_path_name or product_path_paths:
        args.extend(["--product-group", "add"])
        if product_path_name:
            args.extend(["--name", product_path_name])
        for path in product_path_paths:
            args.extend(["--path", path])
    elif product_path:
        args.extend(["--product-group", "from-candidates", "--name", product_path])
    if factor_params:
        args.extend(["--factor", "add"])
        for item in factor_params:
            args.extend(["--param", item])
    elif factor:
        args.extend(["--factor", factor])
    return parse_add_group_selectors(tuple(args))


def _append_group(
    state,
    *,
    selectors: AddGroupSelectors,
) -> None:
    client = client_from_config()
    _ensure_page_candidates(state, client)
    product_selection = resolve_product_group_selector(state, selectors.product_group)
    page_store, backtest_store = _stores_for_backtest(state, client)
    if product_selection:
        backtest_store.set("product_path_selection", product_selection)
    product_group_label = selection_label(backtest_store.effective("product_path_selection"))
    factor = resolve_factor_selector(state, client, selectors.factor, product_group_label=product_group_label)
    if factor:
        backtest_store.set("factor", factor)
    elif not backtest_store.effective("factor"):
        _load_default_factor_for_product_group(state, client, page_store, product_group_label=product_group_label)
    resolved_product_path = backtest_store.effective("product_path_selection")
    resolved_factor = backtest_store.effective("factor")
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
    if selectors.group_name:
        payload["name"] = selectors.group_name
    state.backtest_groups.append(payload)


def _print_group(group: dict[str, Any]) -> None:
    if group.get("name"):
        click.echo(f"名称: {group['name']}")
    if group.get("split_count") is not None:
        click.echo(f"分组数: {group['split_count']}")
    if group.get("group_index") is not None:
        click.echo(f"分组序号: {group['group_index']}")
    click.echo(f"产品路径: {selection_label(group.get('product_path_selection'))}")
    click.echo(f"因子: {group.get('factor')}")


def _stores_for_backtest(state, client=None) -> tuple[FieldStore, FieldStore]:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    backtest_store = FieldStore.from_manifest(client.manifest(BACKTEST_BACKEND_KEY), values=state.backtest_local_settings, parent=page_store)
    return page_store, backtest_store


def _ensure_page_candidates(state, client) -> None:
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    if not page_store.effective("product_path_candidates"):
        groups = client.list_candidates("product_path_candidates")
        page_store.set("product_path_candidates", groups)
        if groups and not page_store.effective("product_path_selection"):
            page_store.set("product_path_selection", product_group_selection(groups[0]))
    state.page_settings = page_store.to_payload()


def _load_default_factor_for_product_group(state, client, page_store: FieldStore, *, product_group_label: str) -> None:
    if not state.factor_family:
        return
    overview = client.factor_library_overview(factor_family=state.factor_family, product_group=product_group_label)
    factors = list(overview.get("factors") or [])
    page_store.set("factor_candidates", factors)
    if factors:
        page_store.set("factor", str(factors[0].get("factor_alias") or factors[0].get("alias") or ""))
