"""Shared helpers for single-factor analysis CLI modules."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.field_help import render_settings_help
from tools.cli.field_store import FieldStore
from tools.cli.modules.backtest import config_args as config_arg_helpers
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
        parsed = config_arg_helpers.parse_raw_settings(args)
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


def parse_factor_grid_options(args: tuple[str, ...], *, default_factor_family: str = "") -> dict[str, Any]:
    options: dict[str, Any] = {
        "factor_family": default_factor_family,
        "n": [],
        "f": [],
        "product_group": [],
        "rev": [],
        "top": 12,
    }
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--factor-family":
            options["factor_family"] = _required_grid_value(args, i, token)
            i += 2
            continue
        if token == "--n":
            options["n"].append(_required_grid_value(args, i, token))
            i += 2
            continue
        if token == "--f":
            options["f"].append(_required_grid_value(args, i, token))
            i += 2
            continue
        if token == "--product-group":
            options["product_group"].append(_required_grid_value(args, i, token))
            i += 2
            continue
        if token == "--top":
            options["top"] = int(_required_grid_value(args, i, token))
            i += 2
            continue
        if token == "--no-rev":
            if False not in options["rev"]:
                options["rev"].append(False)
            i += 1
            continue
        if token == "--rev":
            if True not in options["rev"]:
                options["rev"].append(True)
            i += 1
            continue
        raise click.ClickException(f"无法识别 grid 参数: {token}")
    if not options["n"]:
        options["n"] = ["1m", "2m", "3m", "5m", "10m"]
    if not options["f"]:
        options["f"] = ["1m"]
    if not options["rev"]:
        options["rev"] = [True]
    if not str(options.get("factor_family") or "").strip():
        raise click.ClickException("grid 缺少因子家族；请传 --factor-family")
    options["factor_family"] = str(options["factor_family"]).strip()
    return options


def factor_grid_items(state: Any, *, options: dict[str, Any], settings: dict[str, Any], client=None) -> list[dict[str, Any]]:
    client = client or client_from_config()
    factor_family = str(options.get("factor_family") or "").strip()
    if not factor_family:
        raise click.ClickException("grid 缺少因子家族；请传 --factor-family")
    product_selections = grid_product_selections(state, client, list(options.get("product_group") or []))
    time_settings = shared_time_settings(state)
    items: list[dict[str, Any]] = []
    for n_value in options["n"]:
        for f_value in options["f"]:
            for rev in options["rev"]:
                alias = factor_alias(factor_family, str(n_value), str(f_value), rev=bool(rev))
                register_grid_factor(state, client, alias, factor_family=factor_family)
                for selection in product_selections:
                    item_settings = dict(settings or {})
                    item_settings.update(time_settings)
                    items.append({
                        "factor": alias,
                        "product_group": selection_label(selection),
                        "selection": selection,
                        "settings": item_settings,
                        "payload_base": grid_payload_base(state, factor_family=factor_family, alias=alias, selection=selection),
                    })
    return items


def grid_payload_base(state: Any, *, factor_family: str, alias: str, selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_uuid": state.page_uuid,
        "factor_family_alias": factor_family,
        "factor_alias": alias,
        "factor": alias,
        "factor_name": alias,
        "product_path_selection_id": selection.get("product_path_selection_id") or selection.get("id") or "",
        "product_path_selection": selection,
        "paths": list(selection.get("paths") or selection.get("selected_paths") or []),
    }


def shared_time_settings(state: Any) -> dict[str, Any]:
    keys = ("start_date", "end_date", "start_time", "end_time", "time_precision", "timezone", "evaluation_split")
    values: dict[str, Any] = {}
    for source in (
        getattr(state, "backtest_local_settings", {}),
        getattr(state, "ic_test_local_settings", {}),
        getattr(state, "factor_type_analysis_local_settings", {}),
        getattr(state, "factor_evaluation_local_settings", {}),
    ):
        for key in keys:
            if key in source and source[key] not in {None, ""}:
                values[key] = source[key]
    return values


def grid_product_selections(state: Any, client: Any, names: list[str]) -> list[dict[str, Any]]:
    candidates = client.list_candidates("product_path_candidates")
    if names:
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
    for group in getattr(state, "backtest_groups", []):
        selection = group.get("product_path_selection") if isinstance(group, dict) else None
        if isinstance(selection, dict):
            return [selection]
    selection = getattr(state, "page_settings", {}).get("product_path_selection")
    if isinstance(selection, dict):
        return [selection]
    raise click.ClickException("grid 缺少产品路径；请传 --product-group 或先加载含产品路径的模板")


def register_grid_factor(state: Any, client: Any, alias: str, *, factor_family: str) -> None:
    candidates = list(getattr(state, "page_settings", {}).get("factor_candidates") or [])
    known = {str(item.get("factor_alias") or item.get("alias") or "") for item in candidates if isinstance(item, dict)}
    data = client.add_candidate("factor", {
        "factor_family_alias": factor_family,
        "params": params_from_factor_alias(alias, factor_family),
        "page_uuid": state.page_uuid,
    })
    factor_alias = str(data.get("factor_alias") or alias)
    if factor_alias not in known:
        candidates.append({"factor_alias": factor_alias, "params": params_from_factor_alias(alias, factor_family)})
        state.page_settings["factor_candidates"] = candidates


def factor_alias(factor_family: str, n_value: str, f_value: str, *, rev: bool) -> str:
    alias = f"{factor_family}|N:{n_value}|$F:{f_value}"
    if rev:
        alias += "|$Rev"
    return alias


def params_from_factor_alias(alias: str, factor_family: str) -> dict[str, Any]:
    prefix = f"{factor_family}|"
    if alias == factor_family:
        return {}
    if not alias.startswith(prefix):
        raise click.ClickException(f"因子 {alias} 不属于 {factor_family}")
    params: dict[str, Any] = {}
    for part in alias[len(prefix):].split("|"):
        if not part:
            continue
        if ":" in part:
            key, value = part.split(":", 1)
            params[key] = value[1:-1] if value.startswith("[") and value.endswith("]") else value
        elif part == "$Rev":
            params[part] = "1"
        else:
            params[part] = True
    return params


def _required_grid_value(args: tuple[str, ...], index: int, option: str) -> str:
    if index + 1 >= len(args) or args[index + 1].startswith("--"):
        raise click.ClickException(f"{option} 缺少参数")
    return str(args[index + 1])
