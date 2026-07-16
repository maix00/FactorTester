"""Generic backtest CLI controller.

The single-factor-family page currently exposes a `group_test` module key from
the backend.  CLI users should enter the generic `backtest` controller; this
adapter maps that public command to the backend group-test application.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

import click

from tools.cli.core.context import client_from_config, ensure_child_available
from tools.cli.core.errors import friendly_errors
from tools.cli.modules.keys import BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY
from tools.cli.modules.backtest.audit_formatters import delta_tables as delta_table_formatter
from tools.cli.modules.backtest.audit_formatters import display_values as display_value_formatter
from tools.cli.modules.backtest.audit_formatters import events as events_formatter
from tools.cli.modules.backtest.audit_formatters import execution_prices as execution_price_formatter
from tools.cli.modules.backtest.audit_formatters import field_metadata as field_metadata_formatter
from tools.cli.modules.backtest.audit_formatters import ledger as ledger_formatter
from tools.cli.modules.backtest.audit_formatters import market_data as market_data_formatter
from tools.cli.modules.backtest.audit_formatters import orders as orders_formatter
from tools.cli.modules.backtest.audit_formatters import printer_helpers as audit_printer_helpers
from tools.cli.modules.backtest.audit_formatters import run_window as run_window_formatter
from tools.cli.modules.backtest.audit_formatters import samples as samples_formatter
from tools.cli.modules.backtest.audit_formatters import sections as audit_sections
from tools.cli.modules.backtest.audit_formatters import source_groups as source_group_formatter
from tools.cli.modules.backtest.audit_formatters import step_display as step_display_formatter
from tools.cli.modules.backtest.audit_formatters import strategy as strategy_formatter
from tools.cli.modules.backtest.audit_formatters import table_render as table_render_formatter
from tools.cli.modules.backtest.audit_formatters import trade_intents as trade_intent_formatter
from tools.cli.modules.backtest.audit_formatters import value_text as value_text_formatter
from tools.cli.modules.backtest import run_stream
from tools.cli.modules.backtest import step_runtime
from tools.cli.modules.research_metadata import attach_research_metadata
from tools.testers.backtest.engines.native.flow import phase_label

_audit_field_state_product_filter: tuple[str, ...] = ()
_audit_strategy_ledger_routes: dict[str, tuple[tuple[str, str], ...]] = {}
_audit_short_alias_map: dict[str, str] = {}
_audit_runtime_strategy_aliases: dict[str, str] = {}


def _strip_ansi(value: object) -> str:
    return table_render_formatter.strip_ansi(value)


def _audit_display_width(value: object) -> int:
    return table_render_formatter.display_width_text(value)


@contextlib.contextmanager
def _audit_step_event_context(data: dict[str, Any], short_alias_map: dict[str, str] | None = None):
    global _audit_field_state_product_filter, _audit_strategy_ledger_routes
    global _audit_short_alias_map, _audit_runtime_strategy_aliases
    previous_filter = _audit_field_state_product_filter
    previous_routes = _audit_strategy_ledger_routes
    previous_alias_map = _audit_short_alias_map
    previous_runtime_aliases = _audit_runtime_strategy_aliases
    _audit_field_state_product_filter = _audit_event_product_filter(data)
    _audit_strategy_ledger_routes = _audit_strategy_routes(data)
    _audit_short_alias_map = short_alias_map or {}
    _audit_runtime_strategy_aliases = _audit_runtime_strategy_aliases_for_event(data, _audit_short_alias_map)
    try:
        yield
    finally:
        _audit_field_state_product_filter = previous_filter
        _audit_strategy_ledger_routes = previous_routes
        _audit_short_alias_map = previous_alias_map
        _audit_runtime_strategy_aliases = previous_runtime_aliases


def _audit_strategy_routes(data: dict[str, Any]) -> dict[str, tuple[tuple[str, str], ...]]:
    return events_formatter.strategy_routes(data)


def _audit_event_product_filter(data: dict[str, Any]) -> tuple[str, ...]:
    return events_formatter.event_product_filter(data)


def _audit_runtime_strategy_aliases_for_event(
    data: dict[str, Any],
    short_alias_map: dict[str, str],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for strategy in data.get("strategies") or []:
        if not isinstance(strategy, dict):
            continue
        label = step_display_formatter.active_strategy_short_alias(strategy, short_alias_map=short_alias_map)
        for key in ("strategy", "id", "strategy_id", "group_id", "alias", "name", "shortAlias", "short_alias"):
            raw = str(strategy.get(key) or "").strip()
            if raw:
                aliases[raw] = label
    for strategy_label, routes in _audit_strategy_ledger_routes.items():
        label = short_alias_map.get(strategy_label, strategy_label)
        aliases[strategy_label] = label
        for ledger_id, cash_pool in routes:
            for route_part in (ledger_id, cash_pool):
                text = str(route_part or "").strip()
                if not text:
                    continue
                aliases[text] = label
                if ":" in text:
                    aliases[text.split(":", 1)[1]] = label
    return aliases


def _audit_order_strategy_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in _audit_runtime_strategy_aliases:
        return _audit_runtime_strategy_aliases[text]
    if text in _audit_short_alias_map:
        return _audit_short_alias_map[text]
    prefix = text.split(":", 1)[0]
    if prefix in _audit_runtime_strategy_aliases:
        return _audit_runtime_strategy_aliases[prefix]
    return text


def _pad_audit_cell(value: object, width: int) -> str:
    return table_render_formatter.pad_cell(value, width)


def _audit_change_cell(before: Any, after: Any) -> str:
    return "\n".join(_audit_change_highlight_content(line) for line in f"{before} -> {after}".splitlines())


def _audit_change_prefix(before: Any) -> str:
    return _audit_change_highlight(f"{before} ->")


def _audit_change_highlight(text: str) -> str:
    return click.style(text, fg="black", bg="bright_yellow")


def _audit_badge_highlight(text: str) -> str:
    return f"\x1b[30m\x1b[48;2;255;238;246m{text}\x1b[0m"


def _audit_change_highlight_content(line: str) -> str:
    leading_width = len(line) - len(line.lstrip(" "))
    leading = line[:leading_width]
    content = line[leading_width:]
    if not content:
        return leading
    return leading + _audit_change_highlight(content)


def _audit_scalar_sequence_text(value: list[Any] | tuple[Any, ...], *, width: int = 72) -> str:
    return value_text_formatter.scalar_sequence_text(value, width=width)


_AuditSamplePart = samples_formatter.AuditSamplePart


def _audit_select_sample_part(sample: dict[str, Any], predicate) -> _AuditSamplePart | None:
    return samples_formatter.select_sample_part(sample, predicate)


def _audit_sample_note_lines(sample: dict[str, Any], selected_name: str) -> list[str]:
    return samples_formatter.sample_note_lines(sample, selected_name)


def _audit_single_sample_sequence(items: list[Any]) -> tuple[list[Any], list[str]]:
    return samples_formatter.single_sample_sequence(items)


def _audit_single_sample_frame(frame: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    return samples_formatter.single_sample_frame(frame)


def _audit_single_sample_series(series: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    return samples_formatter.single_sample_series(series)

_field_metadata = field_metadata_formatter.load_field_metadata()
_field_display_offsets = _field_metadata.display_offsets


def _flabel(name: str) -> str:
    return _field_metadata.label(name)


from tools.cli.modules.backtest.run_output import BacktestRunRenderer
from tools.cli.modules.backtest import result_output as result_output_formatter
from tools.cli.modules.backtest import results_data as results_data_formatter
from tools.cli.modules.backtest import results_commands as results_command_handlers
from tools.cli.modules.backtest import root_command as root_command_handler
from tools.cli.modules.backtest import run_payloads as run_payload_formatter
from tools.cli.modules.backtest import run_config as run_config_helpers
from tools.cli.modules.backtest import config_args as config_arg_helpers
from tools.cli.modules.backtest import config_state as config_state_helpers
from tools.cli.modules.backtest import config_commands as config_command_handlers
from tools.cli.modules.backtest import compare_commands as compare_command_handlers
from tools.cli.modules.backtest import group_commands as group_command_handlers
from tools.cli.modules.backtest import group_state as group_state_helpers
from tools.cli.modules.backtest import long_short_commands as long_short_command_handlers
from tools.cli.modules.backtest import template_commands as template_command_handlers
from tools.cli.modules.backtest import template_state as template_state_helpers
from tools.cli.state import BACKTEST_SPACE, load_state, save_state, switch_backtest_space


SELECTOR_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True}
SELECTOR_HELP_CONTEXT = {"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}
_ADD_GROUP_SELECTOR_ROOTS = {
    "--add", "--batch",
    "--derive", "--copy",
    "--group-name", "--group_name",
    "--group-names", "--group_names",
    "--factor-family", "--factor_family",
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
@click.option("--run", is_flag=True, help="运行当前 backtest 草稿中的全部策略。")
@click.option("--step", is_flag=True, help="单步调试模式：每步暂停，按 Enter 继续，显示每个 Flow 的处理和字段变更。")
@click.option("--verbose", is_flag=True, help="运行时打印完整 SSE 进度事件摘要。")
@click.pass_context
@friendly_errors
def backtest(
    ctx: click.Context,
    run: bool,
    step: bool,
    verbose: bool,
) -> None:
    """进入通用回测控制界面。

    \b
    回测与 single_factor_test 平行注册；因子家族在具体需要因子的动作中指定:
      factortester backtest group --add --factor-family SgCCS --factor 'SgCCS|N:2m|$F:1m|$Rev'

    \b
    常用草稿命令:
      factortester backtest local-settings --allocation-mode equal_notional
      factortester backtest local-settings --liquidity-mode infinite
      factortester backtest local-settings --liquidity-mode volume_participation --participation-rate 0.02
      factortester backtest group --add --group-name A1 --split-count 5 --group-index 1 --factor-family SgCCS
      factortester backtest group --add --factor-family SgCCS --factor --alias 'SgCCS|N:2m|$F:1m|$Rev'
      factortester backtest group --add --factor-family SgCCS --factor add --param N=2m --param '$Rev=1'
      factortester backtest group --add --product-group from-candidates --name 中国期货日盘
      factortester backtest group --group-name A1 --derive --group-name A1a --product-path ...
      factortester backtest group --group-name A1 --copy --group-name A1-copy
      factortester backtest long-short --add --ls-name LS-A1-A5 --long-group A1 --short-group A5
      factortester backtest strategy-book ledger --strategy A1 --ledger shared --cash-pool pool-main
      factortester backtest ledger-config --ledger shared --fee-mode auto --margin-mode auto
      factortester backtest ledger-config --ledger private:A1 --margin-mode none
      factortester backtest compare volume-capacity-margin --volume-rate 0.02
      factortester backtest template --from-module-template single_factor_test load "2026-06-02 07:20:47"
      factortester backtest template save "CLI 草稿"
      factortester backtest clear

    \b
    字段级帮助:
      factortester group --add --group-name --help
      factortester group --add --group-name A1 --help
    """
    root_command_handler.handle_root_command(
        ctx,
        run=run,
        step=step,
        verbose=verbose,
        run_backtest=_run_backtest,
        enter_state=enter_backtest_state,
    )


@backtest.command("template", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def template(ctx: click.Context) -> None:
    """管理 backtest 设置模板的便捷入口。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    changed = template_command_handlers.handle_template_command(state, tuple(ctx.args))
    if changed:
        save_state(state)


@backtest.command("local-settings", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def local_settings(ctx: click.Context) -> None:
    """配置回测 local-settings。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    changed = config_command_handlers.handle_local_settings_command(
        state,
        tuple(ctx.args),
        apply_raw_settings=_apply_raw_local_settings,
        validate_registered_settings=_validate_registered_local_settings,
        print_settings_help=config_command_handlers.print_settings_help,
        print_local_settings=config_command_handlers.print_local_settings,
    )
    if changed:
        save_state(state)


@backtest.command("compare", context_settings=SELECTOR_HELP_CONTEXT)
@click.option("--volume-rate", type=float, default=0.02, show_default=True, help="成交量容量限制场景的参与率。")
@click.option("--factor-family", default="", help="因子家族名；factor-grid 未传时使用当前上下文。")
@click.option("--n", "n_values", multiple=True, help="N 参数候选，可重复。默认: 1m,2m,3m,5m,10m")
@click.option("--f", "f_values", multiple=True, help="$F 参数候选，可重复。默认: 1m")
@click.option("--product-group", "product_groups", multiple=True, help="产品组候选名称，可重复。默认继承当前草稿。")
@click.option("--rev/--no-rev", default=True, show_default=True, help="是否使用 $Rev 标志。")
@click.option("--top", type=int, default=12, show_default=True, help="factor-grid 摘要显示前 N 个结果。")
@click.option(
    "--volume-capacity-mode",
    "--liquidity-mode",
    "liquidity_mode",
    type=click.Choice(["inherit", "infinite", "volume_participation"]),
    default="inherit",
    show_default=True,
    help="factor-grid 覆盖成交量容量模式；--liquidity-mode 是旧别名。",
)
@click.option("--participation-rate", type=float, default=None, help="factor-grid 成交量参与率；默认沿用 --volume-rate。")
@click.option("--verbose", is_flag=True, help="运行时打印完整 SSE 进度事件摘要。")
@click.pass_context
@friendly_errors
def compare(
    ctx: click.Context,
    volume_rate: float,
    factor_family: str,
    n_values: tuple[str, ...],
    f_values: tuple[str, ...],
    product_groups: tuple[str, ...],
    rev: bool,
    top: int,
    liquidity_mode: str,
    participation_rate: float | None,
    verbose: bool,
) -> None:
    """在一次 backend run 中克隆当前草稿，批量对比关键执行/保证金场景。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    compare_command_handlers.handle_compare_command(
        state,
        tuple(ctx.args),
        volume_rate=volume_rate,
        factor_family=factor_family,
        n_values=n_values,
        f_values=f_values,
        product_groups=product_groups,
        rev=rev,
        top=top,
        liquidity_mode=liquidity_mode,
        participation_rate=participation_rate,
        verbose=verbose,
        run_backtest=_run_backtest,
    )


@backtest.command("strategy-book", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def strategy_book(ctx: click.Context) -> None:
    """配置 strategy -> ledger -> cash pool 拓扑。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    changed = config_command_handlers.handle_strategy_book_command(
        state,
        tuple(ctx.args),
        arg_value=_arg_value,
    )
    if changed:
        save_state(state)


@backtest.command("ledger-config", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def ledger_config(ctx: click.Context) -> None:
    """配置 ledger-owned 字段，如费用、保证金、DMTM、现金保留。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    changed = config_command_handlers.handle_ledger_config_command(
        state,
        tuple(ctx.args),
        arg_value=_arg_value,
    )
    if changed:
        save_state(state)


@backtest.command("clear")
@click.option("--page-settings", is_flag=True, help="同时清空 single_factor_test 页面级设置。")
@friendly_errors
def clear(page_settings: bool) -> None:
    """清空当前 backtest 配置草稿。"""
    state = load_state()
    switch_backtest_space(state, BACKTEST_SPACE)
    config_command_handlers.handle_clear_command(state, page_settings=page_settings)
    save_state(state)


@backtest.command("results", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def results(ctx: click.Context) -> None:
    """查看最近一次 backtest 运行结果。

    \b
    常用命令:
      factortester backtest results summary
      factortester backtest results equity
      factortester backtest results attribution --group-name A1:1 --by product
      factortester backtest results detail --group-name A1
      factortester backtest results ranking
      factortester backtest results snapshot --index 1
      factortester backtest results order-flow --group-name A1

    所有 results 子命令都支持:
      --output PATH     同时写入文件
      --no-terminal    只写文件，不打印到终端
      --append         追加写入文件
    """
    state = load_state()
    output_options, args = _parse_result_output_options(tuple(ctx.args))
    if not args or args[0] in {"help", "--help", "-h"}:
        results_command_handlers.print_results_help()
        return
    action = args[0]
    _emit_result_output(
        output_options,
        lambda: results_command_handlers.dispatch_stored_result_command(state, action, args[1:]),
    )


def _ensure_active_backtest_scope(state) -> None:
    if state.current_parent not in {BACKTEST_BACKEND_KEY, BACKTEST_PUBLIC_KEY}:
        enter_backtest_state(state, scope=BACKTEST_SPACE)


@backtest.command("group", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def group(
    ctx: click.Context,
) -> None:
    """管理回测分组草稿。

    常用动作:

      factortester group list
      factortester group --add --group-name A1 --split-count 5 --group-index 1
      factortester group --add --batch --group-names A1 A2 A3 A4 A5 --split-count 5
      factortester group --group-name A1 --edit --factor --alias SgCCS|N:2m
      factortester group --group-name A1 --derive --group-name A1a
      factortester group --group-name A1 --copy --group-name A1-copy
      factortester group --group-names A1 A5 --edit --allocation-policy equal_notional
      factortester group --group-name A1 --describe
      factortester group --group-name A1 --run

    字段说明模式:

      factortester group --add --group-name --help
      factortester group --add --batch --help

    上下文校验模式:

      factortester group --add --group-name A1 --help
    """
    state = load_state()
    _ensure_active_backtest_scope(state)
    changed = group_command_handlers.handle_group_command(
        state,
        tuple(ctx.args),
        selector_roots=_ADD_GROUP_SELECTOR_ROOTS,
        print_group_list=config_command_handlers.print_group_list,
        print_group_field_help=config_command_handlers.print_group_field_help,
        print_group_batch_help=config_command_handlers.print_group_batch_help,
        validate_settings=_validate_settings_dict,
        print_settings_help=config_command_handlers.print_settings_help,
        parse_group_add_selectors=group_state_helpers.parse_group_add_selectors,
        append_group=group_state_helpers.append_group,
        selected_groups=group_state_helpers.selected_groups,
        edit_group=group_state_helpers.edit_group,
        derive_or_copy_groups=group_state_helpers.derive_or_copy_groups,
        print_group=config_command_handlers.print_group_detail,
        run_backtest=_run_backtest,
    )
    if changed:
        save_state(state)


@backtest.command("long-short", context_settings=SELECTOR_HELP_CONTEXT)
@click.pass_context
@friendly_errors
def long_short(ctx: click.Context) -> None:
    """管理 Long-Short 策略草稿。"""
    state = load_state()
    _ensure_active_backtest_scope(state)
    changed = long_short_command_handlers.handle_long_short_command(
        state,
        tuple(ctx.args),
        resolve_long_leg=lambda current_state, leg: group_state_helpers.resolve_ls_leg(current_state, leg, side="long"),
        resolve_short_leg=lambda current_state, leg: group_state_helpers.resolve_ls_leg(current_state, leg, side="short"),
        group_ref=group_state_helpers.group_ref,
        print_list=config_command_handlers.print_long_short_list,
        validate_settings=_validate_registered_local_settings,
        print_settings_help=config_command_handlers.print_settings_help,
    )
    if changed:
        save_state(state)


def enter_backtest_state(state, *, scope: str = BACKTEST_SPACE) -> None:
    switch_backtest_space(state, scope)
    if state.current_parent == "single_factor_family_test":
        ensure_child_available(state.current_parent, BACKTEST_BACKEND_KEY)
        state.enter(BACKTEST_BACKEND_KEY)
        return
    ensure_child_available(None, BACKTEST_PUBLIC_KEY)
    state.enter(BACKTEST_PUBLIC_KEY)


def _apply_raw_local_settings(state, args: tuple[str, ...]) -> None:
    state.backtest_local_settings.update(config_arg_helpers.parse_raw_settings(args))


def _validate_registered_local_settings(state) -> None:
    _validate_settings_dict(state, state.backtest_local_settings, prefix="local-settings")


def _validate_settings_dict(state, values: dict[str, Any], *, prefix: str = "设置") -> None:
    _, store = config_state_helpers.stores_for_backtest(state)
    unknown = [key for key in values if key not in store.defaults]
    if unknown:
        raise click.ClickException(f"{prefix} 包含未注册字段: " + ", ".join(sorted(unknown)))
    for key, value in values.items():
        try:
            store.validate_value(key, value)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None


def _strategy_book_payload(state) -> dict[str, Any]:
    return config_state_helpers.strategy_book_payload(state)


def _audit_text(value: Any) -> str:
    return display_value_formatter.audit_text(
        value,
        compact=_compact_audit_display_aliases,
        special=_audit_special_text,
        pandas=_audit_pandas_text,
        table_formatters=[
            _audit_event_draft_table_text,
            _audit_event_payload_table_text,
            _audit_order_table_text,
            _audit_sequence_mapping_table_text,
            _audit_mapping_table_text,
        ],
        json_dumps=_audit_json_text,
    )


def _audit_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _audit_special_text(value: Any) -> str | None:
    return display_value_formatter.backtest_special_text(
        value,
        positions_text=_audit_positions_text,
        trade_intent_text=_audit_trade_intent_text,
        trading_day_resolver_text=_audit_trading_day_resolver_text,
        contract_metadata_text=_audit_contract_metadata_text,
        price_tables_text=_audit_price_tables_text,
        market_data_load_plan_text=_audit_market_data_load_plan_text,
        market_data_excluded_products_text=_audit_market_data_excluded_products_text,
        run_window_text=_audit_run_window_text,
        historical_field_state_text=_audit_historical_field_state_text,
    )


def _audit_event_draft_table_text(value: Any) -> str | None:
    if isinstance(value, dict):
        return _audit_event_draft_sample_table_text(value)
    return events_formatter.event_draft_table_text(
        value,
        table_lines=_audit_table_lines,
        table_cell_is_complex=_audit_table_cell_is_complex,
        notice_scalar=_audit_notice_scalar,
    )


def _audit_event_draft_diff_table_text(before: Any, after: Any) -> str | None:
    return events_formatter.event_draft_diff_table_text(
        before,
        after,
        table_lines=_audit_table_lines,
        table_cell_is_complex=_audit_table_cell_is_complex,
        notice_scalar=_audit_notice_scalar,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
        highlight_cell=_audit_change_highlight_content,
    )


def _audit_event_draft_sample_table_text(value: dict[str, Any]) -> str | None:
    return events_formatter.event_draft_sample_table_text(
        value,
        table_lines=_audit_table_lines,
        table_cell_is_complex=_audit_table_cell_is_complex,
        notice_scalar=_audit_notice_scalar,
        select_sample_part=_audit_select_sample_part,
        sample_note_lines=_audit_sample_note_lines,
        single_sample_sequence=_audit_single_sample_sequence,
    )


def _audit_notice_scalar(value: Any) -> str:
    return events_formatter.notice_scalar(value, audit_text=_audit_text)


def _audit_trading_day_resolver_text(value: dict[str, Any]) -> str:
    return events_formatter.trading_day_resolver_text(
        value,
        select_sample_part=_audit_select_sample_part,
        sample_note_lines=_audit_sample_note_lines,
        single_sample_frame=_audit_single_sample_frame,
        dataframe_table_lines=_audit_dataframe_table_lines,
    )


def _audit_event_payload_table_text(value: Any) -> str | None:
    return events_formatter.event_payload_table_text(value, table_lines=_audit_table_lines)


def _audit_order_table_text(value: Any) -> str | None:
    return orders_formatter.order_table_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        strategy_label=_audit_order_strategy_label,
        select_sample_part=_audit_select_sample_part,
        sample_note_lines=_audit_sample_note_lines,
        single_sample_sequence=_audit_single_sample_sequence,
    )


def _audit_order_diff_text(before: Any, after: Any) -> str | None:
    return orders_formatter.order_diff_text(
        before,
        after,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
        highlight_cell=_audit_change_highlight_content,
        strategy_label=_audit_order_strategy_label,
    )


def _audit_trade_intent_text(value: dict[str, Any]) -> str:
    return trade_intent_formatter.trade_intent_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
    )


def _audit_strategy_change_label(change: dict[str, Any]) -> str:
    strategy = change.get("strategy")
    if strategy not in (None, ""):
        return str(strategy)
    strategies = change.get("strategies")
    if isinstance(strategies, list) and strategies:
        return ", ".join(str(item) for item in strategies)
    return source_group_formatter.source_group_label([change])


def _print_weight_change_tables(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    lines = trade_intent_formatter.weight_change_lines_from_changes(
        field_name,
        changes,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        strategy_label=_audit_strategy_change_label,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
        display_key=_audit_display_key,
        indent=prefix,
    )
    if lines is None:
        return False
    for line in lines:
        click.echo(line)
    return True


def _print_lifecycle_notice_change(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    diff = events_formatter.lifecycle_notice_change_diff(
        field_name,
        changes,
        display_field_value=_display_field_value,
        dedupe=_dedupe_audit_list,
    )
    if diff is None:
        return False
    label, before, after = diff
    _print_audit_diff_value(prefix, label, before, after)
    return True


_ORDER_DELTA_FIELD_NAMES = delta_table_formatter.ORDER_DELTA_FIELD_NAMES


def _print_delta_mapping_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = delta_table_formatter.delta_value_table(
        field_name,
        values,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        strategy_ledger_routes=_audit_strategy_ledger_routes,
        scalar_cell=_audit_scalar_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


def _print_delta_mapping_value_tables(prefix: str, records: list[dict[str, Any]]) -> bool:
    result = delta_table_formatter.combined_delta_value_table(
        records,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        strategy_ledger_routes=_audit_strategy_ledger_routes,
        scalar_cell=_audit_scalar_cell,
    )
    if result is None:
        click.echo(f"{prefix}当前市场快照总表:")
        for line in audit_printer_helpers.combined_field_label_lines(prefix, records):
            click.echo(line, color=True)
        click.echo(f"{prefix}  （当前无市场快照值）")
        return True
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
    )


def _print_delta_mapping_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = delta_table_formatter.delta_change_table(
        field_name,
        changes,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        strategy_ledger_routes=_audit_strategy_ledger_routes,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    if not rows:
        click.echo(f"{prefix}（无变化）")
        return True
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


def _print_delta_mapping_change_tables(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    result = delta_table_formatter.combined_delta_change_table(
        records,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        strategy_ledger_routes=_audit_strategy_ledger_routes,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    if not rows:
        click.echo(f"{prefix}（无变化）")
        return True
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
    )


def _print_order_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    orders: list[Any] = []
    for entry in values:
        value = _display_field_value(field_name, entry.get("value"))
        if isinstance(value, list):
            orders.extend(value)
        elif value not in (None, ""):
            orders.append(value)
    text = _audit_order_table_text(orders)
    if text is None:
        return False
    click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
    for line in text.splitlines():
        click.echo(f"{prefix}  {line}", color=True)
    return True


def _print_order_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    before_orders: list[Any] = []
    after_orders: list[Any] = []
    for change in changes:
        before = _display_field_value(field_name, change.get("before"))
        after = _display_field_value(field_name, change.get("after"))
        if isinstance(before, list):
            before_orders.extend(before)
        elif before not in (None, ""):
            before_orders.append(before)
        if isinstance(after, list):
            after_orders.extend(after)
        elif after not in (None, ""):
            after_orders.append(after)
    text = _audit_order_diff_text(before_orders, after_orders)
    if text is None:
        return False
    click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
    for line in text.splitlines():
        click.echo(f"{prefix}  {line}", color=True)
    return True


def _print_execution_price_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = execution_price_formatter.value_table(
        field_name,
        values,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


def _print_execution_price_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = execution_price_formatter.change_table(
        field_name,
        changes,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


def _print_event_draft_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    drafts: list[Any] = []
    for entry in values:
        value = _display_field_value(field_name, entry.get("value"))
        if isinstance(value, list):
            drafts.extend(value)
        elif value not in (None, ""):
            drafts.append(value)
    text = _audit_event_draft_table_text(drafts)
    if text is None:
        return False
    click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
    for line in text.splitlines():
        click.echo(f"{prefix}  {line}", color=True)
    return True


def _print_event_draft_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    before_drafts: list[Any] = []
    after_drafts: list[Any] = []
    for change in changes:
        before = _display_field_value(field_name, change.get("before"))
        after = _display_field_value(field_name, change.get("after"))
        if isinstance(before, list):
            before_drafts.extend(before)
        elif before not in (None, ""):
            before_drafts.append(before)
        if isinstance(after, list):
            after_drafts.extend(after)
        elif after not in (None, ""):
            after_drafts.append(after)
    text = _audit_event_draft_diff_table_text(before_drafts, after_drafts)
    if text is None:
        text = _audit_event_draft_table_text(after_drafts)
    if text is None:
        return False
    click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
    for line in text.splitlines():
        click.echo(f"{prefix}  {line}", color=True)
    return True


def _print_historical_field_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    selected: Any = None
    for entry in values:
        value = _display_field_value(field_name, entry.get("value"))
        if isinstance(value, dict) and _audit_is_historical_field_state_summary(value):
            selected = value
            break
    if selected is None:
        return False
    click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
    for line in _audit_historical_field_state_text(selected).splitlines():
        click.echo(f"{prefix}  {line}", color=True)
    return True


def _print_historical_field_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    for change in changes:
        before = _display_field_value(field_name, change.get("before"))
        after = _display_field_value(field_name, change.get("after"))
        before_is_summary = isinstance(before, dict) and _audit_is_historical_field_state_summary(before)
        after_is_summary = isinstance(after, dict) and _audit_is_historical_field_state_summary(after)
        if not (before_is_summary or after_is_summary):
            continue
        diff = _audit_historical_field_state_diff_text(before, after)
        if diff is None:
            continue
        click.echo(f"{prefix}{_audit_combined_single_field_label(field_name)}", color=True)
        for line in diff.splitlines():
            click.echo(f"{prefix}  {line}", color=True)
        return True
    return False


def _dedupe_audit_list(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = _audit_display_key(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _audit_ledger_scalar_text(value: Any) -> str | None:
    return ledger_formatter.ledger_scalar_text(
        value,
        normalize=_audit_normalized_value,
        scalar_sequence_text=_audit_scalar_sequence_text,
        audit_text=_audit_text,
        inline_complex_cell_text=_audit_inline_complex_cell_text,
        table_cell_is_complex=_audit_table_cell_is_complex,
    )


def _cash_pool_scalar_record_table(record: dict[str, Any]) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    return ledger_formatter.cash_pool_scalar_record_table(
        record,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
    )


def _print_combined_cash_pool_scalar_value_table(prefix: str, records: list[dict[str, Any]]) -> bool:
    tables = [_cash_pool_scalar_record_table(record) for record in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = ledger_formatter.combined_scalar_value_rows([table for table in tables if table is not None])
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("cash pool", "ledgers", "strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
    )


def _print_ledger_scalar_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = ledger_formatter.ledger_scalar_value_rows(
        field_name,
        values,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(headers, rows, indent=prefix)


def _print_strategy_scalar_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = strategy_formatter.strategy_scalar_value_rows(
        field_name,
        values,
        display_field_value=_display_field_value,
        ledger_scalar_text=_audit_ledger_scalar_text,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(headers, rows, indent=prefix)


def _print_strategy_record_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = strategy_formatter.strategy_record_value_rows(
        field_name,
        values,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
        table_cell_is_complex=_audit_table_cell_is_complex,
        scalar_cell=_audit_scalar_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(
        ("strategies", *headers),
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


_AUDIT_MISSING = object()


def _strategy_scalar_record_table(record: dict[str, Any]) -> tuple[list[str], dict[str, tuple[Any, ...]]] | None:
    return strategy_formatter.strategy_scalar_record_table(
        record,
        field_display_value_kind=_field_metadata.display_value_kind,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
        table_cell_is_complex=_audit_table_cell_is_complex,
    )


def _print_combined_strategy_scalar_value_table(prefix: str, records: list[dict[str, Any]]) -> bool:
    tables = [_strategy_scalar_record_table(record) for record in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = strategy_formatter.combine_strategy_tables(
        [table for table in tables if table is not None],
        display_key=_audit_display_key,
        annotate=_audit_annotated_strategy_row_values,
    )
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
    )


def _audit_annotated_strategy_row_values(field_columns: list[str], row_values: tuple[Any, ...]) -> tuple[Any, ...]:
    return strategy_formatter.annotated_strategy_row_values(field_columns, row_values)


def _print_ledger_grouped_values(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    if _print_positions_value_table(prefix, field_name, values):
        return True
    items = ledger_formatter.ledger_detail_value_groups(
        field_name,
        values,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
    )
    if items is None:
        return False
    for title, value in items:
        click.echo(f"{prefix}{title}:")
        _print_audit_value(f"{prefix}  ", "value", value)
    return True


def _print_positions_value_table(prefix: str, field_name: str, values: list[dict[str, Any]]) -> bool:
    result = ledger_formatter.positions_value_rows(
        field_name,
        values,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
        cash_summary=_audit_cash_summary,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(headers, rows, indent=prefix, allow_transpose=False, allow_split=False)


def _print_ledger_grouped_changes(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    items = ledger_formatter.ledger_detail_change_groups(
        field_name,
        changes,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
    )
    if items is None:
        return False
    for title, before, after in items:
        click.echo(f"{prefix}{title}:")
        _print_audit_diff_value(f"{prefix}  ", "value", before, after)
    return True


def _print_positions_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = ledger_formatter.positions_change_rows(
        field_name,
        changes,
        display_field_value=_display_field_value,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
        cash_summary=_audit_cash_summary,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    if not rows:
        click.echo(f"{prefix}（无变化）")
        return True
    return _print_audit_table(headers, rows, indent=prefix, allow_transpose=False, allow_split=False)


def _ledger_scalar_record_table(record: dict[str, Any]) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    return ledger_formatter.ledger_scalar_record_table(
        record,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
    )


def _print_combined_ledger_scalar_value_table(prefix: str, records: list[dict[str, Any]]) -> bool:
    tables = [_ledger_scalar_record_table(record) for record in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = ledger_formatter.combined_scalar_value_rows([table for table in tables if table is not None])
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("ledger", "cash pool", "strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
    )


def _audit_combined_single_field_label(qualified_name: str) -> str:
    return audit_printer_helpers.combined_single_field_label(qualified_name)


def _print_audit_table(
    headers: tuple[str, ...] | list[str],
    rows: list[tuple[Any, ...]] | list[list[Any]],
    *,
    prefix: str = "",
    indent: str | None = None,
    label_lines: list[str] | None = None,
    title: str | None = None,
    allow_transpose: bool = True,
    allow_split: bool = True,
) -> bool:
    if label_lines:
        for line in label_lines:
            click.echo(line, color=True)
    if title is not None:
        click.echo(title)
    for line in _audit_table_lines(
        headers,
        rows,
        indent=prefix if indent is None else indent,
        allow_transpose=allow_transpose,
        allow_split=allow_split,
    ):
        click.echo(line)
    return True


_MARKET_DATA_SAMPLE_PRODUCT_LIMIT = market_data_formatter.MARKET_DATA_SAMPLE_PRODUCT_LIMIT


def _print_market_snapshot_value_table(prefix: str, records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    result = market_data_formatter.snapshot_rows_from_value_records(
        records,
        display_field_value=_display_field_value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
    )
    if result is None:
        click.echo(f"{prefix}当前市场快照总表:")
        for line in audit_printer_helpers.combined_field_label_lines(prefix, records):
            click.echo(line, color=True)
        click.echo(f"{prefix}  （当前无市场快照值）")
        return True
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
        title=f"{prefix}当前市场快照总表:",
    )


def _print_market_snapshot_change_table(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    if not records:
        return False
    result = market_data_formatter.snapshot_rows_from_change_records(
        records,
        display_field_value=_display_field_value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        change_cell=_audit_change_cell,
    )
    if result is None:
        click.echo(f"{prefix}当前市场快照总表:")
        for line in audit_printer_helpers.combined_change_field_label_lines(prefix, records):
            click.echo(line, color=True)
        click.echo(f"{prefix}  （无市场快照变化）")
        return True
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
        title=f"{prefix}当前市场快照总表:",
    )


def _print_market_data_sample_value_table(prefix: str, records: list[dict[str, Any]]) -> bool:
    if not records:
        return False
    rows, time_columns = _market_data_sample_rows_from_value_records(records)
    if not rows or not time_columns:
        for line in audit_printer_helpers.combined_field_label_lines(prefix, records):
            click.echo(line, color=True)
        click.echo(f"{prefix}市场数据 sample 总表（每个价格字段最多 {_MARKET_DATA_SAMPLE_PRODUCT_LIMIT} 个产品）:")
        click.echo(f"{prefix}  （无可采样值）")
        return True
    return _print_audit_table(
        ("field", "product", *time_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_field_label_lines(prefix, records),
        title=f"{prefix}市场数据 sample 总表（每个价格字段最多 {_MARKET_DATA_SAMPLE_PRODUCT_LIMIT} 个产品）:",
        allow_transpose=False,
        allow_split=False,
    )


def _print_market_data_sample_change_table(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    if not records:
        return False
    rows, time_columns = _market_data_sample_rows_from_change_records(records)
    if not rows or not time_columns:
        for line in audit_printer_helpers.combined_change_field_label_lines(prefix, records):
            click.echo(line, color=True)
        click.echo(f"{prefix}市场数据 sample 总表（每个价格字段最多 {_MARKET_DATA_SAMPLE_PRODUCT_LIMIT} 个产品）:")
        click.echo(f"{prefix}  （无可采样值）")
        return True
    return _print_audit_table(
        ("field", "product", *time_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
        title=f"{prefix}市场数据 sample 总表（每个价格字段最多 {_MARKET_DATA_SAMPLE_PRODUCT_LIMIT} 个产品）:",
        allow_transpose=False,
        allow_split=False,
    )


def _market_data_sample_rows_from_value_records(records: list[dict[str, Any]]) -> tuple[list[tuple[Any, ...]], list[str]]:
    return market_data_formatter.sample_rows_from_value_records(
        records,
        display_field_value=_display_field_value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        select_sample_part=_audit_select_sample_part,
    )


def _market_data_sample_rows_from_change_records(records: list[tuple[str, list[dict[str, Any]]]]) -> tuple[list[tuple[Any, ...]], list[str]]:
    return market_data_formatter.sample_rows_from_change_records(
        records,
        display_field_value=_display_field_value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        change_cell=_audit_change_cell,
        select_sample_part=_audit_select_sample_part,
    )


def _market_data_sample_rows(samples: list[tuple[str, str, dict[str, str]]], time_columns: list[str]) -> list[tuple[Any, ...]]:
    return market_data_formatter.sample_rows(samples, time_columns)


def _market_data_sample_cells(field_name: str, value: Any) -> list[tuple[str, str, dict[str, str]]]:
    return market_data_formatter.sample_cells(
        field_name,
        value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        select_sample_part=_audit_select_sample_part,
    )


def _market_data_price_tables_sample_cells(value: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    return market_data_formatter.price_tables_sample_cells(
        value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        select_sample_part=_audit_select_sample_part,
    )


def _market_data_frame_sample_cells(field_label: str, value: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    return market_data_formatter.frame_sample_cells(
        field_label,
        value,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
    )


def _market_data_series_sample_cells(field_label: str, value: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    return market_data_formatter.series_sample_cells(
        field_label,
        value,
        scalar_cell=_audit_scalar_cell,
        select_sample_part=_audit_select_sample_part,
    )


def _print_strategy_scalar_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = strategy_formatter.strategy_scalar_change_rows(
        field_name,
        changes,
        display_field_value=_display_field_value,
        ledger_scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(headers, rows, indent=prefix)


def _print_cash_pool_scalar_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = ledger_formatter.cash_pool_scalar_change_rows(
        field_name,
        changes,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(
        headers,
        rows,
        indent=f"{prefix}  ",
        label_lines=[f"{prefix}{_audit_combined_single_field_label(field_name)}"],
    )


def _strategy_scalar_change_record_table(field_name: str, changes: list[dict[str, Any]]) -> tuple[list[str], dict[str, tuple[str, ...]]] | None:
    return strategy_formatter.strategy_scalar_change_record_table(
        field_name,
        changes,
        field_display_value_kind=_field_metadata.display_value_kind,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
        normalize=_audit_normalized_value,
        scalar_cell=_audit_scalar_cell,
        ledger_scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )


def _ledger_scalar_change_record_table(field_name: str, changes: list[dict[str, Any]]) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    return ledger_formatter.ledger_scalar_change_record_table(
        field_name,
        changes,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )


def _cash_pool_scalar_change_record_table(field_name: str, changes: list[dict[str, Any]]) -> tuple[str, dict[tuple[str, str, str], str]] | None:
    return ledger_formatter.cash_pool_scalar_change_record_table(
        field_name,
        changes,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )


def _print_combined_strategy_scalar_change_table(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    tables = [_strategy_scalar_change_record_table(field_name, changes) for field_name, changes in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = strategy_formatter.combine_strategy_tables([table for table in tables if table is not None])
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
    )


def _print_combined_ledger_scalar_change_table(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    tables = [_ledger_scalar_change_record_table(field_name, changes) for field_name, changes in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = ledger_formatter.combined_scalar_value_rows([table for table in tables if table is not None])
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("ledger", "cash pool", "strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
    )


def _print_combined_cash_pool_scalar_change_table(prefix: str, records: list[tuple[str, list[dict[str, Any]]]]) -> bool:
    tables = [_cash_pool_scalar_change_record_table(field_name, changes) for field_name, changes in records]
    if any(table is None for table in tables) or not tables:
        return False
    combined = ledger_formatter.combined_scalar_value_rows([table for table in tables if table is not None])
    if combined is None:
        return False
    field_columns, rows = combined
    return _print_audit_table(
        ("cash pool", "ledgers", "strategies", *field_columns),
        rows,
        indent=f"{prefix}  ",
        label_lines=audit_printer_helpers.combined_change_field_label_lines(prefix, records),
    )


def _print_ledger_scalar_change_table(prefix: str, field_name: str, changes: list[dict[str, Any]]) -> bool:
    result = ledger_formatter.ledger_scalar_change_rows(
        field_name,
        changes,
        display_field_value=_display_field_value,
        scalar_text=_audit_ledger_scalar_text,
        change_cell=_audit_change_cell,
    )
    if result is None:
        return False
    headers, rows = result
    return _print_audit_table(headers, rows, indent=prefix)


def _audit_mapping_table_text(value: Any) -> str | None:
    return value_text_formatter.mapping_table_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        historical_summary=_audit_historical_field_state_summary,
        is_historical_summary=_audit_is_historical_field_state_summary,
        historical_text=_audit_historical_field_state_text,
    )


def _audit_sequence_mapping_table_text(value: Any) -> str | None:
    return value_text_formatter.sequence_mapping_table_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
    )


def _audit_scalar_cell(value: Any) -> str:
    return value_text_formatter.scalar_cell(value, cash_summary=_audit_cash_summary)


def _audit_contract_metadata_text(value: dict[str, Any]) -> str:
    return value_text_formatter.contract_metadata_text(value, table_lines=_audit_table_lines)


def _audit_table_lines(
    headers: tuple[str, ...] | list[str],
    rows: list[tuple[Any, ...]] | list[list[Any]],
    *,
    indent: str = "",
    allow_transpose: bool = True,
    allow_split: bool = True,
) -> list[str]:
    return table_render_formatter.table_lines(
        headers,
        rows,
        indent=indent,
        allow_transpose=allow_transpose,
        allow_split=allow_split,
        text_formatter=_audit_text,
        display_key=_audit_display_key,
        normalize=_audit_normalized_value,
        change_highlight_content=_audit_change_highlight_content,
    )


def _audit_inline_complex_cell_text(value: Any) -> str | None:
    return table_render_formatter.inline_complex_cell_text(value, text_formatter=_audit_text)


def _audit_table_cell_is_complex(value: Any) -> bool:
    return table_render_formatter.table_cell_is_complex(value)


def _audit_price_tables_text(value: dict[str, Any]) -> str:
    return market_data_formatter.price_tables_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
    )


def _audit_market_data_load_plan_text(value: dict[str, Any]) -> str:
    return market_data_formatter.market_data_load_plan_text(value, table_lines=_audit_table_lines)


def _audit_market_data_excluded_products_text(value: dict[str, Any]) -> str:
    return market_data_formatter.market_data_excluded_products_text(
        value,
        scalar_sequence_text=_audit_scalar_sequence_text,
    )


def _audit_run_window_text(value: dict[str, Any]) -> str:
    return run_window_formatter.run_window_text(
        value,
        table_lines=lambda headers, rows: _audit_table_lines(headers, rows, allow_transpose=False),
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
    )


def _audit_run_window_summary(value: Any) -> dict[str, Any] | None:
    return run_window_formatter.run_window_summary(
        value,
        normalize=_audit_normalized_value,
        display_key=_audit_display_key,
    )


def _audit_historical_field_state_summary(value: Any) -> dict[str, Any] | None:
    return market_data_formatter.historical_field_state_summary(
        value,
        normalize=_audit_normalized_value,
        product_filter=_audit_field_state_product_filter,
    )


def _audit_is_historical_field_state_summary(value: dict[str, Any]) -> bool:
    return market_data_formatter.is_historical_field_state_summary(value)


def _audit_historical_field_state_text(value: dict[str, Any]) -> str:
    return market_data_formatter.historical_field_state_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
    )


def _audit_historical_field_state_diff_text(before: Any, after: Any) -> str | None:
    return market_data_formatter.historical_field_state_diff_text(
        before,
        after,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        change_cell=_audit_change_cell,
    )


def _audit_positions_summary(value: Any) -> dict[str, Any] | None:
    return ledger_formatter.positions_summary(value, normalize=_audit_normalized_value)


def _audit_positions_text(value: dict[str, Any]) -> str:
    text = ledger_formatter.positions_text(
        value,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        cash_summary=_audit_cash_summary,
    )
    return text or json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _audit_product_list_cell(products: list[str], *, all_products: list[str] | None = None) -> str:
    return ledger_formatter.product_list_cell(products, all_products=all_products)


def _audit_positions_diff_text(before: Any, after: Any) -> str | None:
    return ledger_formatter.positions_diff_text(
        before,
        after,
        table_lines=_audit_table_lines,
        scalar_cell=_audit_scalar_cell,
        normalize=_audit_normalized_value,
        cash_summary=_audit_cash_summary,
        change_cell=_audit_change_cell,
    )


def _audit_pandas_text(value: Any) -> str | None:
    return market_data_formatter.pandas_text(
        value,
        dataframe_formatter=_audit_dataframe_text,
        series_formatter=_audit_series_text,
    )


def _audit_dataframe_text(value: dict[str, Any]) -> str:
    return market_data_formatter.dataframe_text(
        value,
        table_lines=_audit_table_lines,
        select_sample_part=_audit_select_sample_part,
        sample_note_lines=_audit_sample_note_lines,
        single_sample_frame=_audit_single_sample_frame,
    )


def _audit_dataframe_table_lines(value: dict[str, Any], *, indent: str = "") -> list[str]:
    return market_data_formatter.dataframe_table_lines(
        value,
        table_lines=_audit_table_lines,
        indent=indent,
    )


def _audit_series_text(value: dict[str, Any]) -> str:
    return market_data_formatter.series_text(
        value,
        table_lines=_audit_table_lines,
        select_sample_part=_audit_select_sample_part,
        sample_note_lines=_audit_sample_note_lines,
        single_sample_series=_audit_single_sample_series,
    )


def _parse_audit_literal(value: str) -> Any | None:
    return display_value_formatter.parse_literal(value)


def _compact_audit_display_aliases(value: Any) -> Any:
    return display_value_formatter.compact_aliases(value)


def _compact_product_path_selection_for_audit(value: dict[str, Any]) -> dict[str, Any]:
    return display_value_formatter.compact_product_path_selection(value)


def _display_field_value(qualified_name: str, value: Any) -> Any:
    return display_value_formatter.display_field_value(
        qualified_name,
        value,
        field_display_value_kind=_field_metadata.display_value_kind,
        trade_intent_summary=_audit_trade_intent_summary,
        positions_summary=_audit_positions_summary,
        run_window_summary=_audit_run_window_summary,
        historical_field_state_summary=_audit_historical_field_state_summary,
        cash_summary=_audit_cash_summary,
        scalar_sequence_text=_audit_scalar_sequence_text,
        field_display_offsets=_field_display_offsets,
    )


def _audit_trade_intent_summary(value: Any) -> str | None:
    return trade_intent_formatter.trade_intent_summary(value, normalize=_audit_normalized_value)


def _print_audit_value(prefix: str, label: str, value: Any) -> None:
    grouped = _audit_repeated_owner_groups(value)
    if grouped:
        click.echo(f"{prefix}{label} =")
        for owner_label, owner_value in grouped:
            _print_audit_value(f"{prefix}  ", owner_label, owner_value)
        return
    lines = _audit_text(value).splitlines() or [""]
    if len(lines) == 1:
        _print_key_value_line(prefix, label, lines[0])
        return
    _print_audit_text_block(prefix, label, lines, separator=" =")


def _step_section_title(title: str) -> str:
    return f"━━ {title} ━━"


def _print_step_section(title: str) -> None:
    click.secho(_step_section_title(title), fg="cyan", bold=True, color=True)


def _print_key_value_line(prefix: str, label: str, value: str) -> None:
    line_prefix = f"{prefix}{label} = "
    _print_wrapped_line(
        f"{line_prefix}{value}",
        continuation_indent=" " * _audit_display_width(line_prefix),
    )


def _print_audit_text_block(prefix: str, label: str, lines: list[str], *, separator: str = ":") -> None:
    click.echo(f"{prefix}{label}{separator}")
    for line in lines or [""]:
        _print_audit_block_line(f"{prefix}  ", line)


def _print_audit_block_line(prefix: str, line: str) -> None:
    if " = " not in line:
        click.echo(f"{prefix}{line}")
        return
    key, value = line.split(" = ", 1)
    _print_key_value_line(prefix, key, value)


def _print_wrapped_line(line: str, *, continuation_indent: str) -> None:
    width = _audit_max_width()
    if _audit_display_width(line) <= width:
        click.echo(line)
        return
    wrapped = _wrap_audit_text(line, width=width, subsequent_indent=continuation_indent)
    if not wrapped:
        click.echo(line)
        return
    for wrapped_line in wrapped:
        click.echo(wrapped_line)


def _audit_display_key(value: Any) -> str:
    return display_value_formatter.display_key(value)


def _audit_normalized_value(value: Any) -> Any:
    return display_value_formatter.normalized_value(value)


def _audit_repeated_owner_groups(value: Any) -> list[tuple[str, Any]]:
    return display_value_formatter.repeated_owner_groups(
        value,
        product_list_cell=lambda keys: _audit_product_list_cell(keys),
    )


def _print_audit_source_routes(
    prefix: str,
    entries: list[dict[str, Any]],
) -> bool:
    status, rows = source_group_formatter.source_route_display(entries)
    if status == "empty":
        return False
    return _print_audit_table(
        ("ledger", "cash pool", "strategies"),
        rows,
        indent=prefix,
    )


def _drop_empty_non_ledger_entries_when_ledger_values_exist(
    field_name: str,
    values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return audit_printer_helpers.drop_empty_non_ledger_entries_when_ledger_values_exist(
        field_name,
        values,
        display_value=_display_field_value,
        value_is_empty=lambda value: source_group_formatter.value_is_empty(
            value,
            normalize=_audit_normalized_value,
        ),
    )


def _print_audit_diff_value(prefix: str, label: str, before: Any, after: Any) -> None:
    order_diff_text = _audit_order_diff_text(before, after)
    if order_diff_text is not None:
        _print_audit_text_block(prefix, label, order_diff_text.splitlines())
        return
    positions_diff_text = _audit_positions_diff_text(before, after)
    if positions_diff_text is not None:
        _print_audit_text_block(prefix, label, positions_diff_text.splitlines())
        return
    diff_text = _audit_historical_field_state_diff_text(before, after)
    if diff_text is not None:
        _print_audit_text_block(prefix, label, diff_text.splitlines())
        return
    if _audit_repeated_owner_groups(before) or _audit_repeated_owner_groups(after):
        click.echo(f"{prefix}{label}:")
        _print_audit_arrow_diff(f"{prefix}  ", before, after)
        return
    before_lines = _audit_text(before).splitlines() or [""]
    after_lines = _audit_text(after).splitlines() or [""]
    if len(before_lines) == 1 and len(after_lines) == 1:
        _print_key_value_line(prefix, label, _audit_change_cell(before_lines[0], after_lines[0]))
        return
    click.echo(f"{prefix}{label}:")
    _print_audit_arrow_diff(f"{prefix}  ", before, after)


def _print_audit_arrow_diff(prefix: str, before: Any, after: Any) -> None:
    after_lines = _audit_text(after).splitlines() or [""]
    click.echo(f"{prefix}{_audit_change_prefix(_audit_inline_summary(before))}", color=True)
    for line in after_lines:
        click.echo(f"{prefix}  {_audit_change_highlight_content(line)}", color=True)


def _audit_inline_summary(value: Any) -> str:
    return display_value_formatter.inline_summary(
        value,
        audit_text=_audit_text,
        display_width=_audit_display_width,
    )


def _audit_field_sort_key(qualified_name: str) -> tuple[int, int, str]:
    return _field_metadata.sort_key(qualified_name)


def _audit_section_printer() -> audit_sections.StepAuditSectionPrinter:
    return audit_sections.StepAuditSectionPrinter(
        print_step_section=_print_step_section,
        field_sort_key=_audit_field_sort_key,
        field_display_value_kind=_field_metadata.display_value_kind,
        print_market_snapshot_value_table=_print_market_snapshot_value_table,
        print_market_snapshot_change_table=_print_market_snapshot_change_table,
        print_market_data_sample_value_table=_print_market_data_sample_value_table,
        print_market_data_sample_change_table=_print_market_data_sample_change_table,
        print_delta_mapping_value_tables=_print_delta_mapping_value_tables,
        print_delta_mapping_change_tables=_print_delta_mapping_change_tables,
        print_delta_mapping_value_table=_print_delta_mapping_value_table,
        print_delta_mapping_change_table=_print_delta_mapping_change_table,
        print_order_value_table=_print_order_value_table,
        print_order_change_table=_print_order_change_table,
        print_execution_price_value_table=_print_execution_price_value_table,
        print_execution_price_change_table=_print_execution_price_change_table,
        print_event_draft_value_table=_print_event_draft_value_table,
        print_event_draft_change_table=_print_event_draft_change_table,
        print_historical_field_value_table=_print_historical_field_value_table,
        print_historical_field_change_table=_print_historical_field_change_table,
        scalar_value_record_group=_scalar_value_record_group,
        scalar_value_group_key=_scalar_value_group_key,
        scalar_change_record_group=_scalar_change_record_group,
        scalar_change_group_key=_scalar_change_group_key,
        drop_empty_non_ledger_entries=_drop_empty_non_ledger_entries_when_ledger_values_exist,
        print_strategy_record_value_table=_print_strategy_record_value_table,
        print_ledger_scalar_value_table=_print_ledger_scalar_value_table,
        print_strategy_scalar_value_table=_print_strategy_scalar_value_table,
        print_ledger_grouped_values=_print_ledger_grouped_values,
        display_field_value=_display_field_value,
        display_key=_audit_display_key,
        print_audit_source_routes=_print_audit_source_routes,
        print_audit_value=_print_audit_value,
        print_lifecycle_notice_change=_print_lifecycle_notice_change,
        print_weight_change_tables=_print_weight_change_tables,
        print_strategy_scalar_change_table=_print_strategy_scalar_change_table,
        print_positions_change_table=_print_positions_change_table,
        print_cash_pool_scalar_change_table=_print_cash_pool_scalar_change_table,
        print_ledger_scalar_change_table=_print_ledger_scalar_change_table,
        print_ledger_grouped_changes=_print_ledger_grouped_changes,
        print_audit_diff_value=_print_audit_diff_value,
    )


def _print_audit_fields(
    title: str,
    records: list[dict[str, Any]],
    *,
    empty_message: str = "（无字段）",
) -> None:
    _audit_section_printer().print_fields(
        title,
        records,
        empty_message=empty_message,
    )


def _scalar_value_record_group(record: dict[str, Any]) -> tuple[tuple[Any, ...] | None, Any, tuple[Any, ...] | None]:
    if _field_metadata.display_value_kind(str(record.get("field") or "")) in {
        "market_data_sample",
        "market_snapshot",
        "delta_table",
        "order_table",
        "execution_price_table",
        "event_draft_table",
        "positions",
        "historical_field_state",
    }:
        return None, None, None
    return audit_printer_helpers.scalar_record_group([
        (_cash_pool_scalar_record_table(record), _print_combined_cash_pool_scalar_value_table, False),
        (_strategy_scalar_record_table(record), _print_combined_strategy_scalar_value_table, True),
        (_ledger_scalar_record_table(record), _print_combined_ledger_scalar_value_table, False),
    ])


def _scalar_value_group_key(record: dict[str, Any]) -> tuple[Any, tuple[Any, ...] | None] | None:
    table, printer, routes = _scalar_value_record_group(record)
    if table is None:
        return None
    return printer, routes


def _scalar_change_record_group(
    field_name: str,
    field_changes: list[dict[str, Any]],
) -> tuple[tuple[Any, ...] | None, Any, tuple[Any, ...] | None]:
    if _field_metadata.display_value_kind(field_name) in {
        "market_data_sample",
        "market_snapshot",
        "delta_table",
        "order_table",
        "execution_price_table",
        "event_draft_table",
        "positions",
        "historical_field_state",
    }:
        return None, None, None
    return audit_printer_helpers.scalar_record_group([
        (_cash_pool_scalar_change_record_table(field_name, field_changes), _print_combined_cash_pool_scalar_change_table, False),
        (_strategy_scalar_change_record_table(field_name, field_changes), _print_combined_strategy_scalar_change_table, True),
        (_ledger_scalar_change_record_table(field_name, field_changes), _print_combined_ledger_scalar_change_table, False),
    ])


def _print_audit_changes(
    title: str,
    changes: list[dict[str, Any]],
) -> None:
    _audit_section_printer().print_changes(title, changes)


def _scalar_change_group_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[Any, tuple[Any, ...] | None] | None:
    table, printer, routes = _scalar_change_record_group(item[0], item[1])
    if table is None:
        return None
    return printer, routes


def _audit_cash_summary(value: Any) -> str:
    return value_text_formatter.cash_summary(value, audit_text=_audit_text)


def _print_strategy_context(strategies: list[dict[str, Any]], short_alias_map: dict[str, str] | None = None) -> None:
    _print_step_section("本次 flow 的 active strategies")
    for line in step_display_formatter.strategy_context_lines(strategies, short_alias_map=short_alias_map or {}):
        click.echo(line)


def _print_event_payloads(payloads: list[dict[str, Any]]) -> None:
    payloads = step_display_formatter.non_empty_event_payloads(payloads)
    if not payloads:
        return
    click.echo("  事件输入（当前批次，非完整事件队列）:")
    table = _event_payload_input_table(payloads)
    if table is not None:
        headers, rows = table
        _print_audit_table(headers, rows, indent="    ", allow_transpose=False)
        return
    for payload in payloads:
        _print_audit_value("    ", step_display_formatter.event_payload_label(payload), payload.get("payloads"))


def _event_payload_input_table(payloads: list[dict[str, Any]]) -> tuple[tuple[str, ...], list[tuple[Any, ...]]] | None:
    rows: list[tuple[Any, ...]] = []
    all_order_payloads = True
    for entry in payloads:
        for item in _event_payload_items(entry.get("payloads")):
            if not _event_payload_looks_like_order(item):
                all_order_payloads = False
                break
        if not all_order_payloads:
            break
    for entry in payloads:
        for item in _event_payload_items(entry.get("payloads")):
            if all_order_payloads:
                rows.append(_order_event_payload_input_row(entry, item))
            else:
                rows.append(_generic_event_payload_input_row(entry, item))
    if not rows:
        return None
    if all_order_payloads:
        return _drop_empty_event_input_columns(
            (
                "scope",
                "strategy",
                "ledger",
                "cash pool",
                "event_time",
                "event_kind",
                "order_id",
                "instrument",
                "intent_quantity",
                "quantity",
                "status",
                "reject_reason",
            ),
            rows,
            optional_columns={"strategy", "ledger", "cash pool", "reject_reason"},
        )
    return _drop_empty_event_input_columns(
        ("scope", "strategy", "ledger", "cash pool", "event", "subject", "action", "reason", "details"),
        rows,
        optional_columns={"strategy", "ledger", "cash pool", "reason", "details"},
    )


def _drop_empty_event_input_columns(
    headers: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    *,
    optional_columns: set[str],
) -> tuple[tuple[str, ...], list[tuple[Any, ...]]]:
    keep_indexes = [
        index
        for index, header in enumerate(headers)
        if header not in optional_columns
        or any(str(row[index] if index < len(row) else "").strip() for row in rows)
    ]
    return (
        tuple(headers[index] for index in keep_indexes),
        [tuple(row[index] if index < len(row) else "" for index in keep_indexes) for row in rows],
    )


def _event_payload_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [] if value in (None, "") else [value]


def _event_payload_looks_like_order(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    required = {"instrument", "quantity", "intent_quantity", "status", "strategy", "timestamp", "order_id"}
    return required <= set(value)


def _order_event_payload_input_row(entry: dict[str, Any], payload: Any) -> tuple[Any, ...]:
    item = payload if isinstance(payload, dict) else {}
    return (
        entry.get("scope") or "",
        item.get("strategy") or entry.get("strategy") or "",
        entry.get("ledger") or "",
        entry.get("cash_pool") or "",
        item.get("timestamp") or "",
        item.get("kind") or "order",
        item.get("order_id") or "",
        item.get("instrument") or "",
        _audit_scalar_cell(item.get("intent_quantity")),
        _audit_scalar_cell(item.get("quantity")),
        _audit_scalar_cell(item.get("status")),
        _audit_scalar_cell(item.get("reject_reason")),
    )


def _generic_event_payload_input_row(entry: dict[str, Any], payload: Any) -> tuple[Any, ...]:
    item = payload if isinstance(payload, dict) else {"value": payload}
    subject = item.get("product") or item.get("ledger_id") or item.get("trading_day") or item.get("instrument") or ""
    action = item.get("notice_type") or item.get("kind") or item.get("status") or item.get("reason") or ""
    details = events_formatter.event_payload_details(item)
    return (
        entry.get("scope") or "",
        entry.get("strategy") or "",
        entry.get("ledger") or "",
        entry.get("cash_pool") or "",
        item.get("kind") or "",
        _audit_scalar_cell(subject),
        _audit_scalar_cell(action),
        _audit_scalar_cell(item.get("notice_reason") or item.get("reason") or ""),
        details if details else "",
    )


def _print_audit_inputs(
    event_payloads: list[dict[str, Any]],
    records: list[dict[str, Any]],
    empty_message: str,
) -> None:
    _print_step_section("输入字段")
    _print_event_payloads(event_payloads)
    if event_payloads and records:
        click.echo("  声明输入字段:")
    _audit_section_printer().print_field_records(records, empty_message=empty_message)


def _print_event_payload_changes(changes: list[dict[str, Any]]) -> None:
    _print_step_section("本批事件草稿载荷变化（非完整事件队列）")
    if not changes:
        click.echo("  （无变化）")
        return
    for bucket in step_display_formatter.event_payload_change_buckets(changes, display_key=_audit_display_key):
        _print_audit_diff_value(
            "  ",
            source_group_formatter.source_group_label(bucket["entries"]),
            bucket["before"],
            bucket["after"],
        )


def _audit_max_width() -> int:
    return table_render_formatter.max_width()


def _wrap_audit_text(text: str, *, width: int, subsequent_indent: str = "") -> list[str]:
    return table_render_formatter.wrap_text(text, width=width, subsequent_indent=subsequent_indent)


def _print_step_badge_box(data: dict[str, Any], phase_text: str, flow_id: str, flow_name: str, timestamp_text: str) -> None:
    for line in step_display_formatter.step_badge_box_lines(data, phase_text, flow_id, flow_name, timestamp_text):
        click.echo(_audit_badge_highlight(line), color=True)


def _print_contract_audit(violations: list[dict[str, Any]]) -> None:
    _print_step_section("字段声明审计")
    for line in step_display_formatter.contract_audit_lines(violations):
        click.echo(line)


def _step_event_renderer(short_alias_map: dict[str, str]) -> step_runtime.StepEventRenderer:
    return step_runtime.StepEventRenderer(
        phase_label=phase_label,
        audit_context=lambda data: _audit_step_event_context(data, short_alias_map=short_alias_map),
        print_badge_box=_print_step_badge_box,
        print_strategy_context=_print_strategy_context,
        print_audit_inputs=_print_audit_inputs,
        print_audit_fields=_print_audit_fields,
        print_audit_changes=_print_audit_changes,
        print_contract_audit=_print_contract_audit,
        display_key=_audit_display_key,
        normalize=_audit_normalized_value,
        short_alias_map=short_alias_map,
    )


def _handle_step_event(
    data: dict[str, Any],
    client,
    run_token: str,
    navigator: step_display_formatter.StepNavigator,
    *,
    short_alias_map: dict[str, str] | None = None,
) -> None:
    """Render one complete, post-compute audit record and continue once."""
    if str(data.get("phase") or "") != "step":
        return
    if not navigator.should_display(data.get("timestamp")):
        step_runtime.continue_step(client, run_token, navigator)
        return

    _step_event_renderer(short_alias_map or {}).render(data)
    click.echo("")
    step_display_formatter.set_event_queue_snapshot(navigator, data.get("event_queue"))
    step_runtime.prompt_step_navigation(navigator)
    step_runtime.continue_step(client, run_token, navigator)

def _run_backtest(
    state,
    *,
    groups: list[dict[str, Any]],
    verbose: bool = False,
    step_mode: bool = False,
    ls_configs: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    title: str = "回测",
    show_topology: bool = True,
) -> None:
    if not state.page_uuid:
        raise click.ClickException("缺少 page_uuid；请先运行 factortester login 以创建页面上下文")
    if not groups:
        raise click.ClickException("没有可运行的分组；请先用 factortester group --add 新增分组")
    display_ls_configs = ls_configs if ls_configs is not None else state.backtest_ls_configs
    run_payload = payload or _run_payload(state, groups=groups)
    run_token = run_config_helpers.configure_step_mode_payload(run_payload, step_mode=step_mode)
    click.echo(f"开始运行{title}: groups={len(groups)}, long-short={len(display_ls_configs)}")
    if not step_mode:
        _print_run_strategy_info(groups, display_ls_configs)
    if show_topology:
        config_command_handlers.print_run_topology(state, payload=payload, run_payload=run_payload)
    client = client_from_config()
    # A saved template/CLI draft persists aliases and parameters, never Factor
    # instances.  Recreate one-off Factors in the current page before every
    # run so a new login/page_uuid cannot depend on an older page cache.
    template_state_helpers.register_template_factors(state, client)
    renderer = BacktestRunRenderer(verbose=verbose, live=_equity_curve_live_enabled(state, client=client), step_mode=step_mode)
    step_navigator = step_display_formatter.StepNavigator()
    short_alias_map = step_display_formatter.build_short_alias_map(state.backtest_groups, state.backtest_ls_configs)
    run_stream.consume_stream(
        client,
        run_payload,
        renderer=renderer,
        run_token=run_token,
        step_navigator=step_navigator,
        handle_step_event=lambda data, client, run_token, navigator: _handle_step_event(
            data,
            client,
            run_token,
            navigator,
            short_alias_map=short_alias_map,
        ),
    )
    renderer.handle("complete", {})
    if renderer.last_result:
        state.backtest_last_result = renderer.last_result
        save_state(state)
        _save_backtest_research_result(client, state, run_payload, renderer.last_result)
    _print_backtest_result_hints()


def _run_payload(state, *, groups: list[dict[str, Any]]) -> dict[str, Any]:
    return run_payload_formatter.run_payload(
        state,
        groups=groups,
        strategy_book_payload=_strategy_book_payload,
    )


def _parse_result_output_options(args: tuple[str, ...]) -> tuple[dict[str, Any], tuple[str, ...]]:
    return result_output_formatter.parse_result_output_options(args, error=click.ClickException)


def _emit_result_output(options: dict[str, Any], callback) -> None:
    result_output_formatter.emit_result_output(
        options,
        callback,
        echo=lambda text: click.echo(text, nl=False),
    )


def _arg_value(args: tuple[str, ...], flag: str) -> str:
    return results_data_formatter.arg_value(args, flag)


def _print_backtest_result_hints() -> None:
    config_command_handlers.print_result_hints()


def _save_backtest_research_result(client: Any, state: Any, run_payload: dict[str, Any], result: dict[str, Any]) -> None:
    try:
        groups = [group for group in (run_payload.get("groups") or []) if isinstance(group, dict)]
        factor_alias = _primary_backtest_factor_alias(groups)
        if not factor_alias:
            return
        product_group = _primary_backtest_product_group(groups)
        local_settings = run_payload.get("local_settings") if isinstance(run_payload.get("local_settings"), dict) else {}
        start_date = str(local_settings.get("start_date") or "")
        end_date = str(local_settings.get("end_date") or "")
        if not start_date or not end_date:
            return
        payload = {
            "ff_alias": _factor_family_from_alias(factor_alias, state),
            "factor_alias": factor_alias,
            "factor_source": str((state.page_settings or {}).get("factor_source") or ""),
            "product_group": product_group,
            "start_date": start_date,
            "end_date": end_date,
            "test_type": "backtest",
            "config": {
                "local_settings": local_settings,
                "ledger_configs": run_payload.get("ledger_configs") or {},
                "strategy_book": run_payload.get("strategy_book") or {},
                "ls_count": len(run_payload.get("ls_configs") or []),
                "group_count": len(groups),
            },
            "metrics": _backtest_research_metrics(result),
            "note": "auto-saved from factortester backtest run",
        }
        client.save_factor_research_run(attach_research_metadata(payload, settings=local_settings, extra=run_payload))
    except Exception as exc:
        click.echo(f"研究结果入库失败: {exc}", err=True)


def _primary_backtest_factor_alias(groups: list[dict[str, Any]]) -> str:
    for group in groups:
        alias = str(group.get("factorAlias") or group.get("factor") or "").strip()
        if alias:
            return alias
    return ""


def _primary_backtest_product_group(groups: list[dict[str, Any]]) -> str:
    for group in groups:
        selection = group.get("product_path_selection")
        if isinstance(selection, dict):
            label = str(selection.get("label") or selection.get("name") or selection.get("product_group") or "").strip()
            if label:
                return label
        selection_id = str(group.get("product_path_selection_id") or "").strip()
        if selection_id:
            return selection_id
    return ""


def _factor_family_from_alias(factor_alias: str, state: Any) -> str:
    if "|" in factor_alias:
        return factor_alias.split("|", 1)[0]
    return str(getattr(state, "factor_family", "") or factor_alias)


def _backtest_research_metrics(result: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    returns: dict[str, float] = {}
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = _metric_safe_name(str(group.get("name") or group.get("shortAlias") or group.get("id") or "portfolio"))
        curve = _numeric_curve(group.get("total_equity") or group.get("equity") or [])
        if curve:
            ret = curve[-1] / curve[0] - 1 if curve[0] else None
            dd = _max_drawdown(curve)
            if ret is not None:
                metrics[f"{name}_return"] = ret
                returns[name] = ret
            metrics[f"{name}_max_drawdown"] = dd
            metrics[f"{name}_points"] = len(curve)
            if name.startswith("ls_"):
                metrics.setdefault("ls_return", ret)
                metrics.setdefault("ls_max_drawdown", dd)
        for key in ("return", "max_drawdown"):
            if group.get(key) is not None:
                metrics.setdefault(f"{name}_{key}", group.get(key))
        if name.startswith("ls_") and group.get("return") is not None:
            metrics.setdefault("ls_return", group.get("return"))
            if group.get("max_drawdown") is not None:
                metrics.setdefault("ls_max_drawdown", group.get("max_drawdown"))
    if "a1" in returns and "a5" in returns:
        metrics["a1_a5_return_spread"] = returns["a1"] - returns["a5"]
    return {key: value for key, value in metrics.items() if value is not None}


def _numeric_curve(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for value in values:
        try:
            if value is not None:
                out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            drawdown = min(drawdown, value / peak - 1)
    return drawdown


def _metric_safe_name(name: str) -> str:
    import re

    value = re.sub(r"[^0-9A-Za-z]+", "_", name.strip().lower()).strip("_")
    return value or "portfolio"


def _print_run_strategy_info(groups: list[dict[str, Any]], ls_configs: list[dict[str, Any]]) -> None:
    config_command_handlers.print_run_strategy_info(groups, ls_configs)


def _equity_curve_live_enabled(state, *, client=None) -> bool:
    _, store = config_state_helpers.stores_for_backtest(state, client=client)
    return run_config_helpers.equity_curve_live_enabled(store)
