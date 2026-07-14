from __future__ import annotations

import json
import re
import shutil
import threading
import contextlib
import io
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import click
from click.testing import CliRunner
from flask import Flask, Response, jsonify, request
from werkzeug.serving import make_server

from tools.cli.app import _backtest_errors, cli
from tools.cli.http import ClientConfig, HttpClientError, save_config
import tools.cli.modules.backtest.run_output as run_output
from tools.cli.modules.backtest.audit_formatters import step_display as step_display_formatter
from tools.cli.modules.backtest import config_state as config_state_helpers
from tools.cli.modules.backtest import run_payloads as run_payload_helpers
from tools.cli.modules.keys import public_module_key
from tools.cli.modules.backtest.run_output import BacktestRunRenderer
from tools.cli.modules.backtest.controller import (
    _audit_change_cell,
    _audit_scalar_sequence_text,
    _audit_step_event_context,
    _audit_table_lines,
    _audit_text,
    _handle_step_event,
    _print_audit_changes,
    _print_contract_audit,
    _print_event_payload_changes,
    _print_event_payloads,
    _print_audit_fields,
    _print_audit_diff_value,
    _print_audit_value,
    _print_step_badge_box,
    _print_strategy_context,
    _display_field_value,
)
from tools.cli.modules.backtest.audit_formatters import display_values as display_value_formatter
from tools.cli.modules.backtest.audit_formatters.field_metadata import load_field_metadata
from tools.cli.modules.registry import ControllerRegistry
from tools.data.types.data_money import DataMoney


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_step_audit_field_metadata_loads_display_value_kind_from_field_definitions() -> None:
    metadata = load_field_metadata()

    assert metadata.display_value_kind("MarketDataModule.raw_prices") == "market_data_sample"
    assert metadata.display_value_kind("raw_prices") == "market_data_sample"
    assert metadata.display_value_kind("MarketDataModule.causal_valuation_table") == "market_data_sample"
    assert metadata.display_value_kind("LedgerModule.positions") == "positions"
    assert metadata.display_value_kind("TargetStrategyModule.trade_intent") == "trade_intent"
    assert metadata.display_value_kind("RunWindowModule.strategy_windows") == "strategy_scoped_mapping"
    assert metadata.display_value_kind("MarketDataModule.field_state_baseline") == "historical_field_state"
    assert metadata.display_value_kind("CashPoolModule.cash") == "cash"
    assert metadata.display_value_kind("MarketDataModule.required_data_source") == "auto_when_empty"


def test_step_audit_does_not_repeat_changed_output_after_value() -> None:
    records = [
        {"field": "Ledger.cash", "values": [{"scope": "context", "value": 90}]},
        {"field": "Ledger.status", "values": [{"scope": "context", "value": "open"}]},
    ]

    assert step_display_formatter.unchanged_output_records(
        records,
        [{"field": "Ledger.cash", "before": 100, "after": 90}],
    ) == [
        records[1],
    ]


def test_step_audit_treats_ledger_side_channel_changes_as_declared_output_changes() -> None:
    outputs = [
        {"field": "CashPoolModule.cash", "values": [{"scope": "ledger", "ledger": "L1", "cash_pool": "P1", "value": None}]},
        {"field": "LedgerModule.positions", "values": [{"scope": "ledger", "ledger": "L1", "cash_pool": "P1", "value": None}]},
    ]
    ledger_changes = [
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": "L1",
            "cash_pool": "P1",
            "before": None,
            "after": {"currency": "CNY", "amount": 100},
        }
    ]

    merged_changes = step_display_formatter.merge_declared_and_ledger_changes(
        [],
        ledger_changes,
        display_key=display_value_formatter.display_key,
        normalize=display_value_formatter.normalized_value,
    )

    assert [change["field"] for change in merged_changes] == ["CashPoolModule.cash"]
    unchanged = step_display_formatter.unchanged_output_records(outputs, merged_changes)
    assert [record["field"] for record in unchanged] == ["LedgerModule.positions"]


def test_step_audit_groups_identical_values_by_partial_strategy_sets(capsys) -> None:
    records = [{
        "field": "TradingRuleModule.window",
        "values": [
            {"scope": "strategy_config", "strategy": "A1", "value": "0 days 00:02:00"},
            {"scope": "strategy_config", "strategy": "A2", "value": "0 days 00:02:00"},
            {"scope": "strategy_config", "strategy": "A3", "value": "0 days 00:05:00"},
        ],
    }]

    _print_audit_fields("输入字段", records)

    out = capsys.readouterr().out
    assert "strategies" in out
    assert "window" in out
    assert "A1, A2" in out
    assert "0 days 00:02:00" in out
    assert "A3" in out
    assert "0 days 00:05:00" in out
    assert "[跨策略]" not in out


def test_step_audit_fields_follow_backend_display_order(capsys) -> None:
    records = [
        {"field": "RunWindowModule.timezone", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "Asia/Shanghai"}]},
        {"field": "FactorModule.factor", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "SgCCS|N:2m"}]},
        {"field": "RunWindowModule.start_time", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "09:00"}]},
        {"field": "RunWindowModule.end_date", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "2026-01-31"}]},
        {"field": "RunWindowModule.start_date", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "2026-01-01"}]},
        {"field": "RunWindowModule.end_time", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "15:00"}]},
        {"field": "RunWindowModule.time_precision", "values": [{"scope": "strategy_config", "strategy": "A1", "value": "exact"}]},
    ]

    _print_audit_fields("输入字段", records)

    out = capsys.readouterr().out
    ordered = [
        "start_date",
        "factor",
        "end_date",
        "time_precision",
        "start_time",
        "end_time",
        "timezone",
    ]
    positions = [out.index(name) for name in ordered]
    assert positions == sorted(positions)


def test_step_audit_changes_follow_backend_display_order(capsys) -> None:
    changes = [
        {"field": "RunWindowModule.timezone", "scope": "context", "before": None, "after": "Asia/Shanghai"},
        {"field": "RunWindowModule.start_date", "scope": "context", "before": None, "after": "2026-01-01"},
        {"field": "RunWindowModule.time_precision", "scope": "context", "before": None, "after": "exact"},
    ]

    _print_audit_changes("声明输出的变化", changes)

    out = capsys.readouterr().out
    ordered = ["start_date", "time_precision", "timezone"]
    positions = [out.index(name) for name in ordered]
    assert positions == sorted(positions)


def test_step_audit_change_cell_uses_distinct_highlight() -> None:
    cell = _audit_change_cell("100", "90")

    assert "\x1b[30m" in cell
    assert "\x1b[103m" in cell
    assert "\x1b[43m" not in cell
    assert "100 -> 90" in cell


def test_step_badge_uses_light_pink_background(capsys) -> None:
    _print_step_badge_box(
        {
            "current_event": {"event_kind": "ORDER", "batch_count": 1},
            "timestamp": "2026-01-05 09:01:00+08:00",
        },
        "PER_EVENT (事件回放)",
        "apply_order_fill",
        "成交落账",
        "2026-01-05 09:01:00+08:00",
    )

    out = capsys.readouterr().out
    assert "\x1b[30m\x1b[48;2;255;238;246m" in out
    assert "\x1b[101m" not in out
    assert "\x1b[105m" not in out
    assert "\x1b[41m" not in out
    assert "apply_order_fill" in out
    assert "flow           = PER_EVENT" in _strip_ansi(out)
    assert "timestamp      = 2026-01-05 09:01:00+08:00" in _strip_ansi(out)
    assert "event_kind     = ORDER" in _strip_ansi(out)
    assert "batch_count    = 1" in _strip_ansi(out)


def test_step_badge_wraps_event_subjects_at_value_column(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((76, 20)))

    _print_step_badge_box(
        {
            "current_event": {
                "event_kind": "ORDER",
                "batch_count": 3,
                "subjects": [
                    {
                        "strategy": "A1",
                        "subject": "CZCE|F|SM|2603-with-a-very-long-subject-name",
                        "action": "filled",
                    },
                    {
                        "strategy": "A2",
                        "subject": "DCE|F|LH|2605-with-a-very-long-subject-name",
                        "action": "scheduled",
                    },
                ],
            },
        },
        "PER_EVENT (事件回放)",
        "apply_order_fill",
        "成交落账",
        "2026-01-05 09:01:00+08:00",
    )

    lines = [_strip_ansi(line) for line in capsys.readouterr().out.splitlines()]
    subject_lines = [line for line in lines if "event_subjects" in line or "CZCE|F|SM|2603" in line or "DCE|F|LH|2605" in line]
    assert any("event_subjects = " in line for line in subject_lines)
    continuation_lines = [line for line in subject_lines if "event_subjects" not in line]
    assert continuation_lines
    assert all("┃                " in line for line in continuation_lines)


def test_data_money_repr_distinguishes_minor_int_and_major_float() -> None:
    minor = DataMoney(10000000000, "CNY", True, 100)
    major = DataMoney(100000000.0, "CNY", False, 100)

    assert repr(minor) == "DataMoney(100,000,000,00 CNY)"
    assert repr(major) == "DataMoney(100,000,000.00 CNY)"


def test_step_audit_multiline_diff_uses_arrow_without_old_new_labels(capsys) -> None:
    _print_audit_diff_value(
        "  ",
        "value",
        None,
        {"RB.SHF": {"quantity": 1, "average_cost": 3000}},
    )

    out = capsys.readouterr().out
    assert "null ->" in out
    assert "旧值" not in out
    assert "新值" not in out
    assert "before" not in out
    assert "after" not in out
    assert "RB.SHF" in out
    assert "  \x1b[30m\x1b[103mnull ->" in out
    assert "    \x1b[30m\x1b[103m" in out


def test_step_audit_transposed_long_list_wraps_and_truncates(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((54, 20)))
    long_list = "[" + ", ".join(f"P{index}.EX" for index in range(80)) + "]"

    lines = _audit_table_lines(
        ("strategies", "products"),
        [("A1, A2", _audit_change_cell("null", long_list))],
        indent="    ",
    )
    text = "\n".join(lines)

    assert "表格已转置" in text
    assert "products" in text
    assert "P0.EX" in text
    assert "已截断" in text
    assert any(line.startswith("      ") and "\x1b[103m" in line for line in lines[2:])
    assert not any(line.startswith("\x1b[103m      ") for line in lines)


def test_step_audit_product_change_table_wraps_list_inside_cell() -> None:
    products = [
        "AP.CZC", "CJ.CZC", "EC.INE", "ER.CZC", "FB.DCE", "JD.DCE",
        "LC.GFE", "LG.DCE", "LH.DCE", "ME.CZC", "PD.GFE", "PK.CZC",
        "PS.GFE", "PT.GFE", "RO.CZC", "SF.CZC", "SI.GFE", "SM.CZC",
        "TC.CZC", "UR.CZC", "WR.SHF", "WS.CZC", "WT.CZC",
    ]
    after = _audit_scalar_sequence_text(products, width=44)
    lines = _audit_table_lines(
        ("strategies", "products"),
        [("A1, A1:1, A1a, A2, A3, A4, A5, LS A1/A5", _audit_change_cell("null", after))],
        indent="    ",
        allow_transpose=False,
    )
    text = "\n".join(lines)

    assert "null -> [AP.CZC" in text
    assert "WT.CZC]" in text
    assert "已截断" not in text
    assert any("    \x1b[30m\x1b[103m" in line for line in lines[2:])
    assert not any("\x1b[103m    " in line for line in lines)


def test_step_audit_product_output_keeps_common_strategy_list_on_one_line(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((132, 20)))
    strategies = "A1, A1:1, A1a, A2, A3, A4, A5, LS A1/A5"
    products = [
        "AP.CZC", "CJ.CZC", "EC.INE", "ER.CZC", "FB.DCE", "JD.DCE",
        "LC.GFE", "LG.DCE", "LH.DCE", "ME.CZC", "PD.GFE", "PK.CZC",
        "PS.GFE", "PT.GFE", "RO.CZC", "SF.CZC", "SI.GFE", "SM.CZC",
        "TC.CZC", "UR.CZC", "WR.SHF", "WS.CZC", "WT.CZC",
    ]
    after = _audit_scalar_sequence_text(products, width=56)

    lines = _audit_table_lines(
        ("strategies", "products"),
        [(strategies, _audit_change_cell("null", after))],
        indent="    ",
        allow_transpose=False,
    )
    plain_lines = [_strip_ansi(line) for line in lines]

    assert any(strategies in line and "null -> [AP.CZC" in line for line in plain_lines)
    assert not any(line.strip() == "LS A1/A5" for line in plain_lines)
    assert any("LC.GFE" in line for line in plain_lines)


def test_step_audit_inlines_small_complex_cell_in_table() -> None:
    lines = _audit_table_lines(
        ("strategy", "payload"),
        [("A1", {"quantity": 1, "price": 2})],
        indent="  ",
    )
    text = "\n".join(lines)

    assert "[明细" not in text
    assert "key" in text
    assert "quantity" in text
    assert "price" in text


def test_step_audit_separates_large_details_with_rules() -> None:
    lines = _audit_table_lines(
        ("strategy", "payload", "other"),
        [("A1", {"rows": [{"x": index} for index in range(8)]}, {"rows": [{"y": index} for index in range(8)]})],
        indent="  ",
    )
    text = "\n".join(lines)

    assert "[明细 1]" in text
    assert "[明细 2]" in text
    assert text.count("========================") >= 2
    assert "明细 1 (payload):" in text
    assert "明细 2 (other):" in text


def test_step_audit_groups_identical_changes_inline_without_before_after_sections(capsys) -> None:
    changes = [
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": "L1",
            "cash_pool": "P1",
            "strategies": ["A1"],
            "before": 100,
            "after": 90,
        },
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": "L2",
            "cash_pool": "P2",
            "strategies": ["A2"],
            "before": 100,
            "after": 90,
        },
    ]

    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert "合并 2 个账本 / 2 个现金池 / 2 个策略" not in out
    assert "cash pool" in out
    assert "ledgers" in out
    assert "ledger" in out
    assert "strategies" in out
    assert "L1" in out
    assert "P1" in out
    assert "A1" in out
    assert "L2" in out
    assert "P2" in out
    assert "A2" in out
    plain = _strip_ansi(out)
    assert "cash pool 总表:" not in plain
    assert "cash [CashPoolModule.cash]" in plain
    assert "cash" in out
    assert "100 -> 90" in out
    assert "100" in out
    assert "90" in out
    assert "修改前" not in out
    assert "修改后" not in out
    assert "[跨账本]" not in out


def test_step_audit_compacts_long_scalar_list_changes(capsys) -> None:
    contracts = "[" + ", ".join(f"C{i}.EX" for i in range(12)) + "]"

    _print_audit_changes("声明输出的变化", [{
        "field": "TermStructureExpandModule.expanded_contracts",
        "scope": "strategy_context",
        "strategy": "A1",
        "before": None,
        "after": contracts,
    }])

    out = capsys.readouterr().out
    assert "共 12 个" not in out
    assert "C0.EX, C1.EX, C2.EX" in out
    assert "C11.EX]" in out
    assert "null -> [C0.EX" in out


def test_step_audit_groups_cash_by_cash_pool_with_bound_ledgers(capsys) -> None:
    changes = [
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": "L1",
            "cash_pool": "P1",
            "strategies": ["A1"],
            "before": {"amount": {"repr": "10000"}, "currency": "CNY", "scale": 100, "use_minor_units": True},
            "after": {"amount": {"repr": "9000"}, "currency": "CNY", "scale": 100, "use_minor_units": True},
        },
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": "L2",
            "cash_pool": "P1",
            "strategies": ["A2"],
            "before": {"amount": {"repr": "10000"}, "currency": "CNY", "scale": 100, "use_minor_units": True},
            "after": {"amount": {"repr": "9000"}, "currency": "CNY", "scale": 100, "use_minor_units": True},
        },
    ]

    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert "cash pool" in out
    assert "ledgers" in out
    assert "P1" in out
    assert "L1, L2" in out
    assert "A1, A2" in out
    assert "DataMoney(100,00 CNY)" in out
    assert "DataMoney(90,00 CNY)" in out
    assert out.count("P1") == 1
    plain = _strip_ansi(out)
    assert "cash pool 总表:" not in plain
    assert "cash [CashPoolModule.cash]" in plain


def test_step_audit_groups_complex_ledger_fields_by_ledger(capsys) -> None:
    changes = [
        {
            "field": "LedgerModule.positions",
            "scope": "ledger",
            "ledger": "L1",
            "cash_pool": "P1",
            "strategies": ["A1"],
            "before": None,
            "after": {"RB.SHF": {"quantity": 1, "average_cost": 3000}},
        },
        {
            "field": "LedgerModule.positions",
            "scope": "ledger",
            "ledger": "L2",
            "cash_pool": "P2",
            "strategies": ["A2"],
            "before": None,
            "after": {"RB.SHF": {"quantity": 2, "average_cost": 3100}},
        },
    ]

    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert "合并 2 个账本" not in out
    assert "ledger/cash pool/strategy 路由同上" not in out
    assert "ledger" in out
    assert "cash pool" in out
    assert "strategies" in out
    assert "products" in out
    assert "L1" in out
    assert "P1" in out
    assert "A1" in out
    assert "L2" in out
    assert "P2" in out
    assert "A2" in out
    assert "RB.SHF" in out
    assert "quantity" in out
    assert "average_cost" in out


def test_step_audit_renders_positions_as_grouped_table() -> None:
    positions = {
        "AP.CZC": {
            "quantity": 0,
            "average_cost": 0.0,
            "settlement_price": None,
            "margin_reserved": None,
            "lots": [],
        },
        "CJ.CZC": {
            "quantity": 0,
            "average_cost": 0.0,
            "settlement_price": None,
            "margin_reserved": None,
            "lots": [],
        },
        "RB.SHF": {
            "quantity": 2,
            "average_cost": 3000,
            "settlement_price": 3010,
            "margin_reserved": {"amount": {"repr": "120000"}, "currency": "CNY", "scale": 100, "use_minor_units": True},
            "lots": [{"quantity": 2, "entry_price": 3000, "multiplier": 10}],
        },
    }

    text = _audit_text(_display_field_value("LedgerModule.positions", positions))

    assert "products" in text
    assert "lots_count" in text
    assert "AP.CZC, CJ.CZC" in text
    assert "RB.SHF" in text
    assert "DataMoney(1,200,00 CNY)" in text
    assert "[明细" not in text


def test_step_audit_positions_diff_lists_only_changed_products(capsys) -> None:
    before = {
        "AP.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
        "CJ.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
        "RB.SHF": {"quantity": 1, "average_cost": 3000, "lots": [{"quantity": 1, "entry_price": 3000}]},
    }
    after = {
        "AP.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
        "CJ.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
        "RB.SHF": {"quantity": 2, "average_cost": 3010, "lots": [{"quantity": 2, "entry_price": 3010}]},
    }

    _print_audit_diff_value(
        "  ",
        "value",
        _display_field_value("LedgerModule.positions", before),
        _display_field_value("LedgerModule.positions", after),
    )

    out = capsys.readouterr().out
    assert "products" in out
    assert "RB.SHF" in out
    assert "1 -> 2" in out
    assert "changed lots 1" in out
    assert "AP.CZC" not in out
    assert "CJ.CZC" not in out


def test_step_audit_positions_diff_groups_identical_initialization(capsys) -> None:
    after = {
        "AP.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
        "CJ.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
    }

    _print_audit_diff_value(
        "  ",
        "value",
        _display_field_value("LedgerModule.positions", None),
        _display_field_value("LedgerModule.positions", after),
    )

    out = capsys.readouterr().out
    assert "products" in out
    assert "全部产品" in out
    assert out.count("null -> 0") == 3
    assert "lot changes" not in out


def test_step_audit_positions_changes_render_as_one_ledger_product_table(capsys) -> None:
    changes = [
        {
            "field": "LedgerModule.positions",
            "scope": "ledger",
            "ledger": "private:L1",
            "cash_pool": "pool-1",
            "strategies": ["A1"],
            "before": None,
            "after": {
                "AP.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
                "CJ.CZC": {"quantity": 0, "average_cost": 0.0, "lots": []},
            },
        },
        {
            "field": "LedgerModule.positions",
            "scope": "ledger",
            "ledger": "private:L2",
            "cash_pool": "pool-2",
            "strategies": ["A2"],
            "before": None,
            "after": {
                "RB.SHF": {"quantity": 1, "average_cost": 0.0, "lots": []},
            },
        },
    ]

    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert "\x1b[1mpositions [LedgerModule.positions]\x1b[0m" in out
    assert out.count("positions [LedgerModule.positions]") == 1
    assert "账本 private:L1" not in out
    assert "ledger" in out
    assert "cash pool" in out
    assert "products" in out
    assert "全部产品" in out
    assert "RB.SHF" in out
    assert out.count("private:L1") == 1
    assert out.count("private:L2") == 1


def test_step_audit_keeps_merged_ledger_sources_readable(capsys) -> None:
    changes = [
        {
            "field": "MarginModule.margin_requirement",
            "scope": "ledger",
            "ledger": f"private:L{index}",
            "cash_pool": f"pool-{index}",
            "strategies": [f"A{index}"],
            "before": None,
            "after": 0.0,
        }
        for index in range(1, 9)
    ]

    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert "合并 8 个账本 / 8 个现金池 / 8 个策略" not in out
    assert "private:L1, private:L2" not in out
    assert "ledger" in out
    assert "cash pool" in out
    assert "strategies" in out
    assert "private:L8" in out
    assert "pool-8" in out
    assert "A8" in out
    assert "margin_requirement" in out
    assert "null -> 0.0" in out
    assert out.count("null") == 8
    assert out.count("0") >= 8


def test_step_audit_combines_repeated_ledger_scalar_input_fields(capsys) -> None:
    values = [
        {
            "scope": "ledger_config",
            "ledger": f"private:L{index}",
            "cash_pool": f"pool-{index}",
            "strategies": [f"A{index}"],
            "value": value,
        }
        for index, value in ((1, "Auto"), (2, "Auto"))
    ]

    _print_audit_fields("输入字段", [
        {"field": "TradingRuleModule.accounting_mode", "values": values},
        {"field": "TradingRuleModule.use_int_position", "values": [
            {**entry, "value": False}
            for entry in values
        ]},
    ])

    out = capsys.readouterr().out
    assert "账本总表" not in out
    assert "合并账本字段" not in out
    assert "accounting_mode [TradingRuleModule.accounting_mode]" in out
    assert "use_int_position [TradingRuleModule.use_int_position]" in out
    assert "accounting_mode" in out
    assert "use_int_position" in out
    assert out.count("ledger") == 1
    assert out.count("private:L1") == 1
    assert out.count("private:L2") == 1


def test_step_audit_combines_repeated_strategy_scalar_input_fields(capsys) -> None:
    values = [
        {
            "scope": "strategy_config",
            "strategy": strategy,
            "value": value,
        }
        for strategy, value in (("A1", "CNY"), ("A2", "CNY"))
    ]

    _print_audit_fields("输入字段", [
        {"field": "CashPoolModule.base_currency", "values": values},
        {"field": "CashPoolModule.initial_capital_major", "values": [
            {**entry, "value": 100000000.0}
            for entry in values
        ]},
        {"field": "EngineModule.engine_mode", "values": [
            {**entry, "value": "auto"}
            for entry in values
        ]},
    ])

    out = capsys.readouterr().out
    assert "合并策略字段" not in out
    assert "\x1b[1mbase_currency [CashPoolModule.base_currency]\x1b[0m" in out
    assert "base_currency [CashPoolModule.base_currency]" in out
    assert "initial_capital_major [CashPoolModule.initial_capital_major]" in out
    assert "engine_mode [EngineModule.engine_mode]" in out
    assert "base_currency" in out
    assert "initial_capital_major" in out
    assert "engine_mode" in out
    assert "A1, A2" in out
    assert out.count("strategies") == 1
    assert "策略配置 A1, A2 = CNY" not in out


def test_step_audit_combines_strategy_fields_with_mixed_sources_as_subcolumns(capsys) -> None:
    strategies = ["A1", "A2"]

    def values(scope: str, value, *, include_strategy: bool = True):
        if not include_strategy:
            return [{"scope": scope, "value": value}]
        return [{"scope": scope, "strategy": strategy, "value": value} for strategy in strategies]

    _print_audit_fields("输入字段", [
        {
            "field": "MarketDataModule.required_data_source",
            "values": [
                *values("context", [], include_strategy=False),
                *values("strategy_context", []),
                *values("strategy_config", None),
            ],
        },
        {
            "field": "MarketDataModule.required_frequency",
            "values": [
                *values("strategy_context", "MIN1"),
                *values("strategy_config", None),
            ],
        },
        {
            "field": "ProductSelectionModule.products",
            "values": values("strategy_context", ["AP.CZC", "CJ.CZC"]),
        },
        {
            "field": "StrategyBookModule.ledger_session_policy",
            "values": values("strategy_config", "error"),
        },
        {
            "field": "TermStructureExpandModule.contract_metadata",
            "values": [
                *values("strategy_context", {"type": "ContractMetadataTable", "rows": []}),
                *values("strategy_config", None),
            ],
        },
    ])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "合并策略字段" not in plain
    assert "策略上下文" not in plain
    assert "策略配置" not in plain
    assert "required_data_source [MarketDataModule.required_data_source]" in plain
    assert "required_frequency [MarketDataModule.required_frequency]" in plain
    assert "products [ProductSelectionModule.products]" in plain
    assert "ledger_session_policy [StrategyBookModule.ledger_session_policy]" in plain
    assert "contract_metadata [TermStructureExpandModule.contract_metadata]" in plain
    assert plain.count("strategies") == 1
    assert "required_data_source.shared" in plain
    assert "required_data_source.context" in plain
    assert "required_data_source.config" in plain
    assert "required_frequency.context" in plain
    assert "required_frequency.config" in plain
    assert "contract_metadata.context" in plain
    assert "contract_metadata.config" in plain
    assert "A1, A2" in plain


def test_step_audit_strategy_scalar_table_merges_only_identical_rows(capsys) -> None:
    values = [
        {"scope": "strategy_config", "strategy": "A1", "value": "CNY"},
        {"scope": "strategy_config", "strategy": "A2", "value": "CNY"},
        {"scope": "strategy_config", "strategy": "A3", "value": "USD"},
    ]

    _print_audit_fields("输入字段", [
        {"field": "CashPoolModule.base_currency", "values": values},
        {"field": "EngineModule.engine_mode", "values": [
            {**entry, "value": "auto"}
            for entry in values
        ]},
    ])

    out = capsys.readouterr().out
    assert "合并策略字段" not in out
    assert "strategies" in out
    assert "base_currency" in out
    assert "engine_mode" in out
    assert "A1, A2" in out
    assert "A3" in out
    assert "表格已转置" not in out


def test_step_audit_single_strategy_scalar_uses_strategy_total_table(capsys) -> None:
    _print_audit_fields("输入字段", [{
        "field": "EngineModule.engine_mode",
        "values": [
            {"scope": "strategy_config", "strategy": "A1", "value": "auto"},
            {"scope": "strategy_config", "strategy": "A2", "value": "auto"},
        ],
    }])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "合并策略字段" not in plain
    assert "engine_mode [EngineModule.engine_mode]" in plain
    assert "strategies" in out
    assert "engine_mode" in out
    assert "value" not in out


def test_step_audit_single_ledger_scalar_uses_ledger_total_table(capsys) -> None:
    _print_audit_fields("输入字段", [{
        "field": "TradingRuleModule.accounting_mode",
        "values": [
            {"scope": "ledger_config", "ledger": "L1", "cash_pool": "P1", "strategies": ["A1"], "value": "Auto"},
        ],
    }])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "账本总表:" not in plain
    assert "accounting_mode [TradingRuleModule.accounting_mode]" in plain
    assert "ledger" in out
    assert "cash pool" in out
    assert "accounting_mode" in out


def test_step_audit_single_cash_scalar_uses_cash_pool_total_table(capsys) -> None:
    _print_audit_fields("输入字段", [{
        "field": "CashPoolModule.cash",
        "values": [
            {"scope": "ledger", "ledger": "L1", "cash_pool": "P1", "strategies": ["A1"], "value": 100},
        ],
    }])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "cash pool 总表:" not in plain
    assert "cash [CashPoolModule.cash]" in plain
    assert "cash pool" in out
    assert "ledgers" in out
    assert "cash" in out


def test_step_audit_splits_wide_combined_ledger_fields_by_terminal_width(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((72, 20)))
    values = [
        {
            "scope": "ledger_config",
            "ledger": f"private:ledger_with_long_name_{index}",
            "cash_pool": f"private:cash_pool_with_long_name_{index}",
            "strategies": [f"A{index}"],
            "value": "auto",
        }
        for index in range(1, 3)
    ]

    _print_audit_fields("输入字段", [
        {"field": "TradingRuleModule.margin_mode", "values": values},
        {"field": "TradingRuleModule.accounting_mode", "values": [{**entry, "value": "Auto"} for entry in values]},
        {"field": "TradingRuleModule.fee_mode", "values": [{**entry, "value": "auto"} for entry in values]},
        {"field": "TradingRuleModule.fixed_fee_rate", "values": [{**entry, "value": 0.0} for entry in values]},
        {"field": "TradingRuleModule.transaction_fee_source", "values": [{**entry, "value": "fixed"} for entry in values]},
        {"field": "TradingRuleModule.fixed_margin_ratio", "values": [{**entry, "value": 1.0} for entry in values]},
        {"field": "TradingRuleModule.margin_ratio_source", "values": [{**entry, "value": "fixed"} for entry in values]},
        {"field": "TradingRuleModule.use_int_position", "values": [{**entry, "value": False} for entry in values]},
        {"field": "TradingRuleModule.daily_mark_to_market_enabled", "values": [{**entry, "value": False} for entry in values]},
        {"field": "TradingRuleModule.cost_basis_method", "values": [{**entry, "value": "FIFO"} for entry in values]},
    ])

    out = capsys.readouterr().out
    assert "账本总表" not in out
    assert "合并账本字段" not in out
    assert "margin_mode" in out
    assert "cost_basis_method" in out
    assert "columns 1/" in out
    plain = _strip_ansi(out)
    split_headers = [
        line.strip()
        for line in plain.splitlines()
        if line.strip().startswith("ledger")
    ]
    assert split_headers
    assert any("margin_mode" in line for line in split_headers)
    assert all("cash pool" not in line and "strategies" not in line for line in split_headers)
    assert max(len(_strip_ansi(line)) for line in out.splitlines()) <= 132


def test_step_audit_combines_strategy_and_ledger_tables_across_interleaved_sort_order(capsys, monkeypatch) -> None:
    order = {
        "FactorSignalModule.warmup_mode": (1, 0, ""),
        "FeeModule.fee_mode": (2, 0, ""),
        "FactorModule.factor": (3, 0, ""),
        "MarginModule.margin_mode": (4, 0, ""),
        "GroupMembershipModule.allocation_policy": (5, 0, ""),
    }
    monkeypatch.setattr(
        "tools.cli.modules.backtest.controller._audit_field_sort_key",
        lambda field: order.get(field, (99, 0, field)),
    )
    strategy_values = [
        {"scope": "strategy_config", "strategy": "A1", "value": "same"},
        {"scope": "strategy_config", "strategy": "A2", "value": "same"},
    ]
    ledger_values = [
        {"scope": "ledger_config", "ledger": "L1", "cash_pool": "P1", "strategies": ["A1"], "value": "same"},
        {"scope": "ledger_config", "ledger": "L2", "cash_pool": "P2", "strategies": ["A2"], "value": "same"},
    ]

    _print_audit_fields("输入字段", [
        {"field": "FactorSignalModule.warmup_mode", "values": strategy_values},
        {"field": "FeeModule.fee_mode", "values": ledger_values},
        {"field": "FactorModule.factor", "values": [{**entry, "value": "$USER:F"} for entry in strategy_values]},
        {"field": "MarginModule.margin_mode", "values": ledger_values},
        {"field": "GroupMembershipModule.allocation_policy", "values": [{**entry, "value": "rank"} for entry in strategy_values]},
    ])

    plain = _strip_ansi(capsys.readouterr().out)
    strategy_headers = [line for line in plain.splitlines() if line.strip().startswith("strategies")]
    ledger_headers = [line for line in plain.splitlines() if line.strip().startswith("ledger")]
    assert len(strategy_headers) == 1
    assert "warmup_mode" in strategy_headers[0]
    assert "factor" in strategy_headers[0]
    assert "allocation_policy" in strategy_headers[0]
    assert len(ledger_headers) == 1
    assert "fee_mode" in ledger_headers[0]
    assert "margin_mode" in ledger_headers[0]


def test_step_audit_transposes_after_combining_strategy_total_table(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((72, 20)))
    records = [
        {
            "field": f"ExampleModule.strategy_field_{index}",
            "values": [
                {"scope": "strategy_config", "strategy": "A1", "value": f"value-{index}"},
            ],
        }
        for index in range(8)
    ]

    _print_audit_fields("输入字段", records)

    plain = _strip_ansi(capsys.readouterr().out)
    assert plain.count("strategy_field_") >= 8
    assert "表格已转置" in plain
    assert "原列数 9" in plain


def test_step_audit_displays_backend_null_dmtm_ledger_config_verbatim(capsys) -> None:
    values = [
        {
            "scope": "ledger_config",
            "ledger": "private:L1",
            "cash_pool": "private:P1",
            "strategies": ["A1"],
            "value": None,
        }
    ]

    _print_audit_fields("输入字段", [
        {"field": "TradingRuleModule.cost_basis_method", "values": values},
        {"field": "TradingRuleModule.daily_mark_to_market_enabled", "values": values},
    ])

    out = capsys.readouterr().out
    assert "账本总表" not in out
    assert "合并账本字段" not in out
    assert "cost_basis_method" in out
    assert "daily_mark_to_market_enabled" in out
    assert "null" in out


def test_step_audit_prefers_ledger_total_over_empty_strategy_defaults(capsys) -> None:
    values = [
        {"scope": "strategy_config", "strategy": "A1", "value": None},
        {"scope": "strategy_config", "strategy": "A2", "value": None},
        {"scope": "ledger", "ledger": "L1", "cash_pool": "P1", "strategies": ["A1"], "value": 0.0},
        {"scope": "ledger", "ledger": "L2", "cash_pool": "P2", "strategies": ["A2"], "value": 0.0},
    ]

    _print_audit_fields("输入字段", [{
        "field": "MarginModule.margin_deficit",
        "values": values,
    }])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "margin_deficit [MarginModule.margin_deficit]" in plain
    assert "策略配置" not in plain
    assert "合并 " not in plain
    assert "ledger" in plain
    assert "cash pool" in plain
    assert "L1" in plain
    assert "L2" in plain
    assert "0.0" in plain


def test_step_audit_prints_ledger_routes_without_same_as_abbreviation(capsys) -> None:
    values = [
        {
            "scope": "ledger_config",
            "ledger": f"private:L{index}",
            "cash_pool": f"pool-{index}",
            "strategies": [f"A{index}"],
            "value": "Auto",
        }
        for index in range(1, 4)
    ]
    changes = [
        {
            "field": "CashPoolModule.cash",
            "scope": "ledger",
            "ledger": f"private:L{index}",
            "cash_pool": f"pool-{index}",
            "strategies": [f"A{index}"],
            "before": None,
            "after": 100,
        }
        for index in range(1, 4)
    ]

    _print_audit_fields(
        "输入字段",
        [{"field": "TradingRuleModule.accounting_mode", "values": values}],
    )
    _print_audit_fields(
        "输入字段",
        [{"field": "TradingRuleModule.cost_basis_method", "values": values}],
    )
    _print_audit_changes("账本与现金池变化", changes)

    out = capsys.readouterr().out
    assert out.count("private:L1") == 3
    assert out.count("pool-1") == 3
    assert "ledger/cash pool/strategy 路由同上" not in out
    assert "accounting_mode" in out
    assert "cost_basis_method" in out
    assert "cash" in out
    assert "null -> 100" in out
    assert "Auto" in out
    assert "100" in out


def test_step_audit_groups_identical_strategy_changes_inline(capsys) -> None:
    changes = [
        {
            "field": "TargetModule.target_weights",
            "scope": "strategy_context",
            "strategy": "A1",
            "before": None,
            "after": {"CJ.CZC": 0.5, "SF.CZC": 0.5},
        },
        {
            "field": "TargetModule.target_weights",
            "scope": "strategy_context",
            "strategy": "A2",
            "before": None,
            "after": {"CJ.CZC": 0.5, "SF.CZC": 0.5},
        },
        {
            "field": "TargetModule.target_weights",
            "scope": "strategy_context",
            "strategy": "A3",
            "before": None,
            "after": {"SI.GFE": 1.0},
        },
    ]

    _print_audit_changes("声明输出的变化", changes)

    out = capsys.readouterr().out
    assert "before:" not in out
    assert "after:" not in out
    assert "strategies" in out
    assert "A1, A2" in out
    assert "A3" in out
    assert "CJ.CZC" in out
    assert "SI.GFE" in out
    assert "null -> key     value" in out
    assert "before =" not in out
    assert "after =" not in out


def test_step_audit_expands_long_short_leg_strategy_fields(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((90, 20)))

    _print_audit_fields("输入字段", [
        {
            "field": "LongShortCompositionModule.long_leg_strategy_ids",
            "values": [{"scope": "strategy_config", "strategy": "LS A1/A5", "value": [{
                "group_id": "bg_mpuvbhda_1",
                "strategy_id": "bg_mpuvbhda_1",
                "weight": 1.0,
            }]}],
        },
        {
            "field": "LongShortCompositionModule.short_leg_strategy_ids",
            "values": [{"scope": "strategy_config", "strategy": "LS A1/A5", "value": [{
                "group_id": "bg_mpuwogji_5",
                "strategy_id": "bg_mpuwogji_5",
                "weight": 1.0,
            }]}],
        },
        {
            "field": "LongShortCompositionModule.strategy_kind",
            "values": [{"scope": "strategy_config", "strategy": "LS A1/A5", "value": "long_short"}],
        },
    ])

    out = capsys.readouterr().out
    assert "long_leg_strategy_ids.group_id" in out
    assert "long_leg_strategy_ids.strategy_id" in out
    assert "short_leg_strategy_ids.weight" in out
    assert "strategy_kind" in out
    assert "表格已转置" in out
    assert "[明细" not in out


def test_step_audit_inlines_medium_target_weights_in_strategy_table(capsys) -> None:
    _print_audit_fields("输入字段", [
        {
            "field": "TargetStrategyModule.target_weights",
            "values": [{"scope": "strategy_context", "strategy": "A2", "value": {
                "LH.DCE": 0.25,
                "LC.GFE": 0.25,
                "SM.CZC": 0.25,
                "PS.GFE": 0.25,
            }}],
        },
        {
            "field": "EngineModule.engine_mode",
            "values": [{"scope": "strategy_context", "strategy": "A2", "value": "auto"}],
        },
    ])

    out = capsys.readouterr().out
    assert "target_weights" in out
    assert "key" in out
    assert "LH.DCE" in out
    assert "PS.GFE" in out
    assert "[明细" not in out


def test_step_audit_keeps_raw_deltas_in_ledger_table(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((90, 20)))

    _print_audit_fields("输入字段", [
        {
            "field": "OrderConstructModule.raw_deltas",
            "values": [{
                "scope": "ledger",
                "ledger": "private:L1",
                "cash_pool": "private:P1",
                "strategies": ["A1"],
                "value": {"CJ.CZC": 2, "SF.CZC": -1},
            }],
        },
        {
            "field": "OrderConstructModule.max_order_count",
            "values": [{
                "scope": "ledger",
                "ledger": "private:L1",
                "cash_pool": "private:P1",
                "strategies": ["A1"],
                "value": 10,
            }],
        },
    ])

    out = capsys.readouterr().out
    assert "raw_deltas [OrderConstructModule.raw_deltas]" in out
    assert "max_order_count [OrderConstructModule.max_order_count]" in out
    assert "ledger" in out
    assert "cash pool" in out
    assert "strategies" in out
    assert "CJ.CZC" in out
    assert "SF.CZC" in out
    assert "账本 private:L1" not in out


def test_step_audit_maps_strategy_raw_deltas_to_ledger_product_table(capsys) -> None:
    with _audit_step_event_context({
        "ledgers_before": [
            {"ledger": "private:L1", "cash_pool": "private:P1", "strategies": ["A1"]},
            {"ledger": "private:L2", "cash_pool": "private:P2", "strategies": ["A2"]},
        ]
    }):
        _print_audit_changes("声明输出的变化", [
            {
                "field": "OrderConstructModule.raw_deltas",
                "scope": "strategy_context",
                "strategy": "A1",
                "before": None,
                "after": {"CJ.CZC": 2.5, "SF.CZC": 0, "SM.CZC": -1.5},
            },
            {
                "field": "OrderConstructModule.raw_deltas",
                "scope": "strategy_context",
                "strategy": "A2",
                "before": None,
                "after": {"CJ.CZC": 0, "SF.CZC": 0},
            },
        ])

    out = capsys.readouterr().out
    assert "raw_deltas [OrderConstructModule.raw_deltas]" in out
    assert "ledger" in out
    assert "cash pool" in out
    assert "strategies" in out
    assert "product" in out
    assert "private:L1" in out
    assert "private:P1" in out
    assert "A1" in out
    assert "CJ.CZC" in out
    assert "SM.CZC" in out
    assert "其余 1 个产品" in out
    assert "其余 2 个产品" in out
    assert "[明细" not in out


def test_step_audit_maps_strategy_deltas_to_same_ledger_product_table(capsys) -> None:
    with _audit_step_event_context({
        "ledgers_before": [
            {"ledger": "private:L1", "cash_pool": "private:P1", "strategies": ["A1"]},
        ]
    }):
        _print_audit_changes("声明输出的变化", [{
            "field": "OrderConstructModule.deltas",
            "scope": "strategy_context",
            "strategy": "A1",
            "before": None,
            "after": {"CJ.CZC": 2, "SF.CZC": 0},
        }])

    out = capsys.readouterr().out
    assert "deltas [OrderConstructModule.deltas]" in out
    assert "private:L1" in out
    assert "private:P1" in out
    assert "A1" in out
    assert "CJ.CZC" in out
    assert "其余 1 个产品" in out


def test_step_audit_reuses_identical_detail_refs() -> None:
    detail = {"items": list(range(12)), "note": "same-detail"}

    lines = _audit_table_lines(
        ("strategy", "signal_value", "current_historical_fields.shared"),
        [
            ("A1", detail, detail),
            ("A2", detail, detail),
        ],
    )

    text = "\n".join(lines)
    assert text.count("[明细 1]") == 2
    assert text.count("[明细 2]") == 2
    assert "明细 3" not in text


def test_step_audit_transposes_when_table_would_split_three_column_groups(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((64, 20)))

    lines = _audit_table_lines(
        ("strategies", "field_a", "field_b", "field_c", "field_d", "field_e", "field_f", "field_g"),
        [
            ("A1", "a" * 20, "b" * 20, "c" * 20, "d" * 20, "e" * 20, "f" * 20, "g" * 20),
            ("A2", "a" * 20, "b" * 20, "c" * 20, "d" * 20, "e" * 20, "f" * 20, "g" * 20),
        ],
    )

    text = "\n".join(lines)
    assert "表格已转置" in text
    assert "field_a" in text
    assert "A1" in text


def test_step_audit_renders_trade_intent_changes_as_tables(capsys) -> None:
    changes = [
        {
            "field": "TargetStrategyModule.trade_intent",
            "scope": "strategy_context",
            "strategy": "A1",
            "before": None,
            "after": {
                "type": "TargetWeightIntent",
                "reason": "group_quantile",
                "weights": {"CJ.CZC": 0.5, "SF.CZC": 0.5},
            },
        },
        {
            "field": "TargetStrategyModule.trade_intent",
            "scope": "strategy_context",
            "strategy": "A2",
            "before": None,
            "after": {
                "type": "TargetWeightIntent",
                "reason": "group_quantile",
                "weights": {"CJ.CZC": 0.5, "SF.CZC": 0.5},
            },
        },
    ]

    _print_audit_changes("声明输出的变化", changes)

    out = capsys.readouterr().out
    assert "trade_intent [TargetStrategyModule.trade_intent]" in out
    assert "before:" not in out
    assert "after:" not in out
    assert "A1, A2" in out
    assert "reason" in out
    assert "null -> TargetWeightIntent(reason=group_quantile; 2 weights)" in out
    assert "group_quantile" in out
    assert "target_weight" not in out
    assert "[跨策略]" not in out


def test_step_audit_groups_shared_and_strategy_context_sources(capsys) -> None:
    _print_audit_changes("声明输出的变化", [
        {"field": "MarketDataModule.required_data_source", "scope": "context", "before": None, "after": []},
        {
            "field": "MarketDataModule.required_data_source",
            "scope": "strategy_context",
            "strategy": "A1",
            "before": None,
            "after": [],
        },
        {
            "field": "MarketDataModule.required_data_source",
            "scope": "strategy_context",
            "strategy": "A2",
            "before": None,
            "after": [],
        },
    ])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "共享上下文" not in plain
    assert "策略上下文" not in plain
    assert "required_data_source.shared" in plain
    assert "required_data_source.context" in plain
    assert "A1, A2" in plain
    assert "null -> auto（自动选择）" in out
    assert "[合并]" not in out


def test_step_audit_collapses_repeated_strategy_mapping_values(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((88, 20)))
    _print_audit_changes("声明输出的变化", [{
        "field": "RunWindowModule.strategy_windows",
        "scope": "context",
        "before": None,
        "after": {
            "A1": {
                "start_dt": {"precision": "exact", "ts": "2026-01-01 09:00:00+08:00", "tz": "Asia/Shanghai"},
                "end_dt": {"precision": "exact", "ts": "2026-01-31 15:00:00+08:00", "tz": "Asia/Shanghai"},
                "warmup_window": "0 days 00:02:00",
            },
            "A2": {
                "start_dt": {"precision": "exact", "ts": "2026-01-01 09:00:00+08:00", "tz": "Asia/Shanghai"},
                "end_dt": {"precision": "exact", "ts": "2026-01-31 15:00:00+08:00", "tz": "Asia/Shanghai"},
                "warmup_window": "0 days 00:02:00",
            },
            "A3": {
                "start_dt": {"precision": "exact", "ts": "2026-01-01 09:00:00+08:00", "tz": "Asia/Shanghai"},
                "end_dt": {"precision": "exact", "ts": "2026-01-31 15:00:00+08:00", "tz": "Asia/Shanghai"},
                "warmup_window": "0 days 00:02:00",
            },
        },
    }])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "表格已转置" in plain
    assert "strategies" in plain
    assert "start_dt" in plain
    assert "end_dt" in plain
    assert "warmup_window" in plain
    assert "A1, A2, A3" in out
    assert "DataTime(ts=2026-01-01 09:00:00+08:00, tz=Asia/Shanghai," in plain
    assert "Asia/Shanghai" in out
    assert "exact" in out
    assert "DataTime(ts=2026-01-31 15:00:00+08:00, tz=Asia/Shanghai," in plain
    assert "0 days 00:02:00" in out
    assert '"A1, A2, A3": {' not in out


def test_step_audit_run_window_envelope_renders_datatime_values(capsys) -> None:
    _print_audit_changes("声明输出的变化", [{
        "field": "RunWindowModule.run_window_envelope",
        "scope": "context",
        "before": None,
        "after": {
            "start_dt": {"precision": "exact", "ts": "2026-01-01 09:00:00+08:00", "tz": "Asia/Shanghai"},
            "end_dt": {"precision": "exact", "ts": "2026-01-31 15:00:00+08:00", "tz": "Asia/Shanghai"},
        },
    }])

    out = capsys.readouterr().out
    assert "DataTime.ts" in out
    assert "DataTime.tz" in out
    assert "DataTime.precision" in out
    assert "envelope" in out
    assert "start_dt" in out
    assert "2026-01-01 09:00:00+08:00" in out
    assert "Asia/Shanghai" in out
    assert "exact" in out
    assert "end_dt" in out
    assert "2026-01-31 15:00:00+08:00" in out


def test_step_audit_field_state_baseline_renders_as_product_field_table(capsys) -> None:
    _print_audit_changes("声明输出的变化", [{
        "field": "MarketDataModule.field_state_baseline",
        "scope": "context",
        "before": None,
        "after": {
            "RB.SHF": {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.07},
            "SHFE|F|RB|2610": {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.07},
        },
    }])

    out = capsys.readouterr().out
    assert "field" in out
    assert "RB.SHF" in out
    assert "SHFE|F|RB|2610" in out
    assert "策略 RB.SHF" not in out
    assert "VolumeMultiple" in out
    assert "LongMarginRatioByMoney" in out


def test_step_audit_field_state_baseline_samples_products_then_transposes(capsys) -> None:
    after = {
        f"P{index}.EX": {"VolumeMultiple": index, "LongMarginRatioByMoney": index / 100}
        for index in range(10)
    }
    _print_audit_changes("声明输出的变化", [{
        "field": "MarketDataModule.field_state_baseline",
        "scope": "context",
        "before": None,
        "after": after,
    }])

    out = capsys.readouterr().out
    assert "sample products: 6/10" in out
    assert "field" in out
    assert "VolumeMultiple" in out
    assert "LongMarginRatioByMoney" in out
    assert "P0.EX" in out
    assert "P9.EX" in out
    assert "P4.EX" not in out


def test_step_audit_field_state_baseline_filters_to_event_products(capsys) -> None:
    after = {
        "SM.CZC": {"VolumeMultiple": 5, "LongMarginRatioByMoney": 0.12},
        "CZCE|F|SM|2603": {"VolumeMultiple": 5, "LongMarginRatioByMoney": 0.12},
        **{f"P{index}.EX": {"VolumeMultiple": index, "LongMarginRatioByMoney": index / 100} for index in range(10)},
    }
    with _audit_step_event_context({
        "current_event": {
            "event_kind": "ORDER",
            "subjects": [{"strategy": "A1", "subject": "CZCE|F|SM|2603", "action": "scheduled"}],
        },
    }):
        _print_audit_changes("声明输出的变化", [{
            "field": "MarketDataModule.field_state_baseline",
            "scope": "context",
            "before": None,
            "after": after,
        }])

    out = capsys.readouterr().out
    assert "event products: CZCE|F|SM|2603, SM.CZC" in out
    assert "sample products:" not in out
    assert "CZCE|F|SM|2603" in out
    assert "SM.CZC" in out
    assert "P0.EX" not in out
    assert "P9.EX" not in out


def test_step_audit_field_state_baseline_diff_only_prints_changed_rows(capsys) -> None:
    _print_audit_changes("声明输出的变化", [{
        "field": "MarketDataModule.field_state_baseline",
        "scope": "context",
        "before": {
            "RB.SHF": {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.07},
            "AG.SHF": {"VolumeMultiple": 15.0, "LongMarginRatioByMoney": 0.09},
        },
        "after": {
            "RB.SHF": {"VolumeMultiple": 10.0, "LongMarginRatioByMoney": 0.08},
            "AG.SHF": {"VolumeMultiple": 15.0, "LongMarginRatioByMoney": 0.09},
        },
    }])

    out = capsys.readouterr().out
    assert "RB.SHF" in out
    assert "AG.SHF" not in out
    assert "0.07 -> 0.08" in out
    assert "AG.SHF" not in out


def test_step_audit_renders_dict_of_dict_scalars_as_table() -> None:
    text = _audit_text({
        "close": {"RB.SHF": 3187.0, "SHFE|F|RB|2610": 3187.0},
        "volume": {"RB.SHF": 9496.0, "SHFE|F|RB|2610": 9496.0},
    })

    assert "key" in text
    assert "RB.SHF" in text
    assert "close" in text
    assert '"close"' not in text
    assert "{" not in text


def test_step_audit_renders_event_drafts_as_table() -> None:
    text = _audit_text([
        {
            "type": "EventDraft",
            "kind": "ledger",
            "timestamp": "2026-01-01 15:00:00",
            "strategy": "",
            "ledger": "private:L1",
            "payload": {"kind": "margin_check", "ledger_id": "private:L1", "extra": {"x": 1}},
            "index_key": None,
        }
    ])

    assert "timestamp" in text
    assert "margin_check" in text
    assert "private:L1" in text
    assert "明细 1 (details):" not in text
    assert "details" in text
    assert "extra" in text
    assert '"extra"' not in text


def test_step_event_payload_change_renders_order_diff_table(capsys) -> None:
    before = [{
        "timestamp": "2026-01-05 09:02:00+08:00",
        "strategy": "A1",
        "instrument": "CZCE|F|SM|2603",
        "intent_quantity": 438,
        "quantity": 438,
        "status": "scheduled",
        "reject_reason": "",
        "order_id": "A1-1",
        "fields": {
            "price_timestamp": "2026-01-05 09:03:00+08:00",
            "execution_price_basis": "open",
            "effective_price": 5910,
        },
    }]
    after = [{
        **before[0],
        "fields": {
            **before[0]["fields"],
            "fee_open_quantity": 438,
            "fee_close_quantity": 0,
            "fee_cost": 258858,
        },
    }]

    _print_event_payload_changes([
        {"scope": "strategy", "strategy": "A1", "before": before, "after": after},
    ])

    out = capsys.readouterr().out
    assert "订单变化表 rows=1" in out
    assert "effective_price" in out
    assert "fee_open_quantity" in out
    assert "null -> 438" in out
    assert "null -> 258858" in out
    assert "before =" not in out
    assert "after =" not in out


def test_step_audit_renders_lifecycle_notices_as_single_table() -> None:
    text = _audit_text([
        {
            "type": "EventDraft",
            "kind": "trade_intent",
            "timestamp": "2026-01-08 15:00:00+08:00",
            "strategy": "A1",
            "ledger": "",
            "payload": {
                "product": "RS.CZC",
                "contract_product": "RS609.CZC",
                "contract_object": {"type": "Contract", "repr": "RS609.CZC"},
                "last_trade_date": "2026-01-08",
                "delivery_date": "2026-01-12",
                "lifecycle_source_type": "local_db",
                "lifecycle_source": "AKShare CZCE contract lifecycle",
                "lifecycle_source_function": "futures_contract_info_czce",
                "lifecycle_source_query_date": "20260108",
                "lifecycle_exchange": "CZCE",
                "notice_date": float("nan"),
                "notice_type": "force_close",
                "notice_reason": "auto_close_date",
            },
            "index_key": None,
        },
        {
            "type": "EventDraft",
            "kind": "trade_intent",
            "timestamp": "2026-01-09 15:00:00+08:00",
            "strategy": "A2",
            "ledger": "",
            "payload": {
                "product": "EC.INE",
                "contract_product": "EC2602.INE",
                "last_trade_date": "2026-01-09",
                "delivery_date": "2026-01-13",
                "notice_type": "force_close",
                "notice_reason": "auto_close_date",
            },
            "index_key": None,
        },
    ])

    assert "notice_time" in text
    assert "strategy" in text
    assert "product" in text
    assert "contract" in text
    assert "lifecycle_source_type" in text
    assert "lifecycle_source" in text
    assert "lifecycle_source_function" in text
    assert "lifecycle_source_query_date" in text
    assert "lifecycle_exchange" in text
    assert "RS.CZC" in text
    assert "RS609.CZC" in text
    assert "EC2602.INE" in text
    assert "local_db" in text
    assert "AKShare CZCE contract lifecycle" in text
    assert "futures_contract_info_czce" in text
    assert "nan" not in text
    assert "auto_close_date" in text
    assert "明细" not in text
    assert '"payload"' not in text


def test_step_audit_lifecycle_notice_changes_prefer_merged_context(capsys) -> None:
    common_after = [
        {
            "type": "EventDraft",
            "timestamp": "2026-01-28 15:00:00+08:00",
            "strategy": "A1",
            "payload": {
                "product": "FB.DCE",
                "contract_product": "DCE|F|FB|2603",
                "notice_type": "force_close",
                "notice_reason": "auto_close_date",
                "last_trade_date": "2026-03-02",
                "delivery_date": "2026-03-05",
                "lifecycle_source": "DCE product rule + trading calendar derived contract lifecycle",
                "lifecycle_source_function": "exchange_rule_dayk_calendar_derived",
            },
        },
        {
            "type": "EventDraft",
            "timestamp": "2026-01-28 15:00:00+08:00",
            "strategy": "A2",
            "payload": {
                "product": "JD.DCE",
                "contract_product": "DCE|F|JD|2603",
                "notice_type": "force_close",
                "notice_reason": "auto_close_date",
                "last_trade_date": "2026-03-26",
                "delivery_date": "2026-03-31",
                "lifecycle_source": "DCE product rule + trading calendar derived contract lifecycle",
                "lifecycle_source_function": "exchange_rule_dayk_calendar_derived",
            },
        },
    ]
    _print_audit_changes("声明输出的变化", [
        {
            "field": "DeliveryForceCloseModule.force_close_notices",
            "scope": "context",
            "before": None,
            "after": common_after,
        },
        {
            "field": "DeliveryForceCloseModule.force_close_notices",
            "scope": "strategy_context",
            "strategy": "A1",
            "before": None,
            "after": [common_after[0]],
        },
    ])

    out = capsys.readouterr().out
    assert "合并事件草稿（所有 active strategies）" in out
    assert out.count("force_close_notices [DeliveryForceCloseModule.force_close_notices]") == 1
    assert "before =" not in out
    assert "after =" not in out
    assert "策略上下文 A1" not in out
    assert "lifecycle_source_function" in out


def test_step_audit_renders_sampled_event_drafts_as_table() -> None:
    text = _audit_text({
        "type": "list",
        "length": 300,
        "truncated": True,
        "sample": {
            "head": [
                {
                    "type": "EventDraft",
                    "kind": "ledger",
                    "timestamp": "2026-01-01 09:01:00",
                    "strategy": "",
                    "ledger": "private:L1",
                    "payload": {"kind": "margin_check", "ledger_id": "private:L1"},
                    "index_key": None,
                },
                {
                    "type": "EventDraft",
                    "kind": "ledger",
                    "timestamp": "2026-01-01 09:02:00",
                    "strategy": "",
                    "ledger": "private:L2",
                    "payload": {"kind": "second_margin_check", "ledger_id": "private:L2"},
                    "index_key": None,
                }
            ],
            "tail": [
                {
                    "type": "EventDraft",
                    "kind": "ledger",
                    "timestamp": "2026-01-01 15:00:00",
                    "strategy": "",
                    "ledger": "private:L1",
                    "payload": {"kind": "margin_check", "ledger_id": "private:L1"},
                    "index_key": None,
                }
            ],
        },
    })

    assert "事件草稿列表 length=300 truncated=True" in text
    assert "sample = 仅显示 head；tail 已省略" in text
    assert "sample.rows = 仅显示 1/2 行；其余 sample 行已省略" in text
    assert "sample.head:" in text
    assert "sample.tail:" not in text
    assert "margin_check" in text
    assert "second_margin_check" not in text
    assert "15:00:00" not in text
    assert '"payload"' not in text
    assert "明细" not in text


def test_step_audit_renders_event_payload_lists_as_table() -> None:
    text = _audit_text([
        {"kind": "margin_check", "ledger_id": "private:L1"},
        {"kind": "force_close", "product": "RB.SHF", "notice_reason": "expiry"},
    ])

    assert "event" in text
    assert "subject" in text
    assert "margin_check" in text
    assert "private:L1" in text
    assert "RB.SHF" in text
    assert '"ledger_id"' not in text


def test_step_audit_renders_orders_as_table_with_field_details() -> None:
    text = _audit_text([
        {
            "fields": {
                "effective_price": 5924.0,
                "execution_price_basis": "open",
                "fee_cost": 1263.0,
                "price_timestamp": "2026-01-05 09:02:00+08:00",
            },
            "instrument": "CZCE|F|SM|2603",
            "intent_quantity": 421.0,
            "order_id": "order-1",
            "quantity": 421.0,
            "reject_reason": None,
            "status": "filled",
            "strategy": "A1",
            "timestamp": "2026-01-05 09:01:00+08:00",
        }
    ])

    assert "timestamp" in text
    assert "instrument" in text
    assert "intent_qty" in text
    assert "CZCE|F|SM|2603" in text
    assert "filled" in text
    assert "明细 1 (fields):" not in text
    assert "effective_price" in text
    assert "fee_cost" in text
    assert '"fields"' not in text


def test_step_audit_renders_single_order_detail_as_table() -> None:
    text = _audit_text({
        "fields": {"price_timestamp": "2026-01-05 09:02:00+08:00"},
        "instrument": "CZCE|F|SM|2603",
        "intent_quantity": 421.0,
        "order_id": "order-1",
        "quantity": 421.0,
        "reject_reason": None,
        "status": "scheduled",
        "strategy": "A1",
        "timestamp": "2026-01-05 09:01:00+08:00",
    })

    assert "timestamp" in text
    assert "CZCE|F|SM|2603" in text
    assert "scheduled" in text
    assert "price_timestamp" in text
    assert '"instrument"' not in text


def test_step_audit_renders_trading_day_resolver_summary() -> None:
    text = _audit_text({
        "type": "TimestampTradingDayResolver",
        "purpose": "timestamp -> trading_day for trading-day-scoped historical field rows",
        "effective_rule": (
            "rows with effective_timestamp are compared against the actual timestamp; "
            "only rows without effective_timestamp use the mapped trading_day"
        ),
        "mapping_count": 3,
        "timestamp_index": {"start": "2026-01-05 09:01:00", "end": "2026-01-06 09:01:00"},
        "trading_days": {"count": 2, "start": "2026-01-05", "end": "2026-01-06"},
        "sample": {
            "head": {
                "columns": ["trading_day"],
                "index": ["2026-01-05 09:01:00"],
                "rows": [["2026-01-05"]],
            }
        },
    })

    assert "TimestampTradingDayResolver: timestamp -> trading_day（仅用于交易日级历史字段记录）" in text
    assert "effective_timestamp" in text
    assert "mapped trading_day" in text
    assert "mapping_count = 3" in text
    assert "trading_days = 2 days; 2026-01-05 → 2026-01-06" in text
    assert "sample.head:" in text
    assert "trading_day" in text
    assert "repr" not in text


def test_step_audit_renders_runtime_object_without_memory_address() -> None:
    text = _audit_text({
        "type": "FieldHistoryProvider",
        "repr": "<tools.data.field_history.FieldHistoryProvider object at 0x1234>",
    })

    assert text == "FieldHistoryProvider（runtime object）"
    assert "0x1234" not in text
    assert '"repr"' not in text


def test_step_audit_renders_target_weight_intent_as_table() -> None:
    text = _audit_text({
        "type": "TargetWeightIntent",
        "reason": "group_quantile",
        "weights": {"RB.SHF": 0.5, "AG.SHF": 0.5},
    })

    assert "reason = group_quantile" in text
    assert "product" in text
    assert "target_weight" in text
    assert "RB.SHF" in text
    assert "0.5" in text


def test_step_audit_unowned_strategy_context_change_is_shared(capsys) -> None:
    _print_audit_changes("声明输出的变化", [{
        "field": "ProductSelectionModule.products",
        "scope": "strategy_context",
        "before": None,
        "after": ["AP.CZC", "CJ.CZC"],
    }])

    out = capsys.readouterr().out
    assert "[共享]" in out
    assert "策略上下文 无" not in out


def test_step_audit_identical_strategy_context_values_are_merged_in_strategy_table(capsys) -> None:
    _print_audit_fields("输入字段", [{
        "field": "ProductSelectionModule.products",
        "values": [
            {"scope": "strategy_context", "strategy": "A1", "value": ["AP.CZC", "CJ.CZC"]},
            {"scope": "strategy_context", "strategy": "A2", "value": ["AP.CZC", "CJ.CZC"]},
        ],
    }])

    out = capsys.readouterr().out
    assert "[共享]" not in out
    assert "strategies" in out
    assert "products" in out
    assert "A1, A2" in out


def test_step_audit_compacts_long_strategy_input_lists_in_strategy_table(capsys) -> None:
    products = [f"P{index}.EX" for index in range(12)]

    _print_audit_fields("输入字段", [{
        "field": "ProductSelectionModule.products",
        "values": [
            {"scope": "strategy_context", "strategy": "A1", "value": products},
            {"scope": "strategy_context", "strategy": "A2", "value": products},
        ],
    }])

    out = capsys.readouterr().out
    assert "source" not in out
    assert "strategies" in out
    assert "products" in out
    assert "A1, A2" in out
    assert "P0.EX, P1.EX" in out
    assert "共 12 个" not in out
    assert "P11.EX]" in out


def test_step_audit_annotates_signal_frequency_and_inactive_warmup_window(capsys) -> None:
    fields = [
        ("FactorSignalModule.warmup_mode", "auto"),
        ("FactorSignalModule.warmup_window", "30d"),
        ("FactorSignalModule.signal_freq", "1d"),
        ("MarketDataModule.required_frequency", "MIN1"),
    ]
    _print_audit_fields("输入字段", [
        {
            "field": field,
            "values": [
                {"scope": "strategy_context", "strategy": "A1", "value": value},
                {"scope": "strategy_context", "strategy": "A2", "value": value},
            ],
        }
        for field, value in fields
    ])

    out = capsys.readouterr().out
    assert "30d（fixed模式配置；当前auto未生效）" in out
    assert "1d（信号事件频率；因子/行情数据频率见required_frequency=MIN1）" in out


def test_step_audit_current_historical_fields_samples_and_transposes(capsys) -> None:
    after = {
        f"P{index}.EX": {
            "VolumeMultiple": index,
            "LongMarginRatioByMoney": index / 100,
            "CostBasisMethod": "DailyMarkToMarket",
        }
        for index in range(10)
    }
    _print_audit_changes("声明输出的变化", [{
        "field": "MarketDataModule.current_historical_fields",
        "scope": "context",
        "before": None,
        "after": after,
    }])

    out = capsys.readouterr().out
    assert "current_historical_fields [MarketDataModule.current_historical_fields]" in out
    assert "sample products: 6/10" in out
    assert "field" in out
    assert "VolumeMultiple" in out
    assert "LongMarginRatioByMoney" in out
    assert "CostBasisMethod" in out
    assert "P0.EX" in out
    assert "P9.EX" in out
    assert "P4.EX" not in out


def test_step_audit_formats_python_literal_strings_as_json() -> None:
    text = _audit_text("{'id': 'pg_bc7963105fe8', 'selected_paths': ['Product/Futures/CNFutures/日夜盘/日盘']}")

    assert text.startswith("{\n")
    assert '"product_path_selection_id": "pg_bc7963105fe8"' in text
    assert '"paths": [' in text
    assert '"selected_paths"' not in text
    assert '"id"' not in text
    assert "'id'" not in text


def test_step_audit_formats_dataframe_payloads_as_tables() -> None:
    text = _audit_text({
        "type": "DataFrame",
        "shape": [25, 2],
        "columns": ["RB.SHF", "AG.SHF"],
        "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"},
        "sample": {
            "head": {
                "columns": ["RB.SHF", "AG.SHF"],
                "index": ["2026-01-01 09:00:00", "2026-01-01 09:01:00"],
                "rows": [[1.0, 3.0], [2.0, 4.0]],
            }
        },
        "truncated": True,
    })

    assert text.startswith("pd.DataFrame shape=(25, 2)")
    assert "index.start = 2026-01-01 09:00:00" in text
    assert "index.end   = 2026-01-01 09:24:00" in text
    assert "truncated   = True" in text
    assert 'columns     = ["RB.SHF", "AG.SHF"]' in text
    assert "sample.rows = 仅显示 1/2 行；其余 sample 行已省略" in text
    assert "sample.head:" in text
    assert "RB.SHF" in text
    assert "2026-01-01 09:01:00" not in text
    assert '"rows"' not in text


def test_step_audit_formats_only_one_dataframe_sample_when_head_and_tail_exist() -> None:
    text = _audit_text({
        "type": "DataFrame",
        "shape": [100, 2],
        "columns": ["RB.SHF", "AG.SHF"],
        "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 14:59:00"},
        "sample": {
            "head": {
                "columns": ["RB.SHF", "AG.SHF"],
                "index": ["2026-01-01 09:00:00"],
                "rows": [[1.0, 3.0]],
            },
            "tail": {
                "columns": ["RB.SHF", "AG.SHF"],
                "index": ["2026-01-01 15:00:00"],
                "rows": [[2.0, 4.0]],
            },
        },
        "truncated": True,
    })

    assert "sample = 仅显示 head；tail 已省略" in text
    assert "sample.head:" in text
    assert "sample.tail:" not in text
    assert "2026-01-01 09:00:00" in text
    assert "2026-01-01 15:00:00" not in text


def test_step_audit_formats_wide_dataframe_columns_as_counts() -> None:
    text = _audit_text({
        "type": "DataFrame",
        "shape": [25, 5000],
        "columns": {"count": 5000, "sampled": ["C0", "C1", "C4998", "C4999"], "sample_truncated": True},
        "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"},
        "sample": {
            "head": {
                "columns": ["C0", "C1", "C4998", "C4999"],
                "index": ["2026-01-01 09:00:00"],
                "rows": [[1.0, 2.0, 3.0, 4.0]],
            }
        },
        "truncated": True,
    })

    assert "columns     = 5000 columns; sample shows 4 columns" in text
    assert "C4999" in text
    assert "sampled" not in text


def test_step_audit_transposes_wide_two_key_tables(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((90, 20)))

    lines = _audit_table_lines(
        (
            "notice_time",
            "strategy",
            "product",
            "contract",
            "notice_type",
            "reason",
            "last_trade_date",
            "delivery_date",
            "lifecycle_source",
            "lifecycle_source_function",
        ),
        [
            (
                "2026-01-28 15:00:00+08:00",
                "A5",
                "PT.GFE",
                "GFEX|F|PT|2606",
                "force_close",
                "auto_close_date",
                "2026-06-12",
                "2026-06-17",
                "GFEX product rule + trading calendar derived contract lifecycle",
                "exchange_rule_dayk_calendar_derived",
            ),
            (
                "2026-01-28 15:00:00+08:00",
                "A4",
                "FB.DCE",
                "DCE|F|FB|2603",
                "force_close",
                "auto_close_date",
                "2026-03-02",
                "2026-03-05",
                "DCE product rule + trading calendar derived contract lifecycle",
                "exchange_rule_dayk_calendar_derived",
            ),
        ],
    )

    text = "\n".join(lines)
    assert "表格已转置" in text
    assert "2026-01-28 15:00:00+08:00 | A5" in text
    assert "lifecycle_source_function" in text
    assert "columns 1/" in text
    assert max(len(_strip_ansi(line)) for line in lines) <= 140


def test_step_audit_keeps_positions_as_product_index_table() -> None:
    text = _audit_text({
        "type": "PositionsTable",
        "positions": {
            "P1.EX": {
                "quantity": 0,
                "average_cost": 0.0,
                "settlement_price": None,
                "margin_reserved": None,
                "lots_count": 0,
            },
            "P2.EX": {
                "quantity": 0,
                "average_cost": 0.0,
                "settlement_price": None,
                "margin_reserved": None,
                "lots_count": 0,
            },
        },
    })

    assert "表格已转置" not in text
    assert "products" in text
    assert "quantity" in text
    assert "average_cost" in text
    assert "settlement_price" in text
    assert "全部相同" not in text
    assert "全部产品" in text


def test_step_audit_transposed_tables_split_long_row_labels(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((90, 20)))

    long_strategy = "bg_mpv90jxe_1:35b39e39e72e4b0e96f43a313b29ea9e"
    lines = _audit_table_lines(
        ("timestamp", "strategy", "instrument", "qty", "status", "order_id", "effective_price", "fee_cost", "reason"),
        [
            ("2026-01-05 09:01:00.000001+08:00", long_strategy, "A", "1", "scheduled", "O1", "10", "1", ""),
            ("2026-01-05 09:01:00.000001+08:00", long_strategy, "B", "2", "scheduled", "O2", "20", "2", ""),
            ("2026-01-05 09:01:00.000001+08:00", long_strategy, "C", "3", "scheduled", "O3", "30", "3", ""),
        ],
    )

    text = "\n".join(lines)
    assert "表格已转置" in text
    assert "行标明细" in text
    assert "行1" in text
    assert "bg_mpv90jxe_1:35b39e39e72e4b0e96" in text
    assert "f43a313b29ea9e" in text
    assert max(len(_strip_ansi(line)) for line in lines) <= 100
    assert f"column         2026-01-05 09:01:00.000001+08:00 | {long_strategy}" not in text


def test_step_audit_formats_contract_metadata_as_compact_table() -> None:
    text = _audit_text({
        "type": "ContractMetadataTable",
        "columns": ["product", "contract", "start", "end"],
        "rows": [
            {"product": "AP.CZC", "contract": "AP605.CZC", "start": "2025-12-03", "end": "2026-04-10"},
            {"product": "EC.INE", "contract": "INE|F|EC|2602", "start": "2025-11-13", "end": "2026-01-09"},
        ],
    })

    assert "原产品" in text
    assert "新合约" in text
    assert "起始时间" in text
    assert "终止时间" in text
    assert "AP.CZC" in text
    assert "AP605.CZC" in text
    assert "INE|F|EC|2602" in text
    assert '"rows"' not in text
    assert "contract_product" not in text


def test_step_audit_formats_price_tables_as_basis_summary(monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((72, 20)))
    text = _audit_text({
        "type": "PriceTablesSummary",
        "columns": ["basis", "shape", "index", "columns"],
        "rows": [
            {
                "basis": "close",
                "shape": [25, 2],
                "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"},
                "columns": ["RB.SHF", "AG.SHF"],
                "sample": {
                    "head": {
                        "columns": ["RB.SHF", "AG.SHF"],
                        "index": ["2026-01-01 09:00:00"],
                        "rows": [[1.0, 2.0]],
                    },
                    "tail": {
                        "columns": ["RB.SHF", "AG.SHF"],
                        "index": ["2026-01-01 09:24:00"],
                        "rows": [[3.0, 4.0]],
                    },
                },
            },
            {
                "basis": "open",
                "shape": [25, 5000],
                "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"},
                "columns": {"count": 5000, "sampled": ["C0", "C1", "C4998", "C4999"], "sample_truncated": True},
            },
            {
                "basis": "settlement",
                "shape": [25, 2],
                "index": {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"},
                "columns": ["RB.SHF", "AG.SHF"],
                "sample": {
                    "head": {
                        "columns": ["RB.SHF", "AG.SHF"],
                        "index": ["2026-01-01 09:00:00"],
                        "rows": [[1.5, 2.5]],
                    },
                    "tail": {
                        "columns": ["RB.SHF", "AG.SHF"],
                        "index": ["2026-01-01 09:24:00"],
                        "rows": [[3.5, 4.5]],
                    },
                },
            },
        ],
    })

    assert "价格字段 sample（行索引=field/product，列=首尾 sample 时间）:" in text
    assert "价格字段元信息:" not in text
    assert ".sample =" not in text
    assert "columns 1/" not in text
    assert "close" in text
    assert re.search(r"field\s+product\s+2026-01-01 09:00:00", text)
    assert "2026-01-01 09:24:00" in text
    assert re.search(r"close\s+AG\.SHF\s+2(?:\\.0)?\s+4(?:\\.0)?", text)
    assert "4" in text
    assert re.search(r"close\s+RB\.SHF\s+1(?:\\.0)?\s+3(?:\\.0)?", text)
    assert "3" in text
    assert "sample.head:" not in text
    assert "25 x 2" not in text
    assert "5000 columns; sample shows 4 columns" not in text
    assert "日级结算字段" not in text
    assert '"rows"' not in text


def test_step_audit_formats_market_data_load_plan_as_table() -> None:
    text = _audit_text({
        "type": "MarketDataLoadPlan",
        "count": 2,
        "items": {
            "AP.CZC": {"frequency": "MIN1", "data_source": "Local"},
            "CJ.CZC": {"frequency": "MIN1", "data_source": "auto"},
        },
    })

    assert "planned products = 2" in text
    assert "product" in text
    assert "frequency" in text
    assert "data_source" in text
    assert "AP.CZC" in text
    assert "Local" in text
    assert '"rows"' not in text


def test_step_audit_formats_market_data_excluded_products_compactly() -> None:
    text = _audit_text({
        "type": "MarketDataExcludedProducts",
        "count": 2,
        "rows": [{"product": "ER.CZC"}, {"product": "RO.CZC"}],
    })

    assert "excluded products = 2" in text
    assert "ER.CZC" in text
    assert "RO.CZC" in text
    assert '"rows"' not in text


def test_step_audit_combines_market_data_samples_into_one_table(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((132, 20)))
    frame_sample = {
        "type": "DataFrame",
        "sample": {
            "head": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC", "SM.CZC"],
                "index": [["2026-01-05", "09:01"]],
                "rows": [[1, 2, 3, 4]],
            },
            "tail": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC", "SM.CZC"],
                "index": [["2026-01-30", "15:00"]],
                "rows": [[11, 12, 13, 14]],
            },
        },
    }
    price_tables = {
        "type": "PriceTablesSummary",
        "rows": [
            {"basis": "close", "sample": frame_sample["sample"]},
            {"basis": "open", "sample": frame_sample["sample"]},
        ],
    }
    _print_audit_fields("输入字段", [
        {"field": "MarketDataModule.price_tables", "values": [{"scope": "context", "value": price_tables}]},
        {"field": "MarketDataModule.raw_prices", "values": [{"scope": "context", "value": frame_sample}]},
        {"field": "MarketDataModule.settlement_price", "values": [{"scope": "context", "value": {"AP.CZC": 1, "CJ.CZC": 2, "PK.CZC": 3, "SM.CZC": 4}}]},
        {"field": "MarketDataModule.volume", "values": [{"scope": "context", "value": {"AP.CZC": 100, "CJ.CZC": 200, "PK.CZC": 300, "SM.CZC": 400}}]},
    ])

    plain = _strip_ansi(capsys.readouterr().out)
    assert "市场数据 sample 总表（每个价格字段最多 3 个产品）" in plain
    assert plain.count("field") == 1
    assert "price_tables.close" in plain
    assert "price_tables.open" in plain
    assert "raw_prices" in plain
    assert "settlement_price" in plain
    assert "volume" in plain
    assert "AP.CZC" in plain
    assert "CJ.CZC" in plain
    assert "PK.CZC" in plain
    assert "SM.CZC" not in plain
    assert "价格字段元信息:" not in plain


def test_step_audit_does_not_split_market_sample_table(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((72, 20)))
    frame_sample = {
        "type": "DataFrame",
        "sample": {
            "head": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC"],
                "index": [["2026-01-05 00:00:00", "2026-01-05 09:01:00+08:00"]],
                "rows": [[1, 2, 3]],
            },
            "tail": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC"],
                "index": [["2026-01-30 00:00:00", "2026-01-30 15:00:00+08:00"]],
                "rows": [[11, 12, 13]],
            },
        },
    }

    _print_audit_fields("输入字段", [
        {"field": "MarketDataModule.raw_prices", "values": [{"scope": "context", "value": frame_sample}]},
    ])

    plain = _strip_ansi(capsys.readouterr().out)
    headers = [
        line.strip()
        for line in plain.splitlines()
        if line.strip().startswith("field")
    ]
    assert "columns 1/" not in plain
    assert len(headers) == 1
    assert headers[0].startswith("field       product")


def test_step_audit_market_sample_field_without_sample_does_not_fallback_to_strategy_table(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((132, 20)))

    _print_audit_fields("输入字段", [
        {
            "field": "OrderExecutionModule.execution_price_basis",
            "values": [{"scope": "strategy_config", "strategy": "A1", "value": "open"}],
        },
        {
            "field": "MarketDataModule.price_tables",
            "values": [{"scope": "strategy_context", "strategy": "A1", "value": None}],
        },
    ])

    plain = _strip_ansi(capsys.readouterr().out)
    assert "price_tables [MarketDataModule.price_tables]" in plain
    assert "市场数据 sample 总表（每个价格字段最多 3 个产品）" in plain
    assert "（无可采样值）" in plain
    assert "execution_price_basis  price_tables" not in plain
    assert "[共享]:" not in plain


def test_step_audit_combines_market_data_sample_changes(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((132, 20)))
    after = {
        "type": "DataFrame",
        "sample": {
            "head": {"columns": ["AP.CZC", "CJ.CZC", "PK.CZC"], "index": ["2026-01-05 09:01"], "rows": [[1, 2, 3]]},
            "tail": {"columns": ["AP.CZC", "CJ.CZC", "PK.CZC"], "index": ["2026-01-30 15:00"], "rows": [[11, 12, 13]]},
        },
    }

    _print_audit_changes("声明输出的变化", [
        {"field": "MarketDataModule.raw_prices", "before": None, "after": after},
        {"field": "MarketDataModule.volume", "before": None, "after": {"AP.CZC": 100, "CJ.CZC": 200, "PK.CZC": 300, "SM.CZC": 400}},
    ])

    out = capsys.readouterr().out
    plain = _strip_ansi(out)
    assert "市场数据 sample 总表（每个价格字段最多 3 个产品）" in plain
    assert "raw_prices" in plain
    assert "volume" in plain
    assert "null -> 1" in plain
    assert "null -> 100" in plain
    assert "SM.CZC" not in plain


def test_step_audit_renders_causal_valuation_table_as_market_sample(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((132, 20)))
    after = {
        "type": "DataFrame",
        "sample": {
            "head": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC", "SM.CZC"],
                "index": [["2026-01-05 00:00:00", "2026-01-05 09:01:00+08:00"]],
                "rows": [[1, 2, 3, 4]],
            },
            "tail": {
                "columns": ["AP.CZC", "CJ.CZC", "PK.CZC", "SM.CZC"],
                "index": [["2026-01-30 00:00:00", "2026-01-30 15:00:00+08:00"]],
                "rows": [[11, 12, 13, 14]],
            },
        },
    }

    _print_audit_changes("声明输出的变化", [
        {"field": "MarketDataModule.causal_valuation_table", "before": None, "after": after},
    ])

    plain = _strip_ansi(capsys.readouterr().out)
    assert "市场数据 sample 总表（每个价格字段最多 3 个产品）" in plain
    assert "causal_valuation_table" in plain
    assert "pd.DataFrame shape" not in plain
    assert "AP.CZC" in plain
    assert "CJ.CZC" in plain
    assert "PK.CZC" in plain
    assert "SM.CZC" not in plain
    assert "columns 1/" not in plain


def test_step_audit_formats_series_payloads_as_tables() -> None:
    text = _audit_text({
        "type": "Series",
        "name": "close",
        "length": 25,
        "index": {"start": "2026-01-01", "end": "2026-01-25"},
        "sample": {"head": {"index": ["2026-01-01", "2026-01-02"], "values": [1.0, 2.0]}},
        "truncated": True,
    })

    assert text.startswith("pd.Series name='close' length=25 index=2026-01-01")
    assert "truncated=True" in text
    assert "sample.rows = 仅显示 1/2 行；其余 sample 行已省略" in text
    assert "sample.head:" in text
    assert "value" in text
    assert "2026-01-02" not in text
    assert '"values"' not in text


def test_step_audit_empty_message_is_explicit(capsys) -> None:
    _print_audit_fields(
        "声明输出字段（未变化）",
        [],
        empty_message="（所有声明输出字段均发生变化，见下方“声明输出的变化”）",
    )

    out = capsys.readouterr().out
    assert "所有声明输出字段均发生变化" in out
    assert "无声明字段" not in out


def test_step_section_headers_are_prominent(capsys) -> None:
    _print_audit_changes("声明输出的变化", [])
    _print_event_payload_changes([])
    _print_contract_audit([])

    out = capsys.readouterr().out
    assert "━━ 声明输出的变化 ━━" in out
    assert "━━ 本批事件草稿载荷变化（非完整事件队列） ━━" in out
    assert "━━ 字段声明审计 ━━" in out
    assert "事件载荷变化" not in out


def test_step_wrapped_long_scalar_values_align_to_value_column(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((50, 20)))

    _print_audit_value("    ", "策略配置 A1", "Product/Futures/CNFutures/日夜盘/夜盘1/_products/RB.SHF")

    out = capsys.readouterr().out.splitlines()
    assert len(out) > 1
    assert out[1].startswith(" " * len("    策略配置 A1 = "))


def test_step_multiline_dataframe_metadata_wraps_with_value_indent(capsys, monkeypatch) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda fallback: shutil.os.terminal_size((50, 20)))
    value = {
        "type": "DataFrame",
        "shape": [25, 2],
        "columns": ["RB.SHF", "SHFE|F|RB|2610"],
        "index": {
            "start": ["2026-05-26 00:00:00", "2026-05-26 09:01:00+08:00"],
            "end": ["2026-05-27 00:00:00", "2026-05-27 15:00:00+08:00"],
        },
        "sample": {
            "head": {
                "columns": ["RB.SHF", "SHFE|F|RB|2610"],
                "index": [["2026-05-26 00:00:00", "2026-05-26 09:01:00+08:00"]],
                "rows": [[3187.0, 3187.0]],
            }
        },
        "truncated": True,
    }

    _print_audit_value("    ", "after", value)

    out = capsys.readouterr().out.splitlines()
    assert out[0] == "    after ="
    assert any(line.startswith("      index.start = ") for line in out)
    assert any(line.startswith("                    '2026-05-26 09:01:00+08:00']") for line in out)
    assert any("sample.head:" in line for line in out)


def test_step_active_context_renders_compact_one_line_rows(capsys) -> None:
    _print_strategy_context([
        {"strategy": "runtime-bg-1", "shortAlias": "A1", "ledgers": ["private:A1"]},
        {"strategy": "runtime-bg-2", "short_alias": "A2", "ledgers": ["private:A2"]},
    ])

    out = capsys.readouterr().out
    assert "本次 flow 的 active strategies" in out
    assert "A1, A2" in out
    assert "runtime-bg" not in out
    assert "private:A1" not in out
    assert "cash pool" not in out


def test_step_event_payloads_skip_empty_null_payloads(capsys) -> None:
    _print_event_payloads([
        {"scope": "strategy", "strategy": "A1", "payloads": [None]},
    ])

    out = capsys.readouterr().out
    assert "本批事件草稿载荷" not in out


def test_step_navigation_supports_until_and_end_without_skipping_computation() -> None:
    navigator = step_display_formatter.StepNavigator()

    assert step_display_formatter.set_step_navigation(navigator, "until 2026-01-15 10:30:00") is None
    assert not navigator.should_display("")
    assert not navigator.should_display("2026-01-15 10:29:59")
    assert navigator.should_display("2026-01-15 10:30:00")
    assert navigator.until is None

    assert step_display_formatter.set_step_navigation(navigator, "end") is None
    assert navigator.to_end
    assert not navigator.should_display("2026-01-31 15:00:00")


def test_step_navigation_rejects_unknown_or_invalid_commands() -> None:
    navigator = step_display_formatter.StepNavigator()

    assert step_display_formatter.set_step_navigation(navigator, "until nope")
    assert step_display_formatter.set_step_navigation(navigator, "next")
    assert step_display_formatter.set_step_navigation(navigator, "") is None


def test_step_contract_audit_reports_pass_and_read_write_violations(capsys) -> None:
    _print_contract_audit([])
    out = capsys.readouterr().out
    assert "字段声明审计" in out
    assert "已通过" in out

    _print_contract_audit([
        {"access": "read", "field": "A.input"},
        {"access": "write", "field": "B.output"},
    ])
    out = capsys.readouterr().out
    assert "读取未声明输入: A.input" in out
    assert "写入未声明输出: B.output" in out


def test_step_flow_header_is_red(capsys, monkeypatch) -> None:
    posted: list[tuple[str, dict[str, object]]] = []

    class _Session:
        def post(self, path: str, payload: dict[str, object]) -> None:
            posted.append((path, payload))

    client = SimpleNamespace(session=_Session())
    monkeypatch.setattr("builtins.input", lambda _: "")

    _handle_step_event(
        {
            "phase": "step",
            "flow_phase": "pre_replay",
            "flow_id": "resolve_run_window",
            "flow_name": "解析运行时间窗口",
            "timestamp": "2026-01-05 09:02:00+08:00",
            "current_event": {
                "event_kind": "ORDER",
                "batch_count": 1,
                "subjects": [{
                    "strategy": "A1",
                    "subject": "CZCE|F|SM|2603",
                    "action": "scheduled",
                    "order_id": "A1-1",
                }],
            },
            "description": "",
            "strategies": [],
            "ledgers_before": [],
            "inputs": [],
            "outputs": [],
            "output_changes": [],
            "event_payload_changes": [],
            "ledger_changes": [],
        },
        client,
        "run-token",
        step_display_formatter.StepNavigator(),
    )

    out = capsys.readouterr().out
    assert "\x1b[30m\x1b[48;2;255;238;246m┏" in out
    assert "\x1b[101m" not in out
    assert "\x1b[105m" not in out
    assert "\x1b[41m" not in out
    assert "flow           = PRE_REPLAY" in out
    assert "timestamp      = 2026-01-05 09:02:00+08:00" in out
    assert "event_kind     = ORDER" in out
    assert "batch_count    = 1" in out
    assert "event_subjects = A1:CZCE|F|SM|2603/scheduled" in out
    assert "\x1b[0m" in out
    assert posted == [("/step_continue", {"run_token": "run-token", "action": "continue"})]


def test_run_payload_uses_backend_group_contract_names() -> None:
    assert run_payload_helpers.serialize_group_for_run({
        "name": "A1",
        "split_count": 5,
        "group_index": 1,
        "factor": "SgCCS|N:2m",
    }) == {
        "name": "A1",
        "split_count": 5,
        "group_index": 1,
        "factor": "SgCCS|N:2m",
        "splitCount": 5,
        "groupIndex": 1,
        "factorAlias": "SgCCS|N:2m",
    }


def test_strategy_book_short_aliases_are_mapped_to_runtime_strategy_ids() -> None:
    state = SimpleNamespace(backtest_strategy_book={
        "strategies": {
            "A1": {"ledger_ids": ["shared"], "default_ledger_id": "shared"},
            "A2": {"ledger_ids": ["shared"], "default_ledger_id": "shared"},
        },
        "cash_pools": {"shared": "pool-main"},
    })
    groups = [
        {"id": "bg_runtime_1", "name": "完整模板分组名1", "shortAlias": "A1"},
        {"id": "bg_runtime_2", "name": "完整模板分组名2", "shortAlias": "A2"},
    ]

    payload = run_payload_helpers.serialize_strategy_book_for_run(
        config_state_helpers.strategy_book_payload(state),
        groups,
    )

    assert set(payload["strategies"]) == {"bg_runtime_1", "bg_runtime_2"}
    assert payload["strategies"]["bg_runtime_1"]["ledger_ids"] == ["shared"]


@contextmanager
def running_server(app: Flask) -> Iterator[str]:
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def register_home_modules(app: Flask) -> None:
    @app.get("/static/config/modules.json")
    def home_modules():
        return jsonify(success=True, modules=[
            {"id": "single_factor_test", "title": "单因子测试", "path": "/single_factor_test"},
            {"id": "backtest", "title": "回测", "path": "/single_factor_test?module=backtest"},
            {"id": "products", "title": "产品管理", "path": "/products"},
            {"id": "custom_factors", "title": "因子管理", "path": "/custom-factors/editor"},
        ])


def test_products_info_prints_backend_field_notes(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/product_fields")
    def product_fields():
        assert request.args.get("name") == "AP.CZC"
        return jsonify(
            success=True,
            name="AP.CZC",
            fields={
                "name": {"value": "AP.CZC", "type": "str"},
                "MoneyCalculationPolicy": {
                    "value": "aggregate",
                    "type": "str",
                    "label": "金额计算口径",
                    "source": "中国期货交易所默认清算规则",
                    "source_note": "历史字段优先。",
                    "note": "总额公式后落账。",
                },
            },
        )

    with running_server(app) as base_url:
        monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
        save_config(ClientConfig(base_url=base_url))
        result = CliRunner().invoke(cli, ["products", "info", "AP.CZC"])

    assert result.exit_code == 0
    assert "产品后端信息: AP.CZC" in result.output
    assert "金额计算口径" in result.output
    assert "aggregate" in result.output
    assert "历史字段优先" in result.output


def test_click_describe_and_edit_flow_uses_remote_manifests(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(
            success=True,
            application=application,
            tab_lists={"local-settings": [{"key": "risk", "label": "风险"}]},
            defaults={
                "allocation_mode": {
                    "value": "equal_risk",
                    "label": "分配方式",
                    "control_template": "select",
                    "tab_key": "risk",
                    "order": 1,
                    "options": [
                        {"value": "equal_risk", "label": "等风险"},
                        {"value": "equal_notional", "label": "等市值"},
                    ],
                }
            },
        )

    @app.get("/api/backtest/settings/<application>/tabs/<tab_key>")
    def tab(application: str, tab_key: str):
        return jsonify(
            success=True,
            application=application,
            tab={"key": tab_key, "label": "风险"},
            settings=[
                {
                    "key": "allocation_mode",
                    "label": "分配方式",
                    "control_template": "select",
                    "default": "equal_risk",
                    "tab": tab_key,
                    "options": [
                        {"value": "equal_risk", "label": "等风险"},
                        {"value": "equal_notional", "label": "等市值"},
                    ],
                }
            ],
        )

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test/risk", "label": "风险", "kind": "tab", "has_children": True}])
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/risk", "label": "风险", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["describe", "group_test"])
        assert result.exit_code == 0
        assert "分配方式" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_test" in result.output
        assert "[module] products" in result.output
        assert "[module] custom_factors" in result.output
        assert "group_test/risk" not in result.output

        result = runner.invoke(cli, ["list", "single_factor_family_test"])
        assert result.exit_code != 0
        assert "unexpected extra argument" in result.output.lower()

        result = runner.invoke(cli, ["single_factor_family_test", "--factor-family", "SgCCS"])
        assert result.exit_code == 0
        assert "单因子家族测试" in result.output
        assert "已选择 factor_family: SgCCS" in result.output

        result = runner.invoke(cli, ["single_factor_test", "list"])
        assert result.exit_code == 0
        assert "当前位置: single_factor_test" in result.output
        assert "[module] backtest" in result.output

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0
        assert "回测" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_test" in result.output

        result = runner.invoke(cli, ["back"])
        assert result.exit_code != 0
        assert "No such command" in result.output

        result = runner.invoke(cli, ["edit", "group_test"], input="1\n1\n2\nq\n")
        assert result.exit_code == 0
        assert "已设置 分配方式: equal_notional" in result.output
        assert "当前显式设置" in result.output


def test_click_login_failure_is_user_friendly(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.post("/login")
    def login():
        return jsonify(success=False, error="用户名或密码错误"), 401

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "bad"])
        assert result.exit_code != 0
        assert "Error: 请求失败 (401): 用户名或密码错误" in result.output
        assert "Traceback" not in result.output
        assert "tools/cli" not in result.output


def test_click_login_success_prints_welcome(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_home_modules(app)

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-1")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"])
        assert result.exit_code == 0
        assert "已登录: alice" in result.output
        assert "页面上下文: page-1" in result.output
        assert "欢迎使用 FactorTester CLI" in result.output
        assert "factortester list" in result.output
        assert "longbridge-quant、quantitative-research skill" in result.output
        assert "tools/cli/docs/factor-research-cli.md" in result.output


def test_agent_facing_doctor_and_factor_plan(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(
            success=True,
            application=application,
            defaults={
                "start_date": {"value": "2026-01-01", "label": "开始日期"},
                "end_date": {"value": "2026-01-31", "label": "结束日期"},
            },
        )

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0

        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["success"] is True
        assert any(item["name"] == "server" for item in payload["checks"])
        assert any(item["name"] == "manifest:ic_test" for item in payload["checks"])

        result = runner.invoke(cli, [
            "factor-plan",
            "--factor-family",
            "SgCCS",
            "--template",
            "2026-06-02 07:20:47",
            "--product-group",
            "中国期货日盘",
            "--n",
            "2m",
            "--f",
            "1m",
            "--liquidity-mode",
            "infinite",
            "--json",
        ])
        assert result.exit_code == 0
        plan = json.loads(result.output)
        commands = [item["command"] for item in plan["steps"]]
        assert commands[0] == "factortester single_factor_test --factor-family SgCCS"
        assert "factortester custom_factors operators" in commands
        assert any("single_factor_test --factor-family SgCCS template load" in command for command in commands)
        assert any("template --from-module-template single_factor_test load" in command for command in commands)
        ic_index = next(index for index, command in enumerate(commands) if "factortester ic_test grid --factor-family SgCCS" in command)
        type_index = next(index for index, command in enumerate(commands) if "factortester factor_type_analysis grid --factor-family SgCCS" in command)
        backtest_index = next(index for index, command in enumerate(commands) if "factortester backtest compare factor-grid --factor-family SgCCS" in command)
        assert ic_index < backtest_index
        assert type_index < backtest_index
        assert "--volume-capacity-mode infinite" in commands[backtest_index]


def test_single_factor_family_can_jump_directly_to_child_module(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test/time", "label": "时间范围", "kind": "tab", "has_children": True}])
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/time", "label": "时间范围", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["single_factor_family_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0
        assert "回测" in result.output
        assert "--factor-family SgCCS" in result.output

        result = runner.invoke(cli, ["single_factor_test", "list"])
        assert result.exit_code == 0
        assert "当前位置: single_factor_test" in result.output
        assert "[module] backtest" in result.output


def test_backtest_can_enter_from_home_with_factor_family_and_draft_options(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "control_template": "select",
                "tab_key": "risk",
            },
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        if application == "single_factor_page":
            return jsonify(success=True, application=application, defaults=defaults)
        if application == "group_test":
            return jsonify(success=True, application=application, tab_lists={"local-settings": []}, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘", "paths": ["Product/Futures/CNFutures/日盘"]}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{
            "factor_alias": "SgCCS|N:2m|$F:1m|$Rev",
            "factor_family_alias": request.args.get("factor_family_alias"),
            "product_group": request.args.get("product_group"),
        }])

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "backtest":
            return jsonify(success=True, parent=parent, modules=[{"key": "backtest/time", "label": "时间范围", "kind": "tab", "application": "group_test", "has_children": True}])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "local-settings",
            "allocation_mode=equal_notional",
            "--start-date", "2026-01-01",
            "--end-date", "2026-01-31",
        ])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "名称: A1" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 1" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "A1 · 分组数=5 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "因子=SgCCS|N:2m|$F:1m|$Rev" in result.output

        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "当前位置: 首页" in result.output
        assert "[module] single_factor_test" in result.output


def test_single_factor_test_backtest_add_group_reuses_factor_family_context(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        assert request.args.get("factor_family_alias") == "SgCCS"
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[{"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True}])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ])
        assert result.exit_code == 0
        assert "产品路径: 中国期货日盘" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_supports_inline_factor_and_product_paths(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[])

    @app.get("/api/factor-library-configs/<factor_family>")
    def factor_library_configs(factor_family: str):
        assert factor_family == "SgCCS"
        assert request.args.get("product_group") == "现场路径"
        return jsonify(success=True, users=[{"editable": True, "config": {"params_list": []}}])

    @app.put("/api/factor-library-configs/<factor_family>")
    def save_factor_library_configs(factor_family: str):
        payload = request.get_json()
        assert payload["params_list"] == [{"N": "2m", "$Rev": "1"}]
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m|$Rev:1"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--product-group", "add",
            "--name", "现场路径",
            "--path", "Product/Futures/CNFutures/日盘",
            "--path", "-Product/Futures/CNFutures/日盘/_products/BB.DCE",
            "--factor", "add",
            "--param", "N=2m",
            "--param", "$Rev=1",
        ])

        assert result.exit_code == 0
        assert "名称: A1" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 1" in result.output
        assert "产品路径: 现场路径" in result.output
        assert "因子: SgCCS|N:2m|$Rev:1" in result.output


def test_backtest_add_group_can_import_local_factor_family_path(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    source_path = tmp_path / "LocalAlpha.py"
    source_path.write_text(
        "from tools.factors import FactorFamily\n\nclass LocalAlpha(FactorFamily):\n    pass\n",
        encoding="utf-8",
    )

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.post("/custom-factors/api/create")
    def create_custom_factor():
        payload = request.get_json() or {}
        assert "class LocalAlpha" in payload["source_code"]
        return jsonify(success=True, factor={"id": "LocalAlpha", "name": "LocalAlpha"})

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family",
            "--path",
            str(source_path),
            "--group-name",
            "LocalA1",
            "--split-count",
            "5",
            "--group-index",
            "1",
            "--product-group",
            "from-candidates",
            "--name",
            "中国期货日盘",
        ])

        assert result.exit_code != 0
        assert "新增分组缺少 factor" in result.output

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family",
            "--path",
            str(source_path),
            "--factor",
            "--alias",
            "LocalAlpha|N:2m",
            "--group-name",
            "LocalA1",
            "--split-count",
            "5",
            "--group-index",
            "1",
            "--product-group",
            "from-candidates",
            "--name",
            "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "名称: LocalA1" in result.output
        assert "因子: LocalAlpha|N:2m" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "因子=LocalAlpha|N:2m" in result.output


def test_backtest_add_group_uses_backend_registered_candidate_field_commands(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[])

    @app.get("/api/factor-library-configs/<factor_family>")
    def factor_library_configs(factor_family: str):
        return jsonify(success=True, users=[{"editable": True, "config": {"params_list": []}}])

    @app.put("/api/factor-library-configs/<factor_family>")
    def save_factor_library_configs(factor_family: str):
        payload = request.get_json()
        assert payload["product_group"] == "现场路径"
        assert payload["params_list"] == [{"N": "2m"}]
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--product-path-candidates", "add",
            "--name", "现场路径",
            "--path", "Product/Futures/CNFutures/日盘",
            "--factor-candidates", "add",
            "--param", "N=2m",
        ])

        assert result.exit_code == 0
        assert "产品路径: 现场路径" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_selects_factor_and_product_group_from_candidates(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "factor": {
                "value": "",
                "label": "因子",
                "serialization": {"shared_page_field": "factor"},
            },
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[
            {"id": "pg-day", "name": "中国期货日盘"},
            {"id": "pg-night", "name": "中国期货夜盘"},
        ])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        assert request.args.get("factor_family_alias") == "SgCCS"
        assert request.args.get("product_group") == "中国期货夜盘"
        return jsonify(success=True, factors=[
            {"factor_alias": "SgCCS|N:1m"},
            {"factor_alias": "SgCCS|N:2m"},
        ])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--product-group", "from-candidates",
            "--name", "中国期货夜盘",
            "--factor", "from-candidates",
            "--product-group", "中国期货夜盘",
            "--index", "2",
        ])

        assert result.exit_code == 0
        assert "名称: A5" in result.output
        assert "分组数: 5" in result.output
        assert "分组序号: 5" in result.output
        assert "产品路径: 中国期货夜盘" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_add_group_accepts_multiple_group_sections(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--factor", "--alias", "SgCCS|N:1m",
            "--product-group", "--from-candidates", "--name", "中国期货日盘",
            "--add",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--factor", "--alias", "SgCCS|N:2m",
            "--product-group", "--from-candidates", "--name", "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "新增分组: 2" in result.output
        assert "名称: A1" in result.output
        assert "因子: SgCCS|N:1m" in result.output
        assert "名称: A5" in result.output
        assert "因子: SgCCS|N:2m" in result.output


def test_backtest_config_local_settings_is_sibling_action(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "tab_key": "allocation",
                "control_template": "select",
                "options": [{"value": "equal_risk"}, {"value": "equal_notional"}],
            },
            "liquidity_mode": {
                "value": "infinite",
                "label": "流动性模式",
                "tab_key": "execution",
                "control_template": "select",
                "options": [{"value": "infinite"}, {"value": "volume_participation"}],
            },
            "participation_rate": {
                "value": 1.0,
                "label": "参与率",
                "tab_key": "execution",
                "control_template": "number",
                "visible_when": {"liquidity_mode": ["volume_participation"]},
            },
            "slippage_mode": {
                "value": "none",
                "label": "滑点模式",
                "tab_key": "execution",
                "control_template": "select",
                "options": [{"value": "none"}, {"value": "fixed_bps"}],
            },
            "slippage_bps": {
                "value": 0.0,
                "label": "滑点bps",
                "tab_key": "execution",
                "control_template": "number",
                "visible_when": {"slippage_mode": ["fixed_bps"]},
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--allocation-mode", "equal_notional"])

        assert result.exit_code == 0
        assert "已更新 local-settings" in result.output
        assert "allocation_mode: equal_notional" in result.output


def test_backtest_add_group_context_help_prints_registered_visible_and_editable_fields(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "control_template": "select",
                "options": [{"value": "Native", "label": "Native"}, {"value": "Backtrader", "label": "Backtrader"}],
                "order": 1,
            },
            "engine_mode": {
                "value": "basic",
                "label": "引擎模式",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "order": 2,
            },
            "warmup_mode": {
                "value": "auto",
                "label": "前摇模式",
                "tab_key": "factor_execution",
                "tab_label": "因子执行",
                "visible_when": {"engine_mode": ["auto"]},
                "editable_when": {"engine_mode": ["auto"]},
                "order": 1,
            },
            "readonly_probe": {
                "value": "locked",
                "label": "只读字段",
                "tab_key": "engine",
                "tab_label": "执行引擎",
                "editible_when": {"engine_mode": ["never"]},
                "order": 3,
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        }
        return jsonify(success=True, application=application, defaults=defaults)

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
            "--engine", "Native",
            "--engine-mode", "auto",
            "--help",
        ])

        assert result.exit_code == 0
        assert "回测设置上下文" in result.output
        assert "执行引擎" in result.output
        assert "字段" in result.output
        assert "名称" in result.output
        assert "状态" in result.output
        assert "--engine" in result.output
        assert "执行引擎" in result.output
        assert "可编辑" in result.output
        assert "Literal[Native, Backtrader]" in result.output
        assert "--engine-mode" in result.output
        assert "引擎模式" in result.output
        assert "因子执行" in result.output
        assert "--warmup-mode" in result.output
        assert "前摇模式" in result.output
        assert "--readonly-probe" in result.output
        assert "只读字段" in result.output
        assert "不可编辑" in result.output


def test_backtest_add_group_field_help_distinguishes_missing_value_from_context(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "split_count": {
                "value": 5,
                "label": "分组数",
                "tab_key": "group_strategy",
                "tab_label": "分组策略",
                "control_template": "number",
            },
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "tab_label": "执行引擎",
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["group", "--add", "--split-count", "--help"])
        assert result.exit_code == 0
        assert "--split-count 字段说明" in result.output
        assert "后端字段: split_count" in result.output
        assert "类型: number" in result.output
        assert "回测设置上下文" not in result.output

        result = runner.invoke(cli, ["group", "--add", "--split-count", "5", "--help"])
        assert result.exit_code == 0
        assert "回测设置上下文" in result.output
        assert "--split-count" in result.output
        assert "分组数" in result.output
        assert "执行引擎" in result.output


def test_cli_help_pages_explain_navigation_and_backtest_construction() -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "FactorTester CLI" in result.output
    assert "factortester single_factor_test" in result.output
    assert "--factor-family SgCCS" in result.output
    assert "字段级帮助示例" in result.output

    result = runner.invoke(cli, ["single_factor_test", "--help"])
    assert result.exit_code == 0
    assert "进入单因子测试控制界面" in result.output
    assert "factortester single_factor_test" in result.output
    assert "backtest" in result.output

    result = runner.invoke(cli, ["backtest", "--help"])
    assert result.exit_code == 0
    assert "进入通用回测控制界面" in result.output
    assert "factortester backtest group" in result.output


def test_backtest_add_ls_can_reference_existing_groups_and_inline_group(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        assert runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--split-count", "5",
            "--group-index", "1",
        ]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "long-short",
            "--add",
            "--name", "LS A1/A5",
            "--long-group", "A1",
            "--short-group",
            "--add",
            "--group-name", "A5",
            "--split-count", "5",
            "--group-index", "5",
            "--factor", "--alias", "SgCCS|N:2m",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
        ])

        assert result.exit_code == 0
        assert "新增 Long-Short" in result.output
        assert "名称: LS A1/A5" in result.output
        assert "多头: A1" in result.output
        assert "空头: A5" in result.output


def test_backtest_group_actions_batch_edit_describe_list_and_run_use_login_page_uuid(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_home_modules(app)
    received_payloads: list[dict] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-login-1")

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "allocation_mode": {
                "value": "equal_risk",
                "label": "分配方式",
                "tab_key": "allocation",
                "control_template": "select",
                "options": [{"value": "equal_risk"}, {"value": "equal_notional"}],
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    @app.post("/add_factor_by_params")
    def add_factor_by_params_for_backtest_actions():
        payload = request.get_json() or {}
        assert payload["page_uuid"] == "page-login-1"
        return jsonify(success=True, factor_alias="SgCCS|N:1m")

    @app.post("/run_group_test_stream")
    def run_group_test_stream():
        received_payloads.append(request.get_json())
        body = "\n".join([
            "event: activity",
            'data: {"label": "准备运行"}',
            "",
            "event: complete",
            "data: {}",
            "",
        ])
        return Response(body, mimetype="text/event-stream")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        result = runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"])
        assert result.exit_code == 0
        assert "页面上下文: page-login-1" in result.output
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--factor-family", "SgCCS",
            "--batch",
            "--group-names", "A1", "A2",
            "--split-count", "2",
            "--product-group", "from-candidates",
            "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
        ])
        assert result.exit_code == 0
        assert "新增分组: 2" in result.output
        assert "分组序号: 1" in result.output
        assert "分组序号: 2" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "1. A1 · 分组数=2 · 分组序号=1" in result.output
        assert "2. A2 · 分组数=2 · 分组序号=2" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A1", "--derive", "--group-name", "A1a"])
        assert result.exit_code == 0
        assert "新增派生分组: 1" in result.output
        assert "名称: A1a" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A2", "--copy", "--group-name", "A2-copy"])
        assert result.exit_code == 0
        assert "新增复制分组: 1" in result.output
        assert "名称: A2-copy" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-name", "A1", "--describe"])
        assert result.exit_code == 0
        assert "名称: A1" in result.output

        result = runner.invoke(cli, [
            "backtest",
            "local-settings",
            "--liquidity-mode", "infinite",
            "--slippage-mode", "none",
        ])
        assert result.exit_code == 0
        assert "liquidity_mode: infinite" in result.output
        assert "slippage_mode: none" in result.output

        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--group-names", "A1", "A2",
            "--edit",
            "--allocation-mode", "equal_notional",
            "--liquidity-mode", "volume_participation",
            "--participation-rate", "0.25",
            "--slippage-mode", "fixed_bps",
            "--slippage-bps", "3",
        ])
        assert result.exit_code == 0
        assert "已修改分组: 2" in result.output

        result = runner.invoke(cli, ["backtest", "long-short", "--add", "--ls-name", "LS A1/A2", "--long-group", "A1", "--short-group", "A2"])
        assert result.exit_code == 0
        result = runner.invoke(cli, ["backtest", "long-short", "list"])
        assert result.exit_code == 0
        assert "LS A1/A2" in result.output

        result = runner.invoke(cli, [
            "backtest", "strategy-book", "ledger",
            "--strategy", "A1",
            "--ledger", "shared-main",
            "--cash-pool", "pool-main",
            "--default",
        ])
        assert result.exit_code == 0
        assert "StrategyBook" in result.output
        assert "A1" in result.output
        assert "shared-main" in result.output

        result = runner.invoke(cli, [
            "backtest", "strategy-book", "cash-pool",
            "--cash-pool", "pool-main",
            "--initial-capital-major", "100000000",
            "--base-currency", "CNY",
        ])
        assert result.exit_code == 0
        assert "pool-main" in result.output

        result = runner.invoke(cli, [
            "backtest", "ledger-config",
            "--ledger", "shared-main",
            "--fee-mode", "auto",
            "--margin-mode", "auto",
            "--daily-mark-to-market-enabled", "true",
            "--cash-reserve-ratio", "0.1",
        ])
        assert result.exit_code == 0
        assert "已更新 ledger config: shared-main" in result.output
        assert "daily_mark_to_market_enabled=True" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--group-names", "A1", "A2", "--run"])
        assert result.exit_code == 0
        assert "开始运行回测: groups=2, long-short=1" in result.output
        assert "策略信息:" in result.output
        assert "A1 · 分组数=2 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "当前: 准备运行" in result.output
        assert "回测完成" in result.output

    assert len(received_payloads) == 1
    payload = received_payloads[0]
    assert payload["page_uuid"] == "page-login-1"
    assert [group["name"] for group in payload["groups"]] == ["A1", "A2"]
    assert {group["factor_family_alias"] for group in payload["groups"]} == {"SgCCS"}
    assert all(group["allocation_mode"] == "equal_notional" for group in payload["groups"])
    assert payload["local_settings"]["liquidity_mode"] == "infinite"
    assert payload["local_settings"]["slippage_mode"] == "none"
    assert all(group["liquidity_mode"] == "volume_participation" for group in payload["groups"])
    assert all(group["participation_rate"] == "0.25" for group in payload["groups"])
    assert all(group["slippage_mode"] == "fixed_bps" for group in payload["groups"])
    assert all(group["slippage_bps"] == "3" for group in payload["groups"])
    assert payload["ls_configs"][0]["name"] == "LS A1/A2"
    group_ids = {group["name"]: group["id"] for group in payload["groups"]}
    assert payload["strategy_book"]["strategies"][group_ids["A1"]]["ledger_ids"] == ["shared-main"]
    assert payload["strategy_book"]["strategies"][group_ids["A1"]]["default_ledger_id"] == "shared-main"
    assert payload["strategy_book"]["cash_pools"]["shared-main"] == "pool-main"
    assert payload["strategy_book"]["cash_pool_configs"]["pool-main"]["initial_capital_major"] == 100000000.0
    assert payload["strategy_book"]["cash_pool_configs"]["pool-main"]["base_currency"] == "CNY"
    assert payload["ledger_configs"]["shared-main"]["fee_mode"] == "auto"
    assert payload["ledger_configs"]["shared-main"]["margin_mode"] == "auto"
    assert payload["ledger_configs"]["shared-main"]["daily_mark_to_market_enabled"] is True
    assert payload["ledger_configs"]["shared-main"]["cash_reserve_ratio"] == 0.1


def test_backtest_run_renders_manifest_progress_and_verbose_events(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    app.secret_key = "test-secret"
    register_home_modules(app)

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-login-1")

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
            "equity_compute_live": {"value": True},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    @app.post("/add_factor_by_params")
    def add_factor_by_params_for_run_renderer():
        payload = request.get_json() or {}
        assert payload["page_uuid"] == "page-login-1"
        return jsonify(success=True, factor_alias="SgCCS|N:1m")

    @app.post("/run_group_test_stream")
    def run_group_test_stream():
        body = "\n".join([
            "event: activity_manifest",
            'data: {"phases":[{"key":"pre_replay","label":"准备","flows":[{"flow_key":"market_data","flow_label":"加载行情","display_order":1}]},{"key":"event_replay","label":"事件回放","flows":[{"flow_key":"signal.target","flow_label":"合成目标","display_order":1,"event_kind":"SIGNAL"},{"flow_key":"notice.roll","flow_label":"换月通知","display_order":2,"event_kind":"ORDER_NOTICE"},{"flow_key":"order.fill","flow_label":"成交记账","display_order":3,"event_kind":"ORDER"}]},{"key":"post_replay","label":"整理","flows":[{"flow_key":"risk","flow_label":"计算风险指标","display_order":1}]}]}',
            "",
            "event: activity",
            'data: {"phase":"pre_replay","phase_label":"准备","flow_key":"market_data","flow_label":"加载行情","timestamp":"2026-01-02 09:00:00"}',
            "",
            "event: signal_progress",
            'data: {"completed":1,"total":4,"phase":"event_replay"}',
            "",
            "event: activity",
            'data: {"phase":"event_replay","phase_label":"事件回放","flow_key":"signal.target","flow_label":"合成目标","timestamp":"2026-01-02 09:01:00"}',
            "",
            "event: runtime_info",
            'data: {"type":"产品路径","status":"已移除","detail":"ER.CZC(早籼稻)"}',
            "",
            "event: activity",
            'data: {"phase":"post_replay","phase_label":"整理","flow_key":"risk","flow_label":"计算风险指标","timestamp":"2026-01-31 15:00:00"}',
            "",
            "event: result",
            'data: {"success":true,"product_path_selection_id":"pg-day","groups":[{"id":"g-a1","name":"A1","total_equity":[100000000,100200000,100100000,100500000],"timestamps":[1000,2000,3000,4000]},{"id":"ls-a1-a5","name":"LS A1/A5","is_ls":true,"total_equity":[100000000,99900000,100300000],"timestamps":[1000,2000,3000]}]}',
            "",
            "event: complete",
            "data: {}",
            "",
        ])
        return Response(body, mimetype="text/event-stream")

    @app.post("/get_group_snapshot")
    def group_snapshot():
        payload = request.get_json() or {}
        return jsonify(
            success=True,
            timestamp_ms=payload.get("timestamp_ms"),
            event_label="成交后账本",
            summary={"total_changed": 2, "total_prod_count": 5, "avg_turnover": 40.0},
            matrices=[{"label": "实际持仓 · 合约", "columns": [{"label": "A1"}], "rows": [{"name": "现金"}]}],
        )

    @app.post("/get_group_order_flow")
    def group_order_flow():
        payload = request.get_json() or {}
        return jsonify(
            success=True,
            record_count=2,
            groups=[{"group_id": payload.get("group_id") or "g-a1", "group_name": "A1", "records": [{"order_id": "o1"}, {"order_id": "o2"}]}],
        )

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        assert runner.invoke(cli, [
            "backtest", "group", "--add",
            "--factor-family", "SgCCS",
            "--group-name", "A1",
            "--product-group", "from-candidates", "--name", "中国期货日盘",
            "--factor", "--alias", "SgCCS|N:1m",
        ]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "--run", "--verbose"])

    assert result.exit_code == 0
    assert "流程图:" not in result.output
    assert "总进度:" in result.output
    assert "准备: [################] 100.0%" in result.output
    assert "事件回放: [####------------]  25.0%" in result.output
    assert "整理: [################] 100.0%" in result.output
    assert "1/4" not in result.output
    assert "当前: 准备 · 2026-01-02 09:00:00 1/1 加载行情" in result.output
    assert "当前: 事件回放 · 2026-01-02 09:01:00 合成目标" in result.output
    assert "当前: 整理 · 2026-01-31 15:00:00 1/1 计算风险指标" in result.output
    assert "[activity] phase=event_replay flow=signal.target" in result.output
    assert "[progress] phase=event_replay" not in result.output
    assert "[运行信息] 产品路径: ER.CZC(早籼稻)" in result.output
    assert "[live] 刷新净值曲线" in result.output
    assert "净值曲线:" in result.output
    assert result.output.index("净值曲线:") < result.output.index("结果摘要:")
    assert "A1" in result.output
    assert "LS A1/A5 LS" in result.output
    assert "结果摘要:" in result.output
    summary_output = result.output.split("结果摘要:", 1)[1]
    summary_lines = [line for line in summary_output.splitlines() if "100500000.00" in line or "100300000.00" in line]
    assert len(summary_lines) == 2
    assert len({line.index("100") for line in summary_lines}) == 1
    assert "A1" in summary_lines[0]
    assert "100500000.00" in summary_lines[0]
    assert "0.50%" in summary_lines[0]
    assert "LS A1/A5 · LS" in summary_lines[1]
    assert "100300000.00" in summary_lines[1]
    assert "0.30%" in summary_lines[1]
    assert "回测完成" in result.output
    assert "结果查看:" in result.output
    assert "factortester backtest results summary" in result.output

    result = runner.invoke(cli, ["backtest", "results", "summary"])
    assert result.exit_code == 0
    assert "最近一次回测摘要" in result.output
    assert "最终权益" in result.output
    assert "A1" in result.output

    result = runner.invoke(cli, ["backtest", "results", "equity"])
    assert result.exit_code == 0
    assert "净值曲线:" in result.output

    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0
        result = runner.invoke(cli, ["backtest", "results", "snapshot", "--index", "2"])
        assert result.exit_code == 0
        assert "快照: timestamp_ms=2000" in result.output
        assert "成交后账本" in result.output

        result = runner.invoke(cli, ["backtest", "results", "order-flow", "--group-name", "A1"])
        assert result.exit_code == 0
        assert "订单流: records=2" in result.output
        assert "A1" in result.output


def test_backtest_tty_status_keeps_pre_and_post_current_flow() -> None:
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    renderer = BacktestRunRenderer(verbose=False)
    manifest = {
        "phases": [
            {"key": "pre_replay", "label": "回放准备", "flows": [
                {"flow_key": "pre.window", "flow_label": "解析运行时间窗口", "display_order": 1},
            ]},
            {"key": "event_replay", "label": "事件回放", "flows": [
                {"flow_key": "signal.target", "flow_label": "合成目标", "display_order": 1, "event_kind": "SIGNAL"},
            ]},
            {"key": "post_replay", "label": "结果整理", "flows": [
                {"flow_key": "post.risk", "flow_label": "计算风险指标", "display_order": 1},
            ]},
        ],
    }
    stream = TtyBuffer()
    with contextlib.redirect_stdout(stream):
        renderer.handle("activity_manifest", manifest)
        renderer.handle("activity", {
            "phase": "pre_replay",
            "phase_label": "回放准备",
            "flow_key": "pre.window",
            "flow_label": "解析运行时间窗口",
        })
        renderer.handle("progress", {"phase": "pre_replay", "percent": 5})
        renderer.handle("activity", {
            "phase": "post_replay",
            "phase_label": "结果整理",
            "flow_key": "post.risk",
            "flow_label": "计算风险指标",
        })
        renderer.handle("progress", {"phase": "post_replay", "percent": 95})

    raw = stream.getvalue()
    assert "当前: 回放准备 · 1/1 解析运行时间窗口" in raw
    assert "当前: 结果整理 · 1/1 计算风险指标" in raw
    assert "\n\n\n" not in raw


def test_backtest_tty_live_result_is_append_only_and_does_not_repaint() -> None:
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    renderer = BacktestRunRenderer(verbose=False, live=True)
    stream = TtyBuffer()

    with contextlib.redirect_stdout(stream):
        renderer._print_live_chart(["净值曲线:", "A1  100 ─ 101"])

    assert stream.getvalue().splitlines() == ["净值曲线:", "A1  100 ─ 101"]


def test_backtest_verbose_event_activity_is_throttled(monkeypatch) -> None:
    timestamps = iter([0.0, 0.5, 2.2])
    monkeypatch.setattr(run_output.time, "monotonic", lambda: next(timestamps))
    renderer = BacktestRunRenderer(verbose=True)
    stream = io.StringIO()

    with contextlib.redirect_stdout(stream):
        for minute in ("09:01:00", "09:02:00", "09:03:00"):
            renderer.handle("activity", {
                "phase": "event_replay",
                "phase_label": "事件回放",
                "flow_key": "signal.target",
                "flow_label": "合成目标",
                "timestamp": f"2026-01-02 {minute}",
            })

    raw = stream.getvalue()
    assert raw.count("当前: 事件回放") == 2
    assert raw.count("[activity] phase=event_replay") == 2
    assert "2026-01-02 09:01:00" in raw
    assert "2026-01-02 09:02:00" not in raw
    assert "2026-01-02 09:03:00" in raw


def test_backtest_tty_event_activity_is_throttled_by_wall_clock(monkeypatch) -> None:
    class TtyBuffer(io.StringIO):
        def isatty(self) -> bool:
            return True

    timestamps = iter([0.0, 0.5, 2.2])
    monkeypatch.setattr(run_output.time, "monotonic", lambda: next(timestamps))
    renderer = BacktestRunRenderer(verbose=False)
    stream = TtyBuffer()

    with contextlib.redirect_stdout(stream):
        for minute in ("09:01:00", "09:02:00", "09:03:00"):
            renderer.handle("activity", {
                "phase": "event_replay",
                "phase_label": "事件回放",
                "flow_key": "signal.target",
                "flow_label": "合成目标",
                "timestamp": f"2026-01-02 {minute}",
            })

    raw = stream.getvalue()
    assert "2026-01-02 09:01:00" in raw
    assert "2026-01-02 09:02:00" not in raw
    assert "2026-01-02 09:03:00" in raw


def test_backtest_group_add_help_and_batch_help_use_action_specific_text(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "group", "--add", "--help"])
        assert result.exit_code == 0
        assert "group --add 动作说明" in result.output

        result = runner.invoke(cli, ["backtest", "group", "--add", "--batch", "--help"])
        assert result.exit_code == 0
        assert "group --add --batch 字段说明" in result.output


def test_single_factor_template_load_restores_backtest_state_and_clear_resets_draft(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    snapshot = {
        "factors": {
            "factor_candidates": [{"alias": "SgCCS|N:2m", "params": {"N": "2m"}}],
            "factor": "SgCCS|N:2m",
        },
        "local_settings": {"allocation_mode": "equal_notional"},
        "group_settings": {
            "groups": [{
                "id": "g1",
                "name": "A1",
                "splitCount": 5,
                "groupIndex": 1,
                "factorAlias": "SgCCS|N:2m",
                "product_path_selection": {"product_path_selection_id": "pg-day", "product_group": "中国期货日盘"},
            }],
            "lsConfigs": [{
                "id": "ls1",
                "name": "LS A1/A5",
                "longGroupId": "g1",
                "shortGroupId": "g5",
            }],
        },
        "strategy_book": {
            "strategies": {
                "A1": {"ledger_ids": ["shared-main"], "default_ledger_id": "shared-main"},
            },
            "cash_pools": {"shared-main": "pool-main"},
            "cash_pool_configs": {"pool-main": {"initial_capital_major": 100000000, "base_currency": "CNY"}},
        },
        "ledger_configs": {
            "shared-main": {
                "fee_mode": "auto",
                "margin_mode": "auto",
                "daily_mark_to_market_enabled": True,
            }
        },
    }

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "single_factor_page", "label": "因子家族测试设置", "kind": "module", "has_children": True},
                {"key": "group_test", "label": "分组回测", "kind": "module", "has_children": True},
            ])
        if parent == "group_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[{"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True}])

    @app.get("/api/single_factor_setting_templates/<factor_family>")
    def templates(factor_family: str):
        assert factor_family == "SgCCS"
        return jsonify(success=True, templates=[{"id": "tpl-20260602", "name": "2026-06-02 07:20:47"}])

    @app.get("/api/single_factor_setting_templates/<factor_family>/<template_id>")
    def template_detail(factor_family: str, template_id: str):
        assert factor_family == "SgCCS"
        assert template_id == "tpl-20260602"
        return jsonify(success=True, template={"id": template_id, "name": "2026-06-02 07:20:47", "snapshot": snapshot})

    saved_templates: list[dict[str, object]] = []

    @app.post("/api/single_factor_setting_templates/<factor_family>")
    def save_template(factor_family: str):
        assert factor_family == "SgCCS"
        payload = request.get_json() or {}
        saved_templates.append(payload)
        return jsonify(success=True, id="tpl-cli")

    registered_factors: list[dict[str, object]] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-template-1")

    @app.post("/add_factor_by_params")
    def add_factor_by_params():
        payload = request.get_json() or {}
        registered_factors.append(payload)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        return jsonify(success=True, factor_alias=f"SgCCS|N:{params.get('N')}")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "list"])
        assert result.exit_code == 0
        assert "2026-06-02 07:20:47 · id=tpl-20260602" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "help"])
        assert result.exit_code == 0
        assert "template 命令" in result.output
        assert "save [模板名]" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "template", "load", "2026-06-02 07:20:47"])
        assert result.exit_code == 0
        assert "已加载模板: 2026-06-02 07:20:47" in result.output
        assert "groups: 1" in result.output
        assert "strategy-book: 1" in result.output
        assert "ledger-configs: 1" in result.output
        assert "已注册因子: 1" in result.output
        assert registered_factors == [{
            "factor_family_alias": "SgCCS",
            "params": {"N": "2m"},
            "page_uuid": "page-template-1",
        }]

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "（空）" in result.output

        result = runner.invoke(cli, ["backtest", "strategy-book", "show"])
        assert result.exit_code == 0
        assert "StrategyBookSimple" in result.output

        result = runner.invoke(cli, ["backtest", "ledger-config", "show"])
        assert result.exit_code == 0
        assert "（空；使用后端注册字段的默认/推断规则）" in result.output

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "backtest"])
        assert result.exit_code == 0
        assert "草稿空间: single_factor_test/backtest · SgCCS" in result.output
        result = runner.invoke(cli, ["group", "list"])
        assert result.exit_code == 0
        assert "A1 · 分组数=5 · 分组序号=1" in result.output
        assert "产品路径=中国期货日盘" in result.output
        assert "因子=SgCCS|N:2m" in result.output

        result = runner.invoke(cli, ["long-short", "list"])
        assert result.exit_code == 0
        assert "LS A1/A5" in result.output
        assert "多头=g1" in result.output

        result = runner.invoke(cli, ["strategy-book", "show"])
        assert result.exit_code == 0
        assert "shared-main" in result.output
        assert "pool-main" in result.output

        result = runner.invoke(cli, ["ledger-config", "show"])
        assert result.exit_code == 0
        assert "shared-main" in result.output
        assert "fee_mode=auto" in result.output

        result = runner.invoke(cli, ["backtest", "template", "--from-module-template", "single_factor_test", "load", "2026-06-02 07:20:47"])
        assert result.exit_code == 0
        assert "来自 single_factor_test 模板" in result.output
        assert "strategy-book: 1" in result.output
        assert "ledger-configs: 1" in result.output

        result = runner.invoke(cli, ["backtest", "template", "save", "CLI 草稿"])
        assert result.exit_code == 0
        assert "已保存模板: CLI 草稿" in result.output
        assert saved_templates[-1]["name"] == "CLI 草稿"
        assert saved_templates[-1]["ff_alias"] == "SgCCS"
        assert (saved_templates[-1]["snapshot"])["group_settings"]["groups"][0]["name"] == "A1"
        assert (saved_templates[-1]["snapshot"])["strategy_book"]["strategies"]["A1"]["default_ledger_id"] == "shared-main"
        assert (saved_templates[-1]["snapshot"])["ledger_configs"]["shared-main"]["fee_mode"] == "auto"

        result = runner.invoke(cli, ["backtest", "template", "help"])
        assert result.exit_code == 0
        assert "backtest template 命令" in result.output
        assert "load <模板ID或名称>" in result.output

        result = runner.invoke(cli, ["backtest"])
        assert result.exit_code == 0
        assert "allocation_mode: equal_notional" in result.output

        result = runner.invoke(cli, ["backtest", "clear"])
        assert result.exit_code == 0
        assert "已清空 backtest 配置" in result.output

        result = runner.invoke(cli, ["backtest", "group", "list"])
        assert result.exit_code == 0
        assert "（空）" in result.output


def test_ic_test_cli_adds_config_and_runs_stream(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    app.secret_key = "test-secret"
    received_payloads: list[dict[str, object]] = []

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-ic-1")

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "ic_test", "label": "IC 测试", "kind": "module", "has_children": True},
            ])
        if parent == "ic_test":
            return jsonify(success=True, parent=parent, modules=[])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
            {"key": "ic_test", "label": "IC 测试", "kind": "module", "application": "ic_test", "has_children": True},
        ])

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        base_defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "control_template": "custom",
                "tab_key": "product_path_selection",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "control_template": "custom",
                "tab_key": "factor",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
        }
        if application == "single_factor_page":
            return jsonify(success=True, application=application, defaults=base_defaults)
        if application == "ic_test":
            defaults = {
                **base_defaults,
                "product_path_selections": {
                    "value": [],
                    "label": "产品路径选择",
                    "control_template": "custom",
                    "tab_key": "product_path_selection",
                },
                "factor_selections": {
                    "value": [],
                    "label": "因子选择",
                    "control_template": "custom",
                    "tab_key": "factor",
                },
                "ic_correlation": {
                    "value": "rank",
                    "label": "默认 IC",
                    "control_template": "select",
                    "tab_key": "ic_method",
                    "options": [
                        {"value": "rank", "label": "Rank IC"},
                        {"value": "pearson", "label": "Pearson IC"},
                        {"value": "both", "label": "Rank + Pearson"},
                    ],
                },
                "ic_lag": {
                    "value": 0,
                    "label": "IC Lag",
                    "control_template": "number",
                    "tab_key": "delay",
                },
                "ic_decay_lags": {
                    "value": 5,
                    "label": "IC 衰减阶数",
                    "control_template": "number",
                    "tab_key": "delay",
                },
                "group_adjust": {
                    "value": "off",
                    "label": "组内去均值",
                    "control_template": "select",
                    "tab_key": "cross_section",
                    "options": [{"value": "off"}, {"value": "on"}],
                },
                "by_group": {
                    "value": "off",
                    "label": "分组 IC",
                    "control_template": "select",
                    "tab_key": "cross_section",
                    "options": [{"value": "off"}, {"value": "on"}],
                },
                "rolling_window": {
                    "value": 20,
                    "label": "滚动窗口",
                    "control_template": "number",
                    "tab_key": "summary",
                },
            }
            return jsonify(success=True, application=application, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘", "paths": ["Product/Futures/CNFutures/日盘"]}])

    @app.post("/run_ic_test_stream")
    def run_ic_test_stream():
        payload = request.get_json() or {}
        received_payloads.append(payload)

        def stream():
            yield 'event: start\ndata: {"total": 2, "groups": 1, "phase": "init"}\n\n'
            yield 'event: progress\ndata: {"completed": 1, "total": 2, "phase": "eval"}\n\n'
            yield (
                'event: result\ndata: '
                '{"success": true, "ic_stats": {"columns": ["index", "SgCCS|N:2m"], '
                '"rows": [{"index": "mean", "SgCCS|N:2m": 0.123456}, '
                '{"index": "ir", "SgCCS|N:2m": 1.5}]}, '
                '"factors": [{"alias": "SgCCS|N:2m", "ic_series": {"dates": [1,2,3], "values": [0.1, 0.2, -0.1]}, '
                '"rolling_ic": {"window": 3, "mean": [0.066], "ir": [0.4]}, '
                '"ic_decay": [{"lag": 1, "mean": 0.1, "ir": 0.5, "n": 3}, {"lag": 2, "mean": 0.2, "ir": 0.6, "n": 3}]}]}\n\n'
            )

        return Response(stream(), mimetype="text/event-stream")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, ["single_factor_test", "--factor-family", "SgCCS", "ic_test"])
        assert result.exit_code == 0
        assert "IC 测试" in result.output

        result = runner.invoke(cli, ["ic_test", "local-settings", "--help"])
        assert result.exit_code == 0
        assert "IC 设置上下文" in result.output
        assert "--ic-correlation" in result.output

        result = runner.invoke(cli, [
            "ic_test",
            "local-settings",
            "--ic-correlation", "both",
            "--ic-lag", "1",
            "--ic-decay-lags", "3",
            "--rolling-window", "3",
            "--group-adjust", "on",
            "--by-group", "on",
        ])
        assert result.exit_code == 0
        assert "已更新 IC local-settings" in result.output

        result = runner.invoke(cli, [
            "ic_test",
            "config",
            "--add",
            "--name",
            "日盘IC",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "新增 IC 配置" in result.output
        assert "产品路径=中国期货日盘" in result.output

        result = runner.invoke(cli, ["ic_test", "--run", "--verbose"])
        assert result.exit_code == 0
        assert "开始运行 IC 测试: configs=1" in result.output
        assert "进度: eval 1/2" in result.output
        assert "IC 结果摘要" in result.output
        assert "指标" in result.output
        assert "因子" in result.output
        assert "mean" in result.output
        assert "SgCCS|N:2m" in result.output
        assert "0.123456" in result.output
        assert "IC 序列图" in result.output
        assert "Rolling IC" in result.output
        assert "IC 衰减" in result.output
        assert received_payloads
        assert received_payloads[-1]["page_uuid"] == "page-ic-1"
        assert received_payloads[-1]["factor_family_alias"] == "SgCCS"
        assert received_payloads[-1]["product_path_selection_id"] == "pg-day"
        assert received_payloads[-1]["factors"] == [{"alias": "SgCCS|N:2m"}]
        assert (received_payloads[-1]["settings"])["ic_correlation"] == "both"
        assert (received_payloads[-1]["settings"])["group_adjust"] == "on"
        assert (received_payloads[-1]["settings"])["by_group"] == "on"
        assert received_payloads[-1]["ic_correlation"] == "both"
        assert received_payloads[-1]["ic_lag"] == "1"
        assert received_payloads[-1]["ic_decay_lags"] == [1, 2, 3]
        assert received_payloads[-1]["rolling_window"] == "3"

        result = runner.invoke(cli, [
            "ic_test",
            "local-settings",
            "--ic-correlation", "pearson",
            "--ic-lag", "0",
            "--ic-decay-lags", "1",
            "--rolling-window", "2",
            "--group-adjust", "off",
            "--by-group", "off",
        ])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["ic_test", "--run"])
        assert result.exit_code == 0
        assert received_payloads[-1]["ic_correlation"] == "pearson"
        assert received_payloads[-1]["ic_lag"] == "0"
        assert received_payloads[-1]["ic_decay_lags"] == [1]
        assert received_payloads[-1]["rolling_window"] == "2"
        assert (received_payloads[-1]["settings"])["group_adjust"] == "off"
        assert (received_payloads[-1]["settings"])["by_group"] == "off"


def test_factor_evaluation_and_type_analysis_cli_run(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    app.secret_key = "test-secret"
    received: dict[str, dict[str, object]] = {}

    @app.post("/login")
    def login():
        return jsonify(success=True, username="alice")

    @app.post("/api/single_factor_test/page")
    def page():
        return jsonify(success=True, page_uuid="page-analysis-1")

    @app.get("/api/testers/modules")
    def modules():
        parent = request.args.get("parent")
        if parent == "single_factor_family_test":
            return jsonify(success=True, parent=parent, modules=[
                {"key": "factor_evaluation", "label": "因子评估", "kind": "module", "has_children": True},
                {"key": "factor_type_analysis", "label": "因子类型分析", "kind": "module", "has_children": True},
            ])
        return jsonify(success=True, modules=[
            {"key": "single_factor_test", "label": "单因子测试", "kind": "module", "has_children": True},
        ])

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        defaults = {
            "product_path_candidates": {
                "value": [],
                "label": "产品路径候选",
                "control_template": "custom",
                "tab_key": "product",
                "serialization": {"shared_page_field": "product_path_candidates"},
            },
            "product_path_selection": {
                "value": None,
                "label": "产品路径",
                "control_template": "custom",
                "tab_key": "product",
                "serialization": {"shared_page_field": "product_path_selection"},
            },
            "factor_candidates": {
                "value": [],
                "label": "因子候选",
                "control_template": "custom",
                "tab_key": "factor",
                "serialization": {"shared_page_field": "factor_candidates"},
            },
            "start_date": {"value": "", "label": "开始日期", "control_template": "date", "tab_key": "time"},
            "end_date": {"value": "", "label": "结束日期", "control_template": "date", "tab_key": "time"},
        }
        if application == "factor_type_analysis":
            defaults["correlation_method"] = {
                "value": "pearson",
                "label": "相关性方法",
                "control_template": "select",
                "tab_key": "method",
                "options": [
                    {"value": "pearson", "label": "Pearson"},
                    {"value": "spearman", "label": "Spearman"},
                ],
            }
        if application in {"single_factor_page", "factor_evaluation", "factor_type_analysis"}:
            return jsonify(success=True, application=application, defaults=defaults)
        return jsonify(success=False, error="unknown application"), 404

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{
            "id": "pg-day",
            "name": "中国期货日盘",
            "paths": ["Product/Futures/CNFutures/日盘/_products/AP.CZC"],
        }])

    @app.post("/api/factor_evaluation/evaluate")
    def factor_evaluation_endpoint():
        payload = request.get_json() or {}
        received["factor_evaluation"] = payload
        return jsonify(success=True, factor={"alias": payload.get("factor_alias")}, meta={"product_count": 1, "elapsed_ms": 12}, series=[
            {"product": "AP.CZC", "desc": "苹果", "dates": [1, 2], "values": [0.1, 0.2]},
        ])

    @app.post("/api/factor_type_analysis/analyze")
    def factor_type_endpoint():
        payload = request.get_json() or {}
        received["factor_type_analysis"] = payload
        return jsonify(success=True, best_match={"category_label": "趋势", "correlation": 0.81}, reference_factors=[
            {"key": "trend", "name": "趋势参照", "correlation": 0.81},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["login", "--username", "alice", "--password", "pw"]).exit_code == 0

        result = runner.invoke(cli, [
            "factor_evaluation",
            "run",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "开始因子评估" in result.output
        assert "产品" in result.output
        assert "描述" in result.output
        assert "点数" in result.output
        assert "AP.CZC" in result.output
        assert "苹果" in result.output
        assert "因子序列图" in result.output
        assert received["factor_evaluation"]["page_uuid"] == "page-analysis-1"
        assert received["factor_evaluation"]["paths"] == ["Product/Futures/CNFutures/日盘/_products/AP.CZC"]

        result = runner.invoke(cli, ["factor_type_analysis", "local-settings", "--correlation-method", "spearman"])
        assert result.exit_code == 0

        result = runner.invoke(cli, [
            "factor_type_analysis",
            "run",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--factor",
            "--alias",
            "SgCCS|N:2m",
        ])
        assert result.exit_code == 0
        assert "开始因子类型分析" in result.output
        assert "最佳类型" in result.output
        assert "类型" in result.output
        assert "相关性" in result.output
        assert "趋势" in result.output
        assert received["factor_type_analysis"]["settings"]["correlation_method"] == "spearman"


def test_custom_factor_workspace_cli_maps_web_workspace_actions(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)
    calls: list[tuple[str, dict]] = []

    @app.get("/custom-factors/api/source-root")
    def source_root():
        return jsonify(success=True, source_root="", resolved_root="/tmp/factor-workspace")

    @app.post("/custom-factors/api/source-root")
    def save_source_root():
        payload = request.get_json() or {}
        calls.append(("save-root", payload))
        return jsonify(success=True, source_root=payload.get("source_root"), resolved_root=payload.get("source_root"))

    @app.post("/custom-factors/api/workspace/build")
    def build_workspace():
        calls.append(("build", request.get_json() or {}))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", custom_factor_count=2, public_factor_count=1)

    @app.post("/custom-factors/api/workspace/sync")
    def sync_workspace():
        payload = request.get_json() or {}
        calls.append(("sync", payload))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", git_selected_branch=payload.get("branch_mode"), touched_files=["custom_factors/A.py"])

    @app.post("/custom-factors/api/workspace/push")
    def push_workspace():
        payload = request.get_json() or {}
        calls.append(("push", payload))
        return jsonify(success=True, workspace_root="/tmp/factor-workspace", git_selected_branch=payload.get("branch_mode"), updated_custom_count=1)

    @app.get("/custom-factors/api/workspace/git-settings")
    def git_settings():
        return jsonify(success=True, git_enabled=True, git_repo_root="/tmp/factor-workspace", git_current_branch="factor-upload", git_branches=["factor-upload"])

    @app.post("/custom-factors/api/workspace/git-settings")
    def save_git_settings():
        payload = request.get_json() or {}
        calls.append(("git-settings", payload))
        return jsonify(success=True, git_enabled=payload.get("git_enabled"), git_repo_root=payload.get("git_repo_root"), git_current_branch="factor-upload")

    @app.post("/custom-factors/api/workspace/git")
    def workspace_git():
        payload = request.get_json() or {}
        calls.append(("workspace-git", payload))
        action = payload.get("action")
        if action == "status":
            return jsonify(success=True, action=action, stdout="## factor-upload\n M custom_factors/SgCCS.py\n")
        if action == "diff":
            return jsonify(success=True, action=action, stdout=" custom_factors/SgCCS.py | 2 +-\n")
        if action == "commit":
            return jsonify(success=True, action=action, stdout="[factor-upload abc123] research\n", commit_sha="abc123")
        return jsonify(success=True, action=action, stdout="")

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0

        result = runner.invoke(cli, ["custom_factors"])
        assert result.exit_code == 0
        assert "workspace show|root|build|sync|push" in result.output

        result = runner.invoke(cli, ["custom_factors", "list"])
        assert result.exit_code == 0
        assert "custom_factors/factor-library" in result.output
        assert "custom_factors/workspace" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "show"])
        assert result.exit_code == 0
        assert "实际目录: /tmp/factor-workspace" in result.output
        assert "当前分支: factor-upload" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "root", "/tmp/custom-root"])
        assert result.exit_code == 0
        assert "实际目录: /tmp/custom-root" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "build"])
        assert result.exit_code == 0
        assert "建立完成" in result.output
        assert "自定义因子: 2" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "sync", "--branch-mode", "force"])
        assert result.exit_code == 0
        assert "下载同步完成" in result.output
        assert "写入文件" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "push", "--branch-mode", "auto"])
        assert result.exit_code == 0
        assert "上传入库完成" in result.output
        assert "更新自定义因子: 1" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "git-settings", "--disable", "--repo-root", "/tmp/no-git"])
        assert result.exit_code == 0
        assert "启用: 否" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "git", "status"])
        assert result.exit_code == 0
        assert "custom_factors/SgCCS.py" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "git", "diff", "--stat"])
        assert result.exit_code == 0
        assert "custom_factors/SgCCS.py | 2 +-" in result.output

        result = runner.invoke(cli, ["custom_factors", "workspace", "git", "commit", "-m", "research"])
        assert result.exit_code == 0
        assert "commit: abc123" in result.output

    assert calls == [
        ("save-root", {"source_root": "/tmp/custom-root"}),
        ("build", {}),
        ("sync", {"branch_mode": "force"}),
        ("push", {"branch_mode": "auto"}),
        ("git-settings", {"git_enabled": False, "git_repo_root": "/tmp/no-git"}),
        ("workspace-git", {"action": "status"}),
        ("workspace-git", {"action": "diff", "cached": False, "stat": True}),
        ("workspace-git", {"action": "commit", "message": "research"}),
    ]


def test_custom_factor_describe_cross_checks_source_and_operator_tree(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/custom-factors/api/list")
    def factor_list():
        return jsonify(
            success=True,
            public_factors=[],
            custom_factors=[
                {
                    "id": "MyAlpha",
                    "name": "MyAlpha",
                    "source_code": "class MyAlpha(FactorFamily):\n    def factor_expr():\n        return CLOSE.rolling_mean(N)\n",
                    "owner_username": "18717974771",
                }
            ],
        )

    @app.post("/custom-factors/api/validate")
    def validate():
        return jsonify(
            success=True,
            valid=True,
            tree_repr="RollingOp rolling_mean(ColumnRef CLOSE, ParamRef N)",
            params=[{"alias": "N", "type": "DataFreq", "default_value": "2m"}],
        )

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        result = runner.invoke(cli, ["custom_factors", "describe", "MyAlpha", "--json", "--source-code"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["source_checks"]["ok"] is True
        assert payload["operator_keys"] == ["rolling_mean"]
        assert "rolling_mean" in payload["tree_repr"]


def test_backtest_context_help_errors_on_unregistered_field(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "engine": {"value": "Native", "label": "执行引擎", "tab_key": "engine"},
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--not-registered", "x", "--help"])

        assert result.exit_code != 0
        assert "local-settings 包含未注册字段: not_registered" in result.output


def test_backtest_context_help_errors_on_invalid_registered_value(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "engine": {
                "value": "Native",
                "label": "执行引擎",
                "tab_key": "engine",
                "control_template": "select",
                "options": [{"value": "Native", "label": "Native"}],
            },
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:1m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0

        result = runner.invoke(cli, ["backtest", "local-settings", "--engine", "Bad", "--help"])

        assert result.exit_code != 0
        assert "字段 engine 的值不合法" in result.output


def test_backtest_inline_product_path_rejects_duplicate_candidate_name(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    @app.get("/api/backtest/settings/<application>")
    def settings(application: str):
        return jsonify(success=True, application=application, defaults={
            "product_path_candidates": {"value": [], "serialization": {"shared_page_field": "product_path_candidates"}},
            "product_path_selection": {"value": None, "serialization": {"shared_page_field": "product_path_selection"}},
            "factor_candidates": {"value": [], "serialization": {"shared_page_field": "factor_candidates"}},
            "factor": {"value": "", "serialization": {"shared_page_field": "factor"}},
        })

    @app.get("/api/product-groups")
    def product_groups():
        return jsonify(success=True, groups=[{"id": "pg-day", "name": "中国期货日盘"}])

    @app.get("/api/factor-library-overview")
    def factor_library_overview():
        return jsonify(success=True, factors=[{"factor_alias": "SgCCS|N:2m"}])

    @app.get("/api/testers/modules")
    def modules():
        return jsonify(success=True, modules=[
            {"key": "backtest", "label": "回测", "kind": "module", "application": "group_test", "has_children": True},
        ])

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0
        assert runner.invoke(cli, ["backtest"]).exit_code == 0
        result = runner.invoke(cli, [
            "backtest",
            "group",
            "--add",
            "--group-name", "A1",
            "--product-group", "add",
            "--name", "中国期货日盘",
            "--path", "Product/Futures/CNFutures/日盘",
        ])

        assert result.exit_code != 0
        assert "产品路径候选名称已存在: 中国期货日盘" in result.output


def test_products_and_custom_factors_expose_library_submodules_from_home(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)
    register_home_modules(app)

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        assert runner.invoke(cli, ["configure", "--base-url", url]).exit_code == 0

        result = runner.invoke(cli, ["products"])
        assert result.exit_code == 0
        assert "产品管理" in result.output

        result = runner.invoke(cli, ["products", "list"])
        assert result.exit_code == 0
        assert "当前位置: products" in result.output
        assert "[module] products/product-groups: 产品组库" in result.output

        result = runner.invoke(cli, ["custom_factors"])
        assert result.exit_code == 0
        assert "因子管理" in result.output

        result = runner.invoke(cli, ["custom_factors", "list"])
        assert result.exit_code == 0
        assert "当前位置: custom_factors" in result.output
        assert "[module] custom_factors/factor-library: 因子库" in result.output


def test_click_non_json_html_response_is_user_friendly(tmp_path, monkeypatch) -> None:
    app = Flask(__name__)

    @app.get("/static/config/modules.json")
    def modules():
        return "<!DOCTYPE html><html><head><title>工具箱</title></head><body>login</body></html>"

    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    runner = CliRunner()
    with running_server(app) as url:
        result = runner.invoke(cli, ["configure", "--base-url", url])
        assert result.exit_code == 0

        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0
        assert "服务器返回了 HTML 页面而不是 JSON" in result.output
        assert "factortester login" in result.output
        assert "<!DOCTYPE html>" not in result.output
        assert "<html" not in result.output


def test_backtest_error_wrapper_preserves_server_body() -> None:
    @click.command()
    @_backtest_errors
    def failing_backtest():
        raise HttpClientError(500, "http://server/run", "Traceback (most recent call last):\n  File \"strategy.py\", line 1")

    result = CliRunner().invoke(failing_backtest)

    assert result.exit_code != 0
    assert "Traceback (most recent call last)" in result.output
    assert "strategy.py" in result.output


def test_cli_registry_only_adapts_controllers_not_module_metadata() -> None:
    registry = ControllerRegistry()
    backtest_adapter = registry.adapter_for_backend("group_test")

    assert public_module_key("group_test/time") == "backtest/time"
    assert backtest_adapter is not None
    assert backtest_adapter.public_key == "backtest"
    assert not hasattr(backtest_adapter, "label")
    assert not hasattr(backtest_adapter, "order")
