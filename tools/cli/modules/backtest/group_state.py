"""State mutation helpers for backtest group drafts."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest import config_state as config_state_helpers
from tools.cli.modules.backtest.shared.fields import resolve_backtest_public_fields
from tools.cli.modules.backtest.shared.selectors import (
    AddGroupSelectors,
    parse_add_group_selectors,
    parse_add_group_selector_groups,
    resolve_factor_family_selector,
    resolve_factor_selector,
    resolve_product_group_selector,
    selection_label,
)


def parse_group_add_selectors(args: tuple[str, ...], *, batch: bool) -> list[AddGroupSelectors]:
    if not batch:
        names = config_arg_helpers.group_names_from_args(args)
        if not names:
            raise click.ClickException("group --add 必须传 --group-name；不再支持 group --group-name 直接新增")
        return parse_add_group_selector_groups(args)
    if "--group-index" in args or "--group_index" in args:
        raise click.ClickException("group --add --batch 不允许传 --group-index；序号由 --group-names 顺序自动生成")
    names = config_arg_helpers.group_names_from_args(args)
    if not names:
        raise click.ClickException("group --add --batch 必须传 --group-names NAME...")
    base_args = config_arg_helpers.remove_group_name_args(args)
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


def derive_or_copy_groups(
    state,
    args: tuple[str, ...],
    *,
    selectors_args: tuple[str, ...],
    extra_values: dict[str, Any] | None,
    derived: bool,
) -> list[dict[str, Any]]:
    names = config_arg_helpers.group_names_from_args(args)
    if len(names) < 2:
        raise click.ClickException("group --derive/--copy 需要先传源分组，再传至少一个新分组名：--group-name A1 --derive --group-name A1a")
    source = find_group_by_name(state, names[0])
    selectors = parse_add_group_selectors(config_arg_helpers.remove_group_name_args(selectors_args))
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
        edit_group(state, group_item, selectors=selectors, extra_values=extra_values)
        state.backtest_groups.append(group_item)
        created.append(group_item)
    return created


def append_group(
    state,
    *,
    selectors: AddGroupSelectors,
    extra_values: dict[str, Any] | None = None,
) -> None:
    client = client_from_config()
    config_state_helpers.ensure_page_candidates(state, client)
    page_store, backtest_store = config_state_helpers.stores_for_backtest(state, client)
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
        config_state_helpers.load_default_factor_for_product_group(
            state,
            client,
            page_store,
            factor_family=factor_family,
            product_group_label=product_group_label,
        )
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


def edit_group(
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
    config_state_helpers.ensure_page_candidates(state, client)
    page_store, backtest_store = config_state_helpers.stores_for_backtest(state, client)
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


def resolve_ls_leg(state, leg, *, side: str) -> dict[str, Any]:
    if leg.group is not None:
        before = len(state.backtest_groups)
        append_group(state, selectors=leg.group)
        group = state.backtest_groups[-1]
        if not group.get("name"):
            group["name"] = f"{side}-{before + 1}"
        return group
    if leg.group_name:
        return find_group_by_name(state, leg.group_name)
    raise click.ClickException(f"long-short 缺少 {side} leg；请传 --{side}-group GROUP 或 --{side}-group --add ...")


def find_group_by_name(state, name: str) -> dict[str, Any]:
    for group in state.backtest_groups:
        if name in {str(group.get("name") or ""), str(group.get("id") or "")}:
            return group
    raise click.ClickException(f"找不到分组: {name}")


def selected_groups(state, args: tuple[str, ...], *, default_all: bool = False) -> list[dict[str, Any]]:
    names = config_arg_helpers.group_names_from_args(args)
    if not names:
        if default_all:
            return list(state.backtest_groups)
        raise click.ClickException("请用 --group-name 或 --group-names 选择分组")
    return [find_group_by_name(state, name) for name in names]


def group_ref(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "split_count": group.get("split_count"),
        "group_index": group.get("group_index"),
    }
