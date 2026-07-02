"""Single-factor-family page CLI controller."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.display import print_location_welcome, print_single_factor_family_welcome
from tools.cli.core.errors import friendly_errors
from tools.cli.modules.backtest import BACKTEST_PUBLIC_KEY, enter_backtest_state
from tools.cli.state import load_state, save_state

SINGLE_FACTOR_PAGE_SETTINGS_KEY = "single_factor_page"
SETTINGS_COMMAND_ALIASES = {SINGLE_FACTOR_PAGE_SETTINGS_KEY, "settings", "template"}


@click.command("single_factor_family_test")
@click.option("--factor-family", "--factor_family", default="", help="要测试的因子家族。")
@click.argument("path", nargs=-1)
@friendly_errors
def enter_single_factor_family_test(factor_family: str, path: tuple[str, ...]) -> None:
    """进入单因子测试控制界面。

    示例:

      factortester single_factor_test --factor-family SgCCS
      factortester single_factor_test --factor-family SgCCS backtest
      factortester single_factor_test --factor-family SgCCS single_factor_page template list
      factortester single_factor_test --factor-family SgCCS template list
      factortester single_factor_test --factor-family SgCCS template load <模板ID或名称>

    进入后运行 factortester list 查看 IC 测试、回测等下一层模块。
    """
    _enter_single_factor_page(factor_family, path)


@click.command("single_factor_test")
@click.option("--factor-family", "--factor_family", default="", help="要测试的因子家族。")
@click.argument("path", nargs=-1)
@friendly_errors
def enter_single_factor_test(factor_family: str, path: tuple[str, ...]) -> None:
    """进入单因子测试控制界面。

    示例:

      factortester single_factor_test --factor-family SgCCS
      factortester single_factor_test --factor-family SgCCS backtest
      factortester single_factor_test --factor-family SgCCS single_factor_page template list
      factortester single_factor_test --factor-family SgCCS template list
      factortester single_factor_test --factor-family SgCCS template load <模板ID或名称>

    进入后运行 factortester list 查看 IC 测试、回测等下一层模块。
    """
    _enter_single_factor_page(factor_family, path)


def _enter_single_factor_page(factor_family: str, path: tuple[str, ...]) -> None:
    """Enter the single-factor-family test page controller."""
    if not factor_family:
        factor_family = click.prompt("因子家族", default="", show_default=False)
    if not factor_family:
        raise click.ClickException("必须选择 factor_family")
    state = load_state()
    if state.current_parent is None:
        ensure_child_available(None, "single_factor_test")
    state.enter("single_factor_family_test")
    state.factor_family = factor_family
    if path and path[0] in SETTINGS_COMMAND_ALIASES:
        _handle_settings_submodule_command(state, path)
        save_state(state)
        return
    for child in path:
        enter_child(state, child)
    save_state(state)
    if path:
        print_location_welcome(state)
    else:
        print_single_factor_family_welcome(state)


def enter_child(state, key: str) -> None:
    if key == BACKTEST_PUBLIC_KEY:
        enter_backtest_state(state)
        return
    ensure_child_available(state.current_parent, key)
    state.enter(key)


def _handle_settings_submodule_command(state, path: tuple[str, ...]) -> None:
    ensure_child_available("single_factor_family_test", SINGLE_FACTOR_PAGE_SETTINGS_KEY)
    command_path = path
    if command_path and command_path[0] == SINGLE_FACTOR_PAGE_SETTINGS_KEY:
        command_path = command_path[1:]
    if command_path and command_path[0] == "settings":
        command_path = command_path[1:]
    if not command_path:
        _print_settings_submodule_welcome(state)
        return
    if command_path[0] == "template":
        _handle_template_command(state, command_path[1:])
        return
    raise click.ClickException("因子家族测试设置支持的动作: template list, template load")


def _print_settings_submodule_welcome(state) -> None:
    click.echo("因子家族测试设置")
    click.echo(f"当前因子家族: {state.factor_family}")
    click.echo("")
    click.echo("可用命令:")
    click.echo("  factortester single_factor_test --factor-family <因子家族> single_factor_page template list")
    click.echo("  factortester single_factor_test --factor-family <因子家族> single_factor_page template load <模板ID或名称>")
    click.echo("")
    click.echo("简写:")
    click.echo("  factortester single_factor_test --factor-family <因子家族> template list")


def _handle_template_command(state, args: tuple[str, ...]) -> None:
    if not args or args[0] in {"list", "ls"}:
        _list_templates(state.factor_family)
        return
    if args[0] == "load":
        if len(args) < 2:
            raise click.ClickException("template load 需要模板 ID 或名称")
        _load_template_into_state(state, args[1])
        return
    raise click.ClickException("template 支持的动作: list, load")


def _list_templates(factor_family: str) -> None:
    templates = client_from_config().list_single_factor_setting_templates(factor_family)
    click.echo(f"{factor_family} 模板列表")
    if not templates:
        click.echo("  （空）")
        return
    for index, template in enumerate(templates, start=1):
        click.echo(f"  {index}. {template.get('name') or template.get('id')} · id={template.get('id')}")


def _load_template_into_state(state, selector: str) -> None:
    client = client_from_config()
    templates = client.list_single_factor_setting_templates(state.factor_family)
    template_id = _resolve_template_id(selector, templates)
    template = client.get_single_factor_setting_template(state.factor_family, template_id)
    snapshot = template.get("snapshot")
    if not isinstance(snapshot, dict):
        raise click.ClickException("模板缺少 snapshot")
    applied = _apply_snapshot_to_state(state, snapshot, template_name=str(template.get("name") or selector))
    registered = _register_template_factors(state, client)
    click.echo(f"已加载模板: {template.get('name') or selector}")
    factor_text = f" · 已注册因子: {registered}" if registered else ""
    click.echo(
        f"页面字段: {applied['page_settings']} · local-settings: {applied['local_settings']} "
        f"· groups: {applied['groups']} · long-short: {applied['ls_configs']}{factor_text}"
    )


def _resolve_template_id(selector: str, templates: list[dict[str, Any]]) -> str:
    for index, template in enumerate(templates, start=1):
        keys = {str(index), str(template.get("id") or ""), str(template.get("name") or "")}
        if selector in keys:
            return str(template.get("id") or "")
    raise click.ClickException(f"找不到模板: {selector}")


def _apply_snapshot_to_state(state, snapshot: dict[str, Any], *, template_name: str) -> dict[str, int]:
    factors = snapshot.get("factors") if isinstance(snapshot.get("factors"), dict) else {}
    if factors:
        for key in ("factor_candidates", "factor"):
            if key in factors:
                state.page_settings[key] = factors[key]
    state.page_settings["setting_template"] = template_name

    local_settings = snapshot.get("local_settings") if isinstance(snapshot.get("local_settings"), dict) else {}
    state.backtest_local_settings = dict(local_settings or {})

    group_settings = snapshot.get("group_settings") if isinstance(snapshot.get("group_settings"), dict) else {}
    groups = [_normalize_group_snapshot(item) for item in (group_settings.get("groups") or []) if isinstance(item, dict)]
    ls_configs = [_normalize_ls_snapshot(item) for item in (group_settings.get("lsConfigs") or []) if isinstance(item, dict)]
    state.backtest_groups = groups
    state.backtest_ls_configs = ls_configs
    return {
        "page_settings": len(factors) + 1,
        "local_settings": len(state.backtest_local_settings),
        "groups": len(groups),
        "ls_configs": len(ls_configs),
    }


def _normalize_group_snapshot(group: dict[str, Any]) -> dict[str, Any]:
    out = dict(group)
    _rename_if_present(out, "splitCount", "split_count")
    _rename_if_present(out, "groupIndex", "group_index")
    _rename_if_present(out, "factorAlias", "factor")
    _rename_if_present(out, "isAllGroups", "is_all_groups")
    return out


def _normalize_ls_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    _rename_if_present(out, "longGroupId", "long_group_id")
    _rename_if_present(out, "shortGroupId", "short_group_id")
    return out


def _rename_if_present(target: dict[str, Any], old: str, new: str) -> None:
    if old in target and new not in target:
        target[new] = target[old]


def _register_template_factors(state, client) -> int:
    aliases = _template_factor_aliases(state)
    if not aliases or not state.page_uuid:
        return 0
    candidates = list(state.page_settings.get("factor_candidates") or [])
    known = {
        str(item.get("factor_alias") or item.get("alias") or "")
        for item in candidates
        if isinstance(item, dict)
    }
    registered = 0
    for alias in aliases:
        params = _params_from_factor_alias(alias, state.factor_family)
        data = client.add_candidate("factor", {
            "factor_family_alias": state.factor_family,
            "params": params,
            "page_uuid": state.page_uuid,
        })
        factor_alias = str(data.get("factor_alias") or alias)
        if factor_alias not in known:
            candidates.append({"factor_alias": factor_alias, "params": params})
            known.add(factor_alias)
        registered += 1
    state.page_settings["factor_candidates"] = candidates
    if aliases:
        state.page_settings["factor"] = aliases[0]
    return registered


def _template_factor_aliases(state) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for group in state.backtest_groups:
        if not isinstance(group, dict):
            continue
        alias = str(group.get("factor") or group.get("factorAlias") or "").strip()
        if alias and alias not in seen:
            seen.add(alias)
            aliases.append(alias)
    return aliases


def _params_from_factor_alias(alias: str, factor_family: str) -> dict[str, Any]:
    prefix = f"{factor_family}|"
    if alias == factor_family:
        return {}
    if not alias.startswith(prefix):
        raise click.ClickException(f"模板因子 {alias} 不属于当前因子家族 {factor_family}")
    params: dict[str, Any] = {}
    for part in alias[len(prefix):].split("|"):
        if not part:
            continue
        if ":" in part:
            key, value = part.split(":", 1)
            if value.startswith("[") and value.endswith("]"):
                value = value[1:-1]
            params[key] = value
        elif part == "$Rev":
            params[part] = "1"
        else:
            params[part] = True
    return params
