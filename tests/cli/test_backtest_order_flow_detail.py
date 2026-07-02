"""order-flow used to only print a record count ("records=163023") --
useless for checking whether a strategy actually traded the products/
directions it should have. _print_order_flow_result now defaults to
printing per-record detail (timestamp/product/step/quantity/price/status),
which is exactly the extra visibility needed to spot-check a real backtest
run against expectations."""

from __future__ import annotations

import click

import tools.cli.modules.backtest.controller as controller


class _FakeClient:
    def __init__(self, response: dict) -> None:
        self._response = response

    def group_order_flow(self, payload: dict) -> dict:
        return self._response


def _fake_state() -> object:
    from tools.cli.state import CliState

    state = CliState()
    state.page_uuid = "page-1"
    state.backtest_last_result = {"groups": [{"id": "g-a1", "name": "A1"}]}
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
