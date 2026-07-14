"""Backtest group command orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest.shared.selectors import parse_add_group_selectors


PrintState = Callable[[Any], None]
PrintFieldHelp = Callable[[Any, str], None]
ValidateSettings = Callable[[Any, dict[str, Any]], None]
PrintSettingsHelp = Callable[..., None]
ParseGroupAddSelectors = Callable[..., list[Any]]
AppendGroup = Callable[..., None]
SelectedGroups = Callable[..., list[dict[str, Any]]]
EditGroup = Callable[..., None]
DeriveOrCopyGroups = Callable[..., list[dict[str, Any]]]
PrintGroup = Callable[[dict[str, Any]], None]
RunBacktest = Callable[..., None]


def handle_group_command(
    state,
    raw_args: tuple[str, ...],
    *,
    selector_roots: set[str],
    print_group_list: PrintState,
    print_group_field_help: PrintFieldHelp,
    print_group_batch_help: Callable[[], None],
    validate_settings: ValidateSettings,
    print_settings_help: PrintSettingsHelp,
    parse_group_add_selectors: ParseGroupAddSelectors,
    append_group: AppendGroup,
    selected_groups: SelectedGroups,
    edit_group: EditGroup,
    derive_or_copy_groups: DeriveOrCopyGroups,
    print_group: PrintGroup,
    run_backtest: RunBacktest,
) -> bool:
    show_help = config_arg_helpers.has_context_help(raw_args)
    verbose = "--verbose" in raw_args
    args = tuple(arg for arg in raw_args if arg != "--verbose")
    help_target = config_arg_helpers.context_help_target(args)
    clean_args = config_arg_helpers.strip_context_help(args)
    if config_arg_helpers.is_list_action(clean_args):
        print_group_list(state)
        return False
    action = config_arg_helpers.group_action(clean_args)
    selector_args, setting_args = config_arg_helpers.split_selector_and_local_setting_args(
        config_arg_helpers.strip_group_action_args(clean_args),
        selector_roots=selector_roots,
    )
    group_settings = config_arg_helpers.parse_raw_settings(tuple(setting_args)) if setting_args else {}
    if show_help and help_target and not help_target.has_value:
        print_group_field_help(state, help_target.option, batch="--batch" in clean_args)
        return False
    if show_help:
        validate_settings(state, group_settings)
        if action == "add" and "--batch" in clean_args:
            print_group_batch_help()
        else:
            print_settings_help(state, values=group_settings)
        return False
    if action == "add":
        _handle_add(
            state,
            selector_args=selector_args,
            group_settings=group_settings,
            batch="--batch" in clean_args,
            parse_group_add_selectors=parse_group_add_selectors,
            append_group=append_group,
            print_group=print_group,
        )
    elif action == "edit":
        _handle_edit(
            state,
            clean_args=clean_args,
            selector_args=selector_args,
            group_settings=group_settings,
            selected_groups=selected_groups,
            edit_group=edit_group,
            print_group=print_group,
        )
    elif action in {"derive", "copy"}:
        created = derive_or_copy_groups(
            state,
            clean_args,
            selectors_args=tuple(selector_args),
            extra_values=group_settings,
            derived=action == "derive",
        )
        click.echo(f"新增{'派生' if action == 'derive' else '复制'}分组: {len(created)}")
        for group_item in created:
            print_group(group_item)
    elif action == "describe":
        for group_item in selected_groups(state, clean_args):
            print_group(group_item)
    elif action == "run":
        run_backtest(state, groups=selected_groups(state, clean_args, default_all=True), verbose=verbose)
    else:
        raise click.ClickException("group 需要明确动作：list、--add、--edit、--describe 或 --run")
    if action == "add":
        click.echo("下一步: 这些参数会进入 backtest/group-test 的配置草稿；运行接口接好后可直接提交。")
    return True


def _handle_add(
    state,
    *,
    selector_args: list[str],
    group_settings: dict[str, Any],
    batch: bool,
    parse_group_add_selectors: ParseGroupAddSelectors,
    append_group: AppendGroup,
    print_group: PrintGroup,
) -> None:
    selectors_list = parse_group_add_selectors(tuple(selector_args), batch=batch)
    for selectors in selectors_list:
        append_group(state, selectors=selectors, extra_values=group_settings)
    click.echo(f"新增分组: {len(selectors_list)}")
    for group_item in state.backtest_groups[-len(selectors_list):]:
        print_group(group_item)


def _handle_edit(
    state,
    *,
    clean_args: tuple[str, ...],
    selector_args: list[str],
    group_settings: dict[str, Any],
    selected_groups: SelectedGroups,
    edit_group: EditGroup,
    print_group: PrintGroup,
) -> None:
    groups = selected_groups(state, clean_args)
    selectors = parse_add_group_selectors(config_arg_helpers.remove_group_name_args(tuple(selector_args)))
    for group_item in groups:
        edit_group(state, group_item, selectors=selectors, extra_values=group_settings)
    click.echo(f"已修改分组: {len(groups)}")
    for group_item in groups:
        print_group(group_item)
