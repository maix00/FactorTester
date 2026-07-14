"""Backtest template snapshot/load/save helpers."""

from __future__ import annotations

from typing import Any

import click

from tools.cli.core.context import client_from_config


def load_backtest_template_into_state(state, selector: str, *, source_module: str = "") -> None:
    client = client_from_config()
    templates = client.list_single_factor_setting_templates(state.factor_family)
    template_id = resolve_template_id(selector, templates)
    template = client.get_single_factor_setting_template(state.factor_family, template_id)
    snapshot = template.get("snapshot")
    if not isinstance(snapshot, dict):
        raise click.ClickException("模板缺少 snapshot")
    applied = apply_snapshot_to_backtest_state(state, snapshot, template_name=str(template.get("name") or selector))
    registered = register_template_factors(state, client)
    source = f"（来自 {source_module} 模板）" if source_module else ""
    click.echo(f"已加载模板: {template.get('name') or selector}{source}")
    factor_text = f" · 已注册因子: {registered}" if registered else ""
    click.echo(
        f"页面字段: {applied['page_settings']} · local-settings: {applied['local_settings']} "
        f"· groups: {applied['groups']} · long-short: {applied['ls_configs']} "
        f"· strategy-book: {applied['strategy_book']} · ledger-configs: {applied['ledger_configs']}{factor_text}"
    )


def save_backtest_template_from_state(state, name: str) -> None:
    snapshot = snapshot_from_backtest_state(state)
    data = client_from_config().save_single_factor_setting_template(state.factor_family, name=name, snapshot=snapshot)
    template_id = data.get("id") or ""
    state.page_settings["setting_template"] = name
    click.echo(f"已保存模板: {name}")
    if template_id:
        click.echo(f"id={template_id}")


def resolve_template_id(selector: str, templates: list[dict[str, Any]]) -> str:
    for index, template in enumerate(templates, start=1):
        keys = {str(index), str(template.get("id") or ""), str(template.get("name") or "")}
        if selector in keys:
            return str(template.get("id") or "")
    raise click.ClickException(f"找不到模板: {selector}")


def apply_snapshot_to_backtest_state(state, snapshot: dict[str, Any], *, template_name: str) -> dict[str, int]:
    factors_raw = snapshot.get("factors")
    factors: dict[str, Any] = dict(factors_raw) if isinstance(factors_raw, dict) else {}
    for key in ("factor_candidates", "factor"):
        if key in factors:
            state.page_settings[key] = factors[key]
    state.page_settings["setting_template"] = template_name

    local_settings = snapshot.get("local_settings") if isinstance(snapshot.get("local_settings"), dict) else {}
    state.backtest_local_settings = dict(local_settings or {})

    group_settings_raw = snapshot.get("group_settings")
    group_settings: dict[str, Any] = dict(group_settings_raw) if isinstance(group_settings_raw, dict) else {}
    state.backtest_groups = [
        normalize_template_group(item)
        for item in (group_settings.get("groups") or [])
        if isinstance(item, dict)
    ]
    state.backtest_ls_configs = [
        normalize_template_ls(item)
        for item in (group_settings.get("lsConfigs") or [])
        if isinstance(item, dict)
    ]
    strategy_book = snapshot.get("strategy_book")
    state.backtest_strategy_book = dict(strategy_book) if isinstance(strategy_book, dict) else {}
    ledger_configs = snapshot.get("ledger_configs")
    ledger_config_items = ledger_configs.items() if isinstance(ledger_configs, dict) else ()
    state.backtest_ledger_configs = {
        str(key): dict(value)
        for key, value in ledger_config_items
        if isinstance(value, dict)
    }
    return {
        "page_settings": len(factors) + 1,
        "local_settings": len(state.backtest_local_settings),
        "groups": len(state.backtest_groups),
        "ls_configs": len(state.backtest_ls_configs),
        "strategy_book": len(state.backtest_strategy_book.get("strategies") or {}) if state.backtest_strategy_book else 0,
        "ledger_configs": len(state.backtest_ledger_configs),
    }


def snapshot_from_backtest_state(state) -> dict[str, Any]:
    factors: dict[str, Any] = {}
    for key in ("factor_candidates", "factor", "setting_template"):
        if key in state.page_settings:
            factors[key] = state.page_settings[key]
    return {
        "factors": factors,
        "local_settings": dict(state.backtest_local_settings),
        "group_settings": {
            "groups": [dict(group) for group in state.backtest_groups],
            "lsConfigs": [dict(config) for config in state.backtest_ls_configs],
        },
        "strategy_book": dict(state.backtest_strategy_book),
        "ledger_configs": {
            str(key): dict(value)
            for key, value in state.backtest_ledger_configs.items()
        },
    }


def normalize_template_group(group: dict[str, Any]) -> dict[str, Any]:
    out = dict(group)
    rename_if_present(out, "splitCount", "split_count")
    rename_if_present(out, "groupIndex", "group_index")
    rename_if_present(out, "factorAlias", "factor")
    rename_if_present(out, "isAllGroups", "is_all_groups")
    return out


def normalize_template_ls(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config)
    rename_if_present(out, "longGroupId", "long_group_id")
    rename_if_present(out, "shortGroupId", "short_group_id")
    return out


def rename_if_present(target: dict[str, Any], old: str, new: str) -> None:
    if old in target and new not in target:
        target[new] = target[old]


def register_template_factors(state, client) -> int:
    aliases = template_factor_aliases(state)
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
        # A generic backtest draft may contain several factor families and
        # does not require the page-level ``state.factor_family`` selector.
        factor_family = alias.split("|", 1)[0]
        params = params_from_factor_alias(alias, factor_family)
        data = client.add_candidate("factor", {
            "factor_family_alias": factor_family,
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


def template_factor_aliases(state) -> list[str]:
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


def params_from_factor_alias(alias: str, factor_family: str) -> dict[str, Any]:
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
