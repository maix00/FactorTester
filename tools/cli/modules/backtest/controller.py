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
from tools.cli.field_help import field_flag, field_type_label, render_settings_help
from tools.cli.field_store import FieldStore
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY
from tools.cli.modules.products.controller import product_group_selection
from tools.cli.modules.backtest.shared.fields import resolve_backtest_public_fields
from tools.cli.modules.backtest.shared.selectors import (
    AddGroupSelectors,
    parse_add_group_selectors,
    parse_add_group_selector_groups,
    parse_long_short_selector,
    resolve_factor_selector,
    resolve_product_group_selector,
    selection_label,
)
from tools.cli.state import load_state, save_state


SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}
SELECTOR_HELP_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}
_ADD_GROUP_SELECTOR_ROOTS = {
    "--add-group", "--add_group",
    "--group-name", "--group_name",
    "--split-count", "--split_count",
    "--group-index", "--group_index",
    "--name",
    "--factor", "--factor-candidates", "--alias", "--from-candidates",
    "--param", "--factor-param", "--factor_param", "--index", "--factor-product-group",
    "--product-group", "--product-path-candidates",
    "--product-path", "--product_path",
    "--product-path-name", "--product_path_name",
    "--product-path-path", "--product_path_path",
    "--path",
}


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
    """进入通用回测控制界面。

    回测与 single_factor_test 平行注册；从顶层进入时必须指定因子家族:

      factortester backtest --factor-family SgCCS

    常用草稿命令:

      factortester backtest config-local-settings --allocation-mode equal_notional
      factortester backtest add-group --group-name A1 --split-count 5 --group-index 1
      factortester backtest add-group --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'
      factortester backtest add-group --factor add --param N=2m --param '$Rev=1'
      factortester backtest add-group --product-group from-candidates --name 中国期货日盘
      factortester backtest add-ls --ls-name LS-A1-A5 --long-group A1 --short-group A5

    字段级帮助:

      factortester add-group --group-name --help
      factortester add-group --group-name A1 --help
    """
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


@backtest.command("config-local-settings", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def config_local_settings(ctx: click.Context) -> None:
    """Edit local-settings as a sibling action to add-group/add-ls."""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    setting_args = _strip_context_help(args)
    if setting_args:
        _apply_raw_local_settings(state, setting_args)
    if show_help:
        _validate_registered_local_settings(state)
        _print_backtest_settings_help(state)
        return
    save_state(state)
    click.echo("已更新 local-settings")
    print_backtest_welcome(state)


@backtest.command("add-group", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def add_group(
    ctx: click.Context,
) -> None:
    """新增一个或多个回测分组草稿。

    单个分组可以省略段落标记:

      factortester add-group --group-name A1 --split-count 5 --group-index 1

    多个分组用重复 --add-group 分段:

      factortester add-group --add-group --group-name A1 --split-count 5 --group-index 1 \
        --add-group --group-name A5 --split-count 5 --group-index 5

    字段说明模式:

      factortester add-group --group-name --help

    上下文校验模式:

      factortester add-group --group-name A1 --help
    """
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    help_target = _context_help_target(args)
    clean_args = _strip_context_help(args)
    selector_args, setting_args = _split_selector_and_local_setting_args(clean_args, selector_roots=_ADD_GROUP_SELECTOR_ROOTS)
    if setting_args:
        _apply_raw_local_settings(state, tuple(setting_args))
    if show_help and help_target and not help_target.has_value:
        _print_add_group_field_help(state, help_target.option)
        return
    selectors_list = parse_add_group_selector_groups(tuple(selector_args))
    if show_help:
        _validate_registered_local_settings(state)
        _print_backtest_settings_help(state)
        return
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


@backtest.command("add-ls", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def add_ls(ctx: click.Context) -> None:
    """Add a long-short strategy draft from existing or inline group legs."""
    state = load_state()
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state)
    args = tuple(ctx.args)
    show_help = _has_context_help(args)
    clean_args = _strip_context_help(args)
    if show_help:
        _validate_registered_local_settings(state)
        _print_backtest_settings_help(state)
        return
    selector = parse_long_short_selector(clean_args)
    long_group = _resolve_ls_leg(state, selector.long_leg, side="long")
    short_group = _resolve_ls_leg(state, selector.short_leg, side="short")
    config = {
        "name": selector.name or f"LS {long_group.get('name') or long_group.get('id')} / {short_group.get('name') or short_group.get('id')}",
        "long_group": _group_ref(long_group),
        "short_group": _group_ref(short_group),
    }
    state.backtest_ls_configs.append(config)
    save_state(state)
    click.echo("新增 Long-Short")
    click.echo(f"名称: {config['name']}")
    click.echo(f"多头: {config['long_group'].get('name') or config['long_group'].get('id')}")
    click.echo(f"空头: {config['short_group'].get('name') or config['short_group'].get('id')}")


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
    if not local_settings and time_range is None:
        return
    for item in local_settings:
        key, value = _parse_key_value(item)
        state.backtest_local_settings[key] = value
    if time_range is not None:
        start, end = time_range
        state.backtest_local_settings["start_date"] = start
        state.backtest_local_settings["end_date"] = end


def _apply_raw_local_settings(state, args: tuple[str, ...]) -> None:
    i = 0
    while i < len(args):
        token = args[i]
        if "=" in token and not token.startswith("--"):
            key, value = _parse_key_value(token)
            state.backtest_local_settings[key] = value
            i += 1
            continue
        if not token.startswith("--"):
            raise click.ClickException(f"无法识别 local-settings 参数: {token}")
        key = token[2:].replace("-", "_")
        if not key:
            raise click.ClickException("local-settings 字段名不能为空")
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            value: Any = True
            i += 1
        else:
            value = args[i + 1]
            i += 2
        state.backtest_local_settings[key] = value


def _parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("--config-local-settings 必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("--config-local-settings 的 KEY 不能为空")
    return key, value.strip()


def _has_context_help(args: tuple[str, ...]) -> bool:
    return "--help" in args or "-h" in args


class _HelpTarget:
    def __init__(self, option: str, *, has_value: bool) -> None:
        self.option = option
        self.has_value = has_value


def _context_help_target(args: tuple[str, ...]) -> _HelpTarget | None:
    help_positions = [index for index, token in enumerate(args) if token in {"--help", "-h"}]
    if not help_positions:
        return None
    help_index = help_positions[0]
    if help_index == 0:
        return None
    previous = args[help_index - 1]
    if previous.startswith("--"):
        return _HelpTarget(previous, has_value=False)
    for index in range(help_index - 2, -1, -1):
        token = args[index]
        if token.startswith("--"):
            return _HelpTarget(token, has_value=True)
    return None


def _strip_context_help(args: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(arg for arg in args if arg not in {"--help", "-h"})


def _split_selector_and_local_setting_args(args: tuple[str, ...], *, selector_roots: set[str]) -> tuple[list[str], list[str]]:
    selector_args: list[str] = []
    setting_args: list[str] = []
    selector_mode = False
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--add-group", "--add_group"}:
            selector_mode = True
            selector_args.append(token)
            i += 1
            continue
        if token in selector_roots:
            selector_mode = True
            selector_args.append(token)
            if i + 1 < len(args) and not (args[i + 1].startswith("--") and args[i + 1] not in {"--from-candidates"}):
                selector_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if token.startswith("--") and not selector_mode:
            setting_args.append(token)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                setting_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if token.startswith("--"):
            setting_args.append(token)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                setting_args.append(args[i + 1])
                i += 2
            else:
                i += 1
            continue
        selector_args.append(token)
        i += 1
    return selector_args, setting_args


def _validate_registered_local_settings(state) -> None:
    _, store = _stores_for_backtest(state)
    unknown = [key for key in state.backtest_local_settings if key not in store.defaults]
    if unknown:
        raise click.ClickException("local-settings 包含未注册字段: " + ", ".join(sorted(unknown)))
    for key, value in state.backtest_local_settings.items():
        try:
            store.validate_value(key, value)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None


def _print_backtest_settings_help(state) -> None:
    _, store = _stores_for_backtest(state)
    for line in render_settings_help(store, title="回测设置上下文"):
        click.echo(line)


def _print_add_group_field_help(state, option: str) -> None:
    field_key = _field_key_for_option(option)
    if field_key is None:
        raise click.ClickException(f"无法识别 add-group 字段: {option}")
    _, store = _stores_for_backtest(state)
    meta = store.field(field_key)
    if meta:
        click.echo(f"{option} 字段说明")
        click.echo(f"  后端字段: {field_key}")
        click.echo(f"  中文名: {meta.get('label') or field_key}")
        click.echo(f"  类型: {field_type_label(meta)}")
        click.echo(f"  默认值: {meta.get('value')!r}")
        click.echo(f"  可见: {'是' if store.is_visible(field_key) else '否'}")
        click.echo(f"  可编辑: {'是' if store.is_editable(field_key) else '否'}")
        if meta.get("options"):
            options = ", ".join(
                f"{item.get('value')}({item.get('label') or item.get('value')})"
                for item in meta["options"]
                if isinstance(item, dict)
            )
            click.echo(f"  允许值: {options}")
        if meta.get("help_text"):
            click.echo(f"  说明: {meta['help_text']}")
        click.echo(f"  写法: {field_flag(field_key)} VALUE")
        return
    local = _ADD_GROUP_LOCAL_FIELD_HELP.get(field_key)
    if local is None:
        raise click.ClickException(f"字段尚未由后端注册: {field_key}")
    click.echo(f"{option} 字段说明")
    click.echo(f"  字段: {field_key}")
    click.echo(f"  中文名: {local['label']}")
    click.echo(f"  类型: {local['type']}")
    click.echo(f"  说明: {local['help']}")
    click.echo(f"  写法: {option} {local['metavar']}")


def _field_key_for_option(option: str) -> str | None:
    normalized = option.lstrip("-").replace("-", "_")
    aliases = {
        "name": "group_name",
        "group_name": "group_name",
        "split_count": "split_count",
        "group_index": "group_index",
        "product_group": "product_path_selection",
        "product_path": "product_path_selection",
        "product_path_candidates": "product_path_candidates",
        "factor": "factor",
        "factor_candidates": "factor_candidates",
    }
    return aliases.get(normalized, normalized or None)


_ADD_GROUP_LOCAL_FIELD_HELP = {
    "group_name": {
        "label": "分组名称",
        "type": "str",
        "metavar": "NAME",
        "help": "当前新增分组在回测草稿中的显示名称；不参与后端因子或交易语义。",
    },
}


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
    page_store, backtest_store = _stores_for_backtest(state, client)
    fields = resolve_backtest_public_fields(backtest_store)
    product_selection = resolve_product_group_selector(state, selectors.product_group, fields=fields)
    if product_selection:
        backtest_store.set(fields.product_path_selection, product_selection)
    product_group_label = selection_label(backtest_store.effective(fields.product_path_selection))
    factor = resolve_factor_selector(state, client, selectors.factor, product_group_label=product_group_label, fields=fields)
    if factor:
        backtest_store.set(fields.factor, factor)
    elif not backtest_store.effective(fields.factor):
        _load_default_factor_for_product_group(state, client, page_store, product_group_label=product_group_label)
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
    if selectors.group_name:
        payload["name"] = selectors.group_name
    payload.setdefault("id", f"group-{len(state.backtest_groups) + 1}")
    state.backtest_groups.append(payload)


def _resolve_ls_leg(state, leg, *, side: str) -> dict[str, Any]:
    if leg.group is not None:
        before = len(state.backtest_groups)
        _append_group(state, selectors=leg.group)
        group = state.backtest_groups[-1]
        if not group.get("name"):
            group["name"] = f"{side}-{before + 1}"
        return group
    if leg.group_name:
        return _find_group_by_name(state, leg.group_name)
    raise click.ClickException(f"add-ls 缺少 {side} leg；请传 --{side}-group GROUP 或 --{side}-group --add-group ...")


def _find_group_by_name(state, name: str) -> dict[str, Any]:
    for group in state.backtest_groups:
        if name in {str(group.get("name") or ""), str(group.get("id") or "")}:
            return group
    raise click.ClickException(f"找不到分组: {name}")


def _group_ref(group: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": group.get("id"),
        "name": group.get("name"),
        "split_count": group.get("split_count"),
        "group_index": group.get("group_index"),
    }


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
    fields = resolve_backtest_public_fields(page_store)
    if not page_store.effective(fields.product_path_candidates):
        groups = client.list_candidates(fields.product_path_candidates)
        page_store.set(fields.product_path_candidates, groups)
        if groups and not page_store.effective(fields.product_path_selection):
            page_store.set(fields.product_path_selection, product_group_selection(groups[0]))
    state.page_settings = page_store.to_payload()


def _load_default_factor_for_product_group(state, client, page_store: FieldStore, *, product_group_label: str) -> None:
    if not state.factor_family:
        return
    overview = client.factor_library_overview(factor_family=state.factor_family, product_group=product_group_label)
    factors = list(overview.get("factors") or [])
    fields = resolve_backtest_public_fields(page_store)
    page_store.set(fields.factor_candidates, factors)
    if factors:
        page_store.set(fields.factor, str(factors[0].get("factor_alias") or factors[0].get("alias") or ""))
