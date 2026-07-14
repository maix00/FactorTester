"""Long-short backtest draft command handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest.shared.selectors import parse_long_short_selector


ResolveLeg = Callable[[Any, Any], dict[str, Any]]
GroupRef = Callable[[dict[str, Any]], dict[str, Any]]
PrintList = Callable[[Any], None]
ValidateSettings = Callable[[Any], None]
PrintSettingsHelp = Callable[[Any], None]


def handle_long_short_command(
    state,
    args: tuple[str, ...],
    *,
    resolve_long_leg: ResolveLeg,
    resolve_short_leg: ResolveLeg,
    group_ref: GroupRef,
    print_list: PrintList,
    validate_settings: ValidateSettings,
    print_settings_help: PrintSettingsHelp,
) -> bool:
    show_help = config_arg_helpers.has_context_help(args)
    clean_args = config_arg_helpers.strip_context_help(args)
    if config_arg_helpers.is_list_action(clean_args):
        print_list(state)
        return False
    if show_help:
        validate_settings(state)
        print_settings_help(state)
        return False
    if "--add" not in clean_args:
        raise click.ClickException("long-short 需要明确动作：list 或 --add")
    selector = parse_long_short_selector(tuple(arg for arg in clean_args if arg != "--add"))
    long_group = resolve_long_leg(state, selector.long_leg)
    short_group = resolve_short_leg(state, selector.short_leg)
    config: dict[str, Any] = {
        "name": selector.name or f"LS {long_group.get('name') or long_group.get('id')} / {short_group.get('name') or short_group.get('id')}",
        "long_group": group_ref(long_group),
        "short_group": group_ref(short_group),
    }
    state.backtest_ls_configs.append(config)
    _print_created_long_short(config)
    return True


def _print_created_long_short(config: dict[str, Any]) -> None:
    click.echo("新增 Long-Short")
    click.echo(f"名称: {config['name']}")
    long_ref = config["long_group"]
    short_ref = config["short_group"]
    click.echo(f"多头: {long_ref.get('name') or long_ref.get('id')}")
    click.echo(f"空头: {short_ref.get('name') or short_ref.get('id')}")
