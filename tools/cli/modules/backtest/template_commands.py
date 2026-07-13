"""Backtest template command handlers."""

from __future__ import annotations

from datetime import datetime

import click

from tools.cli.core.context import client_from_config
from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest import config_views as config_view_formatter
from tools.cli.modules.backtest import template_state as template_state_helpers


def handle_template_command(state, raw_args: tuple[str, ...]) -> bool:
    parsed_args = config_arg_helpers.parse_template_args(raw_args)
    args = parsed_args.args
    source_module = ""
    if parsed_args.factor_family:
        state.factor_family = parsed_args.factor_family

    if args[:1] == ("--from-module-template",):
        if len(args) < 3:
            raise click.ClickException("--from-module-template 需要模块名和动作，例如: --from-module-template single_factor_test load <模板>")
        source_module = args[1]
        if source_module not in {"single_factor_test", "single_factor_family_test"}:
            raise click.ClickException(f"暂不支持从该模块模板导入: {source_module}")
        args = args[2:]
    if not args or args[0] in {"help", "--help", "-h"}:
        print_template_help(state)
        return False
    if not state.factor_family:
        raise click.ClickException("template 命令需要先选择因子家族，例如加上 --factor-family SgCCS")
    if args[0] in {"list", "ls"}:
        list_templates(state.factor_family)
        return False
    if args[0] == "load":
        if len(args) < 2:
            raise click.ClickException("template load 需要模板 ID 或名称")
        template_state_helpers.load_backtest_template_into_state(state, args[1], source_module=source_module)
        return True
    if args[0] == "save":
        name = args[1] if len(args) >= 2 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        template_state_helpers.save_backtest_template_from_state(state, name)
        return True
    raise click.ClickException("template 支持的动作: list, load, save, help")


def print_template_help(state) -> None:
    for line in config_view_formatter.template_help_lines(state.factor_family):
        click.echo(line)


def list_templates(factor_family: str) -> None:
    templates = client_from_config().list_single_factor_setting_templates(factor_family)
    click.echo(f"{factor_family} 模板列表")
    if not templates:
        click.echo("  （空）")
        return
    for index, template in enumerate(templates, start=1):
        click.echo(f"  {index}. {template.get('name') or template.get('id')} · id={template.get('id')}")
