"""Shared selector parsing and resolution for backtest CLI commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import click

from tools.cli.modules.custom_factors.controller import parse_key_value as parse_factor_param
from tools.cli.modules.products.controller import product_group_selection
from tools.cli.modules.backtest.shared.fields import BacktestPublicFields


@dataclass(slots=True)
class FactorSelector:
    mode: str = ""
    alias: str = ""
    product_group: str = ""
    index: int | None = None
    params: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProductGroupSelector:
    mode: str = ""
    name: str = ""
    paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AddGroupSelectors:
    group_name: str = ""
    factor_family: str = ""
    split_count: int | None = None
    group_index: int | None = None
    factor: FactorSelector = field(default_factory=FactorSelector)
    product_group: ProductGroupSelector = field(default_factory=ProductGroupSelector)


@dataclass(slots=True)
class LongShortLegSelector:
    group_name: str = ""
    group: AddGroupSelectors | None = None


@dataclass(slots=True)
class LongShortSelector:
    name: str = ""
    long_leg: LongShortLegSelector = field(default_factory=LongShortLegSelector)
    short_leg: LongShortLegSelector = field(default_factory=LongShortLegSelector)


def parse_long_short_selector(args: tuple[str, ...]) -> LongShortSelector:
    selector = LongShortSelector()
    section: str | None = None
    current_group_args: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--ls-name", "--ls_name"}:
            selector.name = _require_value(args, i, token)
            i += 2
            continue
        if token == "--name" and section is None:
            selector.name = _require_value(args, i, token)
            i += 2
            continue
        if token == "--long-group":
            _flush_ls_group(selector, section, current_group_args)
            section = "long"
            current_group_args = []
            nxt = _peek(args, i)
            if nxt and not nxt.startswith("--"):
                selector.long_leg.group_name = str(nxt)
                i += 2
            else:
                i += 1
            continue
        if token == "--short-group":
            _flush_ls_group(selector, section, current_group_args)
            section = "short"
            current_group_args = []
            nxt = _peek(args, i)
            if nxt and not nxt.startswith("--"):
                selector.short_leg.group_name = str(nxt)
                i += 2
            else:
                i += 1
            continue
        if token == "--add":
            if section not in {"long", "short"}:
                raise click.ClickException("--add 必须跟在 --long-group 或 --short-group 后面")
            current_group_args = []
            i += 1
            continue
        if section in {"long", "short"}:
            current_group_args.append(token)
            i += 1
            continue
        raise click.ClickException(f"无法识别 long-short 参数: {token}")
    _flush_ls_group(selector, section, current_group_args)
    return selector


def parse_add_group_selectors(args: tuple[str, ...]) -> AddGroupSelectors:
    """Parse selector mini-grammar used by backtest group --add.

    Supported examples:
    - --factor add --param N=2m --param '$Rev=1'
    - --factor --alias 'SgCCS|N:1m|$F:1m|$Rev:1'
    - --factor SgCCS|N:1m
    - --factor --from-candidates --product-group 中国期货日盘 --index 1
    - --product-group add --name 现场日盘 --path Product/... --path -Product/...
    - --product-group --from-candidates --name 中国期货日盘
    """
    groups = parse_add_group_selector_groups(args)
    if len(groups) > 1:
        raise click.ClickException("当前入口只接受一个分组；一次新增多个分组请使用重复的 --add 段落")
    return groups[0] if groups else AddGroupSelectors()


def parse_add_group_selector_groups(args: tuple[str, ...]) -> list[AddGroupSelectors]:
    groups: list[AddGroupSelectors] = []
    current: list[str] = []
    for token in args:
        if token == "--add":
            if current:
                groups.append(_parse_one_add_group(tuple(current)))
                current = []
            continue
        current.append(token)
    if current or not groups:
        groups.append(_parse_one_add_group(tuple(current)))
    return groups


def _flush_ls_group(selector: LongShortSelector, section: str | None, args: list[str]) -> None:
    if section not in {"long", "short"} or not args:
        return
    parsed = parse_add_group_selectors(tuple(args))
    if section == "long":
        selector.long_leg.group = parsed
    else:
        selector.short_leg.group = parsed


def _parse_one_add_group(args: tuple[str, ...]) -> AddGroupSelectors:
    parsed = AddGroupSelectors()
    section: str | None = None
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--group-name", "--group_name"}:
            parsed.group_name = _require_value(args, i, token)
            section = None
            i += 2
            continue
        if token in {"--factor-family", "--factor_family"}:
            parsed.factor_family = _require_value(args, i, token)
            section = None
            i += 2
            continue
        if token in {"--split-count", "--split_count"}:
            parsed.split_count = _parse_int(_require_value(args, i, token), token)
            section = None
            i += 2
            continue
        if token in {"--group-index", "--group_index"}:
            parsed.group_index = _parse_int(_require_value(args, i, token), token)
            section = None
            i += 2
            continue
        if token == "--name":
            value = _require_value(args, i, token)
            if section == "product_group":
                parsed.product_group.name = value
            else:
                parsed.group_name = value
            i += 2
            continue
        if token == "--factor":
            section = "factor"
            nxt = _peek(args, i)
            if nxt in {"add", "from-candidates", "--from-candidates"}:
                parsed.factor.mode = str(nxt).lstrip("-").replace("-", "_")
                i += 2
            elif nxt and not str(nxt).startswith("--"):
                parsed.factor.mode = "alias"
                parsed.factor.alias = str(nxt)
                i += 2
            else:
                i += 1
            continue
        if token == "--factor-candidates":
            section = "factor"
            nxt = _peek(args, i)
            if nxt == "add":
                parsed.factor.mode = "add"
                i += 2
            elif nxt in {"from-candidates", "--from-candidates"}:
                parsed.factor.mode = "from_candidates"
                i += 2
            else:
                parsed.factor.mode = "from_candidates"
                i += 1
            continue
        if token == "--product-group":
            nxt = _peek(args, i)
            if section == "factor" and nxt not in {"add", "from-candidates", "--from-candidates"}:
                parsed.factor.product_group = str(_require_value(args, i, token))
                i += 2
                continue
            section = "product_group"
            if nxt in {"add", "from-candidates", "--from-candidates"}:
                parsed.product_group.mode = str(nxt).lstrip("-").replace("-", "_")
                i += 2
            elif nxt and not str(nxt).startswith("--"):
                parsed.product_group.mode = "from_candidates"
                parsed.product_group.name = str(nxt)
                i += 2
            else:
                i += 1
            continue
        if token == "--product-path-candidates":
            section = "product_group"
            nxt = _peek(args, i)
            if nxt == "add":
                parsed.product_group.mode = "add"
                i += 2
            elif nxt in {"from-candidates", "--from-candidates"}:
                parsed.product_group.mode = "from_candidates"
                i += 2
            else:
                parsed.product_group.mode = "from_candidates"
                i += 1
            continue
        if token in {"--product-path", "--product_path"}:
            parsed.product_group.mode = "from_candidates"
            parsed.product_group.name = _require_value(args, i, token)
            section = "product_group"
            i += 2
            continue
        if token in {"--product-path-name", "--product_path_name"}:
            parsed.product_group.mode = "add"
            parsed.product_group.name = _require_value(args, i, token)
            section = "product_group"
            i += 2
            continue
        if token in {"--product-path-path", "--product_path_path", "--path"}:
            parsed.product_group.mode = parsed.product_group.mode or "add"
            parsed.product_group.paths.append(_require_value(args, i, token))
            section = "product_group"
            i += 2
            continue
        if token == "--alias":
            parsed.factor.mode = "alias"
            parsed.factor.alias = _require_value(args, i, token)
            section = "factor"
            i += 2
            continue
        if token == "--from-candidates":
            if section == "product_group":
                parsed.product_group.mode = "from_candidates"
            else:
                parsed.factor.mode = "from_candidates"
                section = "factor"
            i += 1
            continue
        if token in {"--param", "--factor-param", "--factor_param"}:
            parsed.factor.mode = "add"
            parsed.factor.params.append(_require_value(args, i, token))
            section = "factor"
            i += 2
            continue
        if token == "--index":
            parsed.factor.mode = "from_candidates"
            value = _require_value(args, i, token)
            try:
                parsed.factor.index = int(value)
            except ValueError as exc:
                raise click.ClickException("--index 必须是整数") from exc
            section = "factor"
            i += 2
            continue
        if token == "--factor-product-group":
            parsed.factor.product_group = _require_value(args, i, token)
            section = "factor"
            i += 2
            continue
        raise click.ClickException(f"无法识别 group 参数: {token}")
    return parsed


def resolve_product_group_selector(state: Any, selector: ProductGroupSelector, *, fields: BacktestPublicFields) -> Any:
    if selector.mode == "add" or selector.paths:
        return _create_runtime_product_group(state, selector, fields=fields)
    if selector.mode == "from_candidates" or selector.name:
        candidates = _all_product_group_candidates(state, fields=fields)
        return resolve_product_group_by_name(selector.name, candidates)
    return None


def resolve_product_group_by_name(value: str, candidates: list[Any]) -> Any:
    if not value:
        return None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        keys = {
            str(item.get("id") or ""),
            str(item.get("product_path_selection_id") or ""),
            str(item.get("name") or ""),
            str(item.get("label") or ""),
            str(item.get("product_group") or ""),
        }
        if value in keys:
            return product_group_selection(item)
    return {"product_path_selection_id": value}


def resolve_factor_selector(
    state: Any,
    client: Any,
    selector: FactorSelector,
    *,
    factor_family: str,
    product_group_label: str,
    fields: BacktestPublicFields,
) -> str:
    if selector.mode == "add" or selector.params:
        return create_factor_candidate(state, client, factor_family=factor_family, params=selector.params, product_group=product_group_label, fields=fields)
    if selector.mode == "alias" or selector.alias:
        return selector.alias
    if selector.mode == "from_candidates":
        return resolve_factor_from_candidates(
            state,
            client,
            factor_family=factor_family,
            product_group=selector.product_group or product_group_label,
            alias=selector.alias,
            index=selector.index,
            fields=fields,
        )
    return ""


def create_factor_candidate(
    state: Any,
    client: Any,
    *,
    factor_family: str,
    params: list[str],
    product_group: str,
    fields: BacktestPublicFields,
) -> str:
    if not params:
        raise click.ClickException("现场新增因子时必须传 --param KEY=VALUE")
    if not factor_family:
        raise click.ClickException("现场新增因子参数时必须传 --factor-family")
    current = client.factor_library_configs(factor_family, product_group=product_group)
    rows = []
    for user in current.get("users") or []:
        if user.get("editable"):
            rows = list((user.get("config") or {}).get("params_list") or [])
            break
    rows.append(dict(parse_factor_param(item) for item in params))
    data = client.save_factor_library_config(factor_family, product_group=product_group, params_list=rows)
    factors = list(data.get("factors") or [])
    factor = str((factors[-1] if factors else {}).get("factor_alias") or "")
    if not factor:
        raise click.ClickException("新增因子参数成功但后端未返回 factor_alias")
    page_candidates = list(state.page_settings.get(fields.factor_candidates) or [])
    page_candidates.extend(factors[-1:])
    state.page_settings[fields.factor_candidates] = page_candidates
    state.page_settings[fields.factor] = factor
    return factor


def resolve_factor_from_candidates(
    state: Any,
    client: Any,
    *,
    factor_family: str,
    product_group: str,
    alias: str = "",
    index: int | None = None,
    fields: BacktestPublicFields,
) -> str:
    if not factor_family:
        raise click.ClickException("从因子候选选择时必须传 --factor-family")
    overview = client.factor_library_overview(factor_family=factor_family, product_group=product_group)
    factors = list(overview.get("factors") or [])
    state.page_settings[fields.factor_candidates] = factors
    if alias:
        for item in factors:
            candidate_alias = str(item.get("factor_alias") or item.get("alias") or "")
            if candidate_alias == alias:
                state.page_settings[fields.factor] = candidate_alias
                return candidate_alias
        raise click.ClickException(f"因子候选中找不到 alias: {alias}")
    if index is not None:
        if index < 1 or index > len(factors):
            raise click.ClickException(f"因子候选 index 超出范围: {index}")
        factor = str(factors[index - 1].get("factor_alias") or factors[index - 1].get("alias") or "")
        state.page_settings[fields.factor] = factor
        return factor
    if factors:
        factor = str(factors[0].get("factor_alias") or factors[0].get("alias") or "")
        state.page_settings[fields.factor] = factor
        return factor
    raise click.ClickException("因子候选列表为空")


def selection_label(selection: Any) -> str:
    if isinstance(selection, dict):
        return str(selection.get("product_group") or selection.get("label") or selection.get("name") or selection.get("product_path_selection_id") or "")
    return str(selection or "")


def _create_runtime_product_group(state: Any, selector: ProductGroupSelector, *, fields: BacktestPublicFields) -> dict[str, Any]:
    if not selector.name:
        raise click.ClickException("现场新增产品路径候选时必须传 --product-group add --name NAME")
    if not selector.paths:
        raise click.ClickException("现场新增产品路径候选时必须至少传一个 --path")
    existing_names = {selection_label(item) for item in _all_product_group_candidates(state, fields=fields)}
    if selector.name in existing_names:
        raise click.ClickException(f"产品路径候选名称已存在: {selector.name}")
    selection = {
        "product_path_selection_id": f"manual:{selector.name}",
        "id": f"manual:{selector.name}",
        "label": selector.name,
        "name": selector.name,
        "paths": list(selector.paths),
        "selected_paths": list(selector.paths),
        "source_type": "runtime_manual_path_group",
    }
    candidates = list(state.backtest_local_settings.get(fields.product_path_candidates) or [])
    candidates.append(selection)
    state.backtest_local_settings[fields.product_path_candidates] = candidates
    state.backtest_local_settings[fields.product_path_selection] = selection
    return selection


def _all_product_group_candidates(state: Any, *, fields: BacktestPublicFields) -> list[Any]:
    return list(state.page_settings.get(fields.product_path_candidates) or []) + list(
        state.backtest_local_settings.get(fields.product_path_candidates) or []
    )


def _peek(args: tuple[str, ...], index: int) -> str | None:
    nxt = index + 1
    if nxt >= len(args):
        return None
    return args[nxt]


def _require_value(args: tuple[str, ...], index: int, option: str) -> str:
    nxt = index + 1
    if nxt >= len(args):
        raise click.ClickException(f"{option} 缺少参数")
    return args[nxt]


def _parse_int(value: str, option: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise click.ClickException(f"{option} 必须是整数") from exc
