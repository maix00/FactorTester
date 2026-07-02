"""Shared helpers for single-factor analysis CLI modules."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
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
from tools.cli.modules.products.controller import product_group_selection


def stores_for_application(state: Any, application: str, values: dict[str, Any], client=None) -> tuple[FieldStore, FieldStore]:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    app_store = FieldStore.from_manifest(client.manifest(application), values=values, parent=page_store)
    return page_store, app_store


def apply_local_settings(state: Any, *, application: str, values_attr: str, args: tuple[str, ...]) -> bool:
    show_help = "--help" in args or "-h" in args
    args = tuple(arg for arg in args if arg not in {"--help", "-h"})
    values = getattr(state, values_attr)
    if args:
        parsed = _parse_raw_settings(args)
        _, store = stores_for_application(state, application, values)
        unknown = [key for key in parsed if key not in store.defaults]
        if unknown:
            raise click.ClickException(f"{application} local-settings 包含未注册字段: " + ", ".join(sorted(unknown)))
        for key, value in parsed.items():
            try:
                store.validate_value(key, value)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from None
        values.update(parsed)
    if show_help:
        _, store = stores_for_application(state, application, values)
        for line in render_settings_help(store, title=f"{application} 设置上下文"):
            click.echo(line)
        return True
    return False


def parse_run_selectors(args: tuple[str, ...]):
    if "--run" in args:
        args = tuple(arg for arg in args if arg != "--run")
    return parse_add_group_selectors(args)


def ensure_page_product_candidates(state: Any, client=None) -> None:
    client = client or client_from_config()
    page_store = FieldStore.from_manifest(client.manifest("single_factor_page"), values=state.page_settings)
    if "product_path_candidates" in page_store.defaults and not page_store.effective("product_path_candidates"):
        page_store.set("product_path_candidates", client.list_candidates("product_path_candidates"))
    state.page_settings = page_store.to_payload()


def resolve_product_group(state: Any, selector: ProductGroupSelector) -> dict[str, Any]:
    if selector.mode == "add" or selector.paths:
        if not selector.name:
            raise click.ClickException("现场新增产品路径候选时必须传 --product-group add --name NAME")
        if not selector.paths:
            raise click.ClickException("现场新增产品路径候选时必须至少传一个 --path")
        return {
            "product_path_selection_id": f"manual:{selector.name}",
            "id": f"manual:{selector.name}",
            "label": selector.name,
            "name": selector.name,
            "paths": list(selector.paths),
            "selected_paths": list(selector.paths),
            "source_type": "runtime_manual_path_group",
        }
    candidates = list(state.page_settings.get("product_path_candidates") or [])
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
    raise click.ClickException("缺少产品路径；请传 --product-group")


def resolve_factor(state: Any, selector: FactorSelector, *, factor_family: str, product_group_label: str, client=None) -> str:
    client = client or client_from_config()
    if selector.mode == "alias" or selector.alias:
        return selector.alias
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
    if selector.mode == "add" or selector.params:
        if not factor_family:
            raise click.ClickException("现场新增因子参数时必须传 --factor-family")
        from tools.cli.modules.custom_factors.controller import parse_key_value

        current = client.factor_library_configs(factor_family, product_group=product_group_label)
        rows = []
        for user in current.get("users") or []:
            if user.get("editable"):
                rows = list((user.get("config") or {}).get("params_list") or [])
                break
        rows.append(dict(parse_key_value(item) for item in selector.params))
        data = client.save_factor_library_config(factor_family, product_group=product_group_label, params_list=rows)
        factors = list(data.get("factors") or [])
        factor = str((factors[-1] if factors else {}).get("factor_alias") or "")
        if not factor:
            raise click.ClickException("新增因子参数成功但后端未返回 factor_alias")
        return factor
    raise click.ClickException("缺少因子；请传 --factor")


def selection_summary(selection: dict[str, Any], factor: str) -> str:
    return f"产品路径={selection_label(selection) or '（未设置）'} · 因子={factor or '（未设置）'}"


def base_payload(
    state: Any,
    *,
    selectors: Any,
    settings: dict[str, Any],
) -> dict[str, Any]:
    client = client_from_config()
    ensure_page_product_candidates(state, client)
    product_selection = resolve_product_group(state, selectors.product_group)
    factor_family = resolve_factor_family_selector(state, client, selectors)
    factor = resolve_factor(
        state,
        selectors.factor,
        factor_family=factor_family,
        product_group_label=selection_label(product_selection),
        client=client,
    )
    return {
        "page_uuid": state.page_uuid,
        "factor_family_alias": factor_family,
        "factor_alias": factor,
        "factor": factor,
        "factor_name": factor,
        "product_path_selection_id": product_selection.get("product_path_selection_id") or product_selection.get("id") or "",
        "product_path_selection": product_selection,
        "paths": list(product_selection.get("paths") or product_selection.get("selected_paths") or []),
        "settings": dict(settings),
        "_summary": selection_summary(product_selection, factor),
    }
