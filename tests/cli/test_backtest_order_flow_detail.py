"""order-flow used to only print a record count ("records=163023") --
useless for checking whether a strategy actually traded the products/
directions it should have. _print_order_flow_result now defaults to
printing per-record detail (timestamp/product/step/quantity/price/status),
which is exactly the extra visibility needed to spot-check a real backtest
run against expectations."""

from __future__ import annotations

import click
import pytest

import tools.cli.modules.backtest.controller as controller


class _FakeClient:
    def __init__(self, response: dict) -> None:
        self._response = response

    def group_order_flow(self, payload: dict) -> dict:
        return self._response

    def group_detail(self, payload: dict) -> dict:
        return self._response

    def group_ranking_detail(self, payload: dict) -> dict:
        return self._response


def _fake_state() -> object:
    from tools.cli.state import CliState

    state = CliState()
    state.page_uuid = "page-1"
    state.backtest_last_result = {
        "product_path_selection_id": "pg-1",
        "groups": [{
            "id": "g-a1",
            "group_id": "g-a1",
            "name": "A1",
            "group_index": 1,
            "product_path_selection_id": "pg-1",
            "total_equity": [100_000_000.0, 101_000_000.0],
        }],
    }
    return state


def test_order_flow_prints_record_detail_by_default(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 3,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [
                # missing "quantity" entirely (not just None) -- must not crash
                {"timestamp": "t1", "step": "liquidity_cap", "label": "按流动性上限截断"},
                # explicit None quantity/effective_price -- must not crash either
                {"timestamp": "t2", "product": "SI.GFE", "step": "construct_orders",
                 "label": "构造订单", "quantity": None, "effective_price": None, "status": "draft"},
                {"timestamp": "t3", "product": "SI.GFE", "step": "fee", "label": "计算手续费",
                 "quantity": 759.7, "effective_price": 8775.0, "status": "scheduled"},
            ],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    state = _fake_state()
    controller._print_order_flow_result(state, ("--group-name", "A1"))

    out = capsys.readouterr().out
    assert "订单流: records=3" in out
    assert "订单流明细" in out
    assert "SI.GFE" in out
    assert "759.7" in out
    assert "8775" in out


def test_order_flow_counts_only_skips_detail(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 1,
        "groups": [{"group_id": "g-a1", "group_name": "A1", "records": [{"timestamp": "t1"}]}],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    state = _fake_state()
    controller._print_order_flow_result(state, ("--group-name", "A1", "--counts-only"))

    out = capsys.readouterr().out
    assert "订单流: records=1" in out
    assert "订单流明细" not in out


def test_order_flow_limit_truncates_and_reports_remainder(monkeypatch, capsys):
    records = [{"timestamp": f"t{i}", "product": "P", "quantity": 1.0} for i in range(10)]
    response = {
        "success": True,
        "record_count": len(records),
        "groups": [{"group_id": "g-a1", "group_name": "A1", "records": records}],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    state = _fake_state()
    controller._print_order_flow_result(state, ("--group-name", "A1", "--limit", "3"))

    out = capsys.readouterr().out
    assert "显示 3/10 条" in out
    assert "还有 7 条" in out
    assert "--limit 0" in out


def test_order_flow_show_fee_prints_fee_cash_and_margin(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 1,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [{
                "timestamp": "t1",
                "product": "AP.CZC",
                "step": "fee",
                "quantity": 12.0,
                "effective_price": 8000.0,
                "fee_cost": 34.5,
                "details": {
                    "ledger_id": "ledger-a1",
                    "cash_pool_id": "pool-a1",
                    "cash_after": 99_000_000.0,
                    "margin_after": 1_000_000.0,
                },
                "status": "scheduled",
            }],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_order_flow_result(_fake_state(), ("--group-name", "A1", "--show", "fee"))

    out = capsys.readouterr().out
    assert "费用" in out
    assert "34.50" in out
    assert "ledger-a1" in out
    assert "pool-a1" in out
    assert "99,000,000.00" in out
    assert "1,000,000.00" in out


def test_order_flow_can_filter_by_ledger_and_cash_pool(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 2,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [
                {"timestamp": "t1", "product": "AP.CZC", "details": {"ledger_id": "ledger-a", "cash_pool_id": "pool-a"}},
                {"timestamp": "t2", "product": "CJ.CZC", "details": {"ledger_id": "ledger-b", "cash_pool_id": "pool-b"}},
            ],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_order_flow_result(_fake_state(), ("--group-name", "A1", "--ledger", "ledger-a", "--cash-pool", "pool-a", "--limit", "0"))

    out = capsys.readouterr().out
    assert "records=1" in out
    assert "ledger=ledger-a" in out
    assert "cash_pool=pool-a" in out
    assert "AP.CZC" in out
    assert "CJ.CZC" not in out


def test_attribution_summarizes_fee_drag_and_product_fee(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 2,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [
                {"product": "AP.CZC", "fee_cost": 100.0},
                {"product": "CJ.CZC", "fee_cost": 50.0},
            ],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_attribution_result(_fake_state(), ("--group-name", "A1", "--by", "product"))

    out = capsys.readouterr().out
    assert "归因摘要" in out
    assert "gross" in out
    assert "fee" in out
    assert "AP.CZC" in out
    assert "100.00" in out


def test_attribution_can_group_fee_by_ledger(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 3,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [
                {"fee_cost": 100.0, "details": {"ledger_id": "ledger-a"}},
                {"fee_cost": 50.0, "details": {"ledger_id": "ledger-a"}},
                {"fee_cost": 20.0, "details": {"ledger_id": "ledger-b"}},
            ],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_attribution_result(_fake_state(), ("--group-name", "A1", "--by", "ledger"))

    out = capsys.readouterr().out
    assert "费用按账本聚合" in out
    assert "ledger-a" in out
    assert "150.00" in out
    assert "ledger-b" in out


def test_ledger_replay_summarizes_records_fee_and_cash(monkeypatch, capsys):
    response = {
        "success": True,
        "record_count": 2,
        "groups": [{
            "group_id": "g-a1",
            "group_name": "A1",
            "records": [
                {
                    "fee_cost": 100.0,
                    "details": {
                        "ledger_id": "ledger-a",
                        "cash_pool_id": "pool-a",
                        "cash_after": 99_000_000.0,
                        "margin_after": 1_000_000.0,
                    },
                },
                {
                    "fee_cost": 50.0,
                    "details": {
                        "ledger_id": "ledger-a",
                        "cash_pool_id": "pool-a",
                        "cash_after": 98_900_000.0,
                        "margin_after": 1_100_000.0,
                    },
                },
            ],
        }],
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_ledger_replay_result(_fake_state(), ("--group-name", "A1"))

    out = capsys.readouterr().out
    assert "Ledger 回放摘要" in out
    assert "ledger-a" in out
    assert "pool-a" in out
    assert "150.00" in out
    assert "98,900,000.00" in out
    assert "1,100,000.00" in out


def test_group_detail_prints_product_overlay_summary(monkeypatch, capsys):
    response = {
        "success": True,
        "detail": {
            "product_analysis": {
                "default_level": "products",
                "by_level": {
                    "products": {
                        "rows": [{
                            "product": {
                                "name": "AP.CZC",
                                "desc": "苹果",
                                "fee": {"open": 0.0001, "close_today": 0.0002},
                            },
                            "active_period_count": 12,
                            "gross_contribution": 0.031,
                            "market_rule": {"multiplier": 10, "margin_ratio": 0.12},
                        }],
                        "top1_positive_contribution_ratio": 0.7,
                        "top3_positive_contribution_ratio": 0.9,
                    }
                },
            }
        },
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_group_detail_result(_fake_state(), ("--group-name", "A1"))

    out = capsys.readouterr().out
    assert "A1 · 产品层级贡献" in out
    assert "AP.CZC(苹果)" in out
    assert "3.10%" in out
    assert "top1正贡献占比=70.00%" in out


def test_group_ranking_prints_scalar_summary(monkeypatch, capsys):
    response = {
        "success": True,
        "detail": {
            "monotonic_score": 0.42,
            "note": "ok",
            "adjacent_spreads": [{"name": "A1-A2"}],
        },
    }
    monkeypatch.setattr(controller, "client_from_config", lambda: _FakeClient(response))

    controller._print_group_ranking_result(_fake_state(), ())

    out = capsys.readouterr().out
    assert "分组排序能力摘要" in out
    assert "monotonic_score" in out
    assert "0.42" in out


def test_result_output_options_write_file_and_can_suppress_terminal(tmp_path, capsys):
    output = tmp_path / "replay" / "attribution.txt"
    options, cleaned = controller._parse_result_output_options((
        "attribution",
        "--group-name",
        "A1",
        "--output",
        str(output),
        "--no-terminal",
    ))

    assert cleaned == ("attribution", "--group-name", "A1")
    controller._emit_result_output(options, lambda: click.echo("归因摘要\nA1 100"))

    assert output.read_text(encoding="utf-8") == "归因摘要\nA1 100\n"
    assert capsys.readouterr().out == ""


def test_result_output_options_append_and_keep_terminal(tmp_path, capsys):
    output = tmp_path / "order-flow.txt"
    first, _ = controller._parse_result_output_options(("summary", "--output", str(output)))
    second, _ = controller._parse_result_output_options(("summary", "--output", str(output), "--append"))

    controller._emit_result_output(first, lambda: click.echo("first"))
    controller._emit_result_output(second, lambda: click.echo("second"))

    assert output.read_text(encoding="utf-8") == "first\nsecond\n"
    out = capsys.readouterr().out
    assert "first" in out
    assert "second" in out


def test_no_terminal_requires_output_path():
    with pytest.raises(click.ClickException, match="--no-terminal"):
        controller._parse_result_output_options(("summary", "--no-terminal"))
