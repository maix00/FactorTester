"""Argument parsing helpers for backtest configuration commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click


@dataclass(frozen=True)
class TemplateArgs:
    args: tuple[str, ...]
    factor_family: str = ""


@dataclass(frozen=True)
class HelpTarget:
    option: str
    has_value: bool


def parse_template_args(args: tuple[str, ...]) -> TemplateArgs:
    factor_family = ""
    cleaned_args: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--factor-family":
            if index + 1 < len(args):
                factor_family = str(args[index + 1])
                skip_next = True
            continue
        cleaned_args.append(arg)
    return TemplateArgs(args=tuple(cleaned_args), factor_family=factor_family)


def parse_raw_settings(args: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if "=" in token and not token.startswith("--"):
            key, value = parse_key_value(token)
            values[key] = value
            i += 1
            continue
        if not token.startswith("--"):
            raise click.ClickException(f"无法识别设置参数: {token}")
        key = token[2:].replace("-", "_")
        if not key:
            raise click.ClickException("设置字段名不能为空")
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            parsed_value: Any = True
            i += 1
        else:
            parsed_value = args[i + 1]
            i += 2
        values[key] = parsed_value
    return values


def parse_key_value(item: str) -> tuple[str, str]:
    if "=" not in item:
        raise click.ClickException("local-settings 必须使用 KEY=VALUE 格式")
    key, value = item.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException("local-settings 的 KEY 不能为空")
    return key, value.strip()


def has_context_help(args: tuple[str, ...]) -> bool:
    return "--help" in args or "-h" in args


def context_help_target(args: tuple[str, ...]) -> HelpTarget | None:
    help_positions = [index for index, token in enumerate(args) if token in {"--help", "-h"}]
    if not help_positions:
        return None
    help_index = help_positions[0]
    if help_index == 0:
        return None
    previous = args[help_index - 1]
    if previous.startswith("--"):
        return HelpTarget(previous, has_value=False)
    for index in range(help_index - 2, -1, -1):
        token = args[index]
        if token.startswith("--"):
            return HelpTarget(token, has_value=True)
    return None


def strip_context_help(args: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(arg for arg in args if arg not in {"--help", "-h"})


def is_list_action(args: tuple[str, ...]) -> bool:
    return bool(args) and args[0] == "list"


def group_action(args: tuple[str, ...]) -> str:
    if "--add" in args:
        return "add"
    if "--derive" in args:
        return "derive"
    if "--copy" in args:
        return "copy"
    if "--edit" in args:
        return "edit"
    if "--describe" in args:
        return "describe"
    if "--run" in args:
        return "run"
    return ""


def strip_group_action_args(args: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    removed_action_add = False
    for arg in args:
        if arg == "--add" and not removed_action_add:
            removed_action_add = True
            continue
        if arg in {"--edit", "--describe", "--run", "--batch", "--derive", "--copy"}:
            continue
        result.append(arg)
    return tuple(result)


def group_names_from_args(args: tuple[str, ...]) -> list[str]:
    names: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--group-name", "--group_name"}:
            names.append(require_arg_value(args, i, token))
            i += 2
            continue
        if token in {"--group-names", "--group_names"}:
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                names.append(args[i])
                i += 1
            continue
        i += 1
    return names


def require_arg_value(args: tuple[str, ...], index: int, option: str) -> str:
    if index + 1 >= len(args) or args[index + 1].startswith("--"):
        raise click.ClickException(f"{option} 缺少参数")
    return args[index + 1]


def split_selector_and_local_setting_args(args: tuple[str, ...], *, selector_roots: set[str]) -> tuple[list[str], list[str]]:
    selector_args: list[str] = []
    setting_args: list[str] = []
    selector_mode = False
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--add":
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


def remove_group_name_args(args: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in {"--group-name", "--group_name"}:
            i += 2
            continue
        if token in {"--group-names", "--group_names"}:
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                i += 1
            continue
        result.append(token)
        i += 1
    return tuple(result)


def parse_ledger_config_args(args: tuple[str, ...], *, arg_value, parse_raw_settings) -> dict[str, Any]:
    values: dict[str, Any] = {}
    string_fields = {
        "--fee-mode": "fee_mode",
        "--transaction-fee-source": "transaction_fee_source",
        "--margin-mode": "margin_mode",
        "--margin-call-mode": "margin_call_mode",
        "--accounting-mode": "accounting_mode",
        "--cost-basis-method": "cost_basis_method",
        "--tradability-policy": "tradability_policy",
        "--clearing-rounding-policy": "clearing_rounding_policy",
    }
    float_fields = {
        "--fixed-fee-rate": "fixed_fee_rate",
        "--fixed-margin-ratio": "fixed_margin_ratio",
        "--liquidation-target-buffer": "liquidation_target_buffer",
        "--cash-reserve-ratio": "cash_reserve_ratio",
        "--cash-reserve-major": "cash_reserve_major",
    }
    bool_fields = {
        "--daily-mark-to-market-enabled": "daily_mark_to_market_enabled",
        "--use-int-position": "use_int_position",
    }
    for flag, key in string_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = value
    for flag, key in float_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = float(value)
    for flag, key in bool_fields.items():
        value = arg_value(args, flag)
        if value:
            values[key] = parse_bool(value, flag)
    extra = parse_raw_settings(tuple(strip_known_ledger_config_args(args)))
    values.update(extra)
    return values


def strip_known_ledger_config_args(args: tuple[str, ...]) -> list[str]:
    known_with_value = {
        "--ledger",
        "--fee-mode",
        "--transaction-fee-source",
        "--fixed-fee-rate",
        "--margin-mode",
        "--fixed-margin-ratio",
        "--margin-call-mode",
        "--liquidation-target-buffer",
        "--accounting-mode",
        "--daily-mark-to-market-enabled",
        "--cost-basis-method",
        "--use-int-position",
        "--tradability-policy",
        "--clearing-rounding-policy",
        "--cash-reserve-ratio",
        "--cash-reserve-major",
    }
    result: list[str] = []
    i = 0
    while i < len(args):
        if args[i] in known_with_value:
            i += 2
            continue
        result.append(args[i])
        i += 1
    return result


def set_optional_float_arg(target: dict[str, Any], args: tuple[str, ...], flag: str, key: str, *, arg_value) -> None:
    value = arg_value(args, flag)
    if value:
        target[key] = float(value)


def parse_bool(value: str, flag: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise click.ClickException(f"{flag} 需要布尔值: {value}")
