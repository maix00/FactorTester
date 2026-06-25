from __future__ import annotations

from types import SimpleNamespace
import json

import numpy as np
import pandas as pd
from flask import Flask

from server.modules.single_factor_test import group as group_routes
from server.modules.single_factor_test import sft_bp
from sources.LocalCNFutures import CNFutures as cn_futures_module
from tools.factors.tests.single_factor_test.group.result import GroupRunResult


def _minor_units(values):
    return np.rint(np.asarray(values, dtype=float) * 100.0).astype(np.int64)


def _cny_vec(count: int):
    return np.full(count, 'CNY', dtype=object)


def test_snapshot_product_display_falls_back_to_openctp_product_name(monkeypatch):
    from sources.LocalCNFutures import product_catalog
    from sources.OpenCTP import products as openctp_products

    monkeypatch.setattr(
        product_catalog,
        "load_product_catalog",
        lambda **_: pd.DataFrame(columns=["_product_name", "品种代码", "交易所代码", "合约标的", "简称", "类别"]),
    )
    monkeypatch.setattr(
        openctp_products,
        "load_products_list",
        lambda: [
            {"ExchangeID": "CZCE", "ProductID": "AP", "ProductName": "苹果", "ProductClass": "1"},
        ],
    )

    assert group_routes._snapshot_product_display("AP.CZC")["desc"] == "苹果"


def test_group_snapshot_keeps_fee_display_helpers_alive(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    product = 'SgCCS|N:2m|$F:1m|$Rev'
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 1), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True]]], dtype=bool),
        products_by_group={0: {idx: [product]}},
        valid_cols=[product],
        open_ratio_mat=np.array([0.01], dtype=float),
        close_ratio_mat=np.array([0.02], dtype=float),
        close_today_ratio_mat=np.array([0.03], dtype=float),
        index_list=[idx],
        group_names={0: '第一组'},
        hold_amounts_np=_minor_units([[[100.0]]]),
        position_quantities_np=np.array([[[1.0]]], dtype=float),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload['success'] is True
    assert payload['default_matrix_key'] == 'raw'
    assert len(payload['matrices']) == 2
    assert payload['matrices'][0]['key'] == 'raw'
    assert payload['matrices'][0]['rows'][0]['name'] == product
    assert payload['matrices'][0]['cells'][0][0]['status'] == 'entering'
    assert payload['matrices'][0]['columns'][0]['count_label'] == '持仓品种数(1)'
    assert payload['summary']['total_prod_count'] == 1


def test_group_snapshot_includes_capital_warning_when_first_period_cannot_open_positions(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 1), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True]]], dtype=bool),
        products_by_group={0: {idx: ['TEST|N:1m|$F:1m|$Rev']}},
        valid_cols=['TEST|N:1m|$F:1m|$Rev'],
        open_ratio_mat=np.array([[0.0]], dtype=float),
        open_fixed_mat=np.array([[0.0]], dtype=float),
        close_ratio_mat=np.array([[0.0]], dtype=float),
        close_fixed_mat=np.array([[0.0]], dtype=float),
        close_today_ratio_mat=np.array([[0.0]], dtype=float),
        index_list=[idx],
        group_names={0: '第一组'},
        hold_amounts_np=np.zeros((1, 1, 1), dtype=np.int64),
        position_quantities_np=np.zeros((1, 1, 1), dtype=float),
        price_np=np.array([[1000.0]], dtype=float),
        point_value_mat=np.array([[100.0]], dtype=float),
        min_trade_quantity_mat=np.array([[1.0]], dtype=float),
        margin_ratio_mat=np.array([[1.0]], dtype=float),
        is_margin_traded_vec=np.array([False], dtype=bool),
        initial_capital=1000.0,
        post_rebalance_cash_np=_minor_units([[50.0]]),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload['success'] is True
    assert payload['capital_warning']
    assert '一手资金需求' in payload['capital_warning']
    assert payload['capital_diagnostics']['blocked_group_count'] == 1
    assert payload['capital_diagnostics']['blocked_groups'][0]['cheapest_product_name'] == 'TEST|N:1m|$F:1m|$Rev'


def test_group_snapshot_reports_open_reason_from_target_before_floor(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 1), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True]]], dtype=bool),
        products_by_group={0: {idx: ['TEST|N:1m|$F:1m|$Rev']}},
        valid_cols=['TEST|N:1m|$F:1m|$Rev'],
        open_ratio_mat=np.array([0.0], dtype=float),
        open_fixed_mat=np.array([0.0], dtype=float),
        close_ratio_mat=np.array([0.0], dtype=float),
        close_fixed_mat=np.array([0.0], dtype=float),
        close_today_ratio_mat=np.array([0.0], dtype=float),
        index_list=[idx],
        group_names={0: '第一组'},
        hold_amounts_np=np.zeros((1, 1, 1), dtype=np.int64),
        target_amounts_before_floor_np=_minor_units([[[50.0]]]),
        position_quantities_np=np.zeros((1, 1, 1), dtype=float),
        price_np=np.array([[100.0]], dtype=float),
        point_value_mat=np.array([1.0], dtype=float),
        min_trade_quantity_mat=np.array([1.0], dtype=float),
        margin_ratio_mat=np.array([1.0], dtype=float),
        is_margin_traded_vec=np.array([False], dtype=bool),
        initial_capital=1000.0,
        post_rebalance_cash_np=_minor_units([[50.0]]),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    cell = payload['matrices'][0]['cells'][0][0]
    assert cell['selected'] is True
    assert '剩余现金 CNY 50.00' in (cell['open_reason'] or '')


def test_group_snapshot_uses_group_axis_not_product_axis(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    products = [f'P{i}' for i in range(8)]
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 7), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 7), dtype=float),
        gross_returns_np=np.zeros((1, 7), dtype=float),
        product_gross_contrib_np=np.zeros((1, 7, 8), dtype=float),
        product_fee_contrib_np=np.zeros((1, 7, 8), dtype=float),
        returns_np=np.zeros((1, 7), dtype=float),
        period_returns_np=np.zeros((1, 7), dtype=float),
        membership_np=np.zeros((1, 7, 8), dtype=bool),
        products_by_group={},
        valid_cols=products,
        open_ratio_mat=np.zeros(8, dtype=float),
        close_ratio_mat=np.zeros(8, dtype=float),
        close_today_ratio_mat=np.zeros(8, dtype=float),
        index_list=[idx],
        group_names={i: f'第{i + 1}组' for i in range(7)},
        hold_amounts_np=np.zeros((1, 7, 8), dtype=np.int64),
        position_quantities_np=np.zeros((1, 7, 8), dtype=float),
        product_currency_vec=_cny_vec(8),
    )
    group_result.membership_np[0, 6, 7] = True
    group_result.hold_amounts_np[0, 6, 7] = 10000
    group_result.position_quantities_np[0, 6, 7] = 1.0
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload['success'] is True
    assert len(payload['matrices'][0]['columns']) == 7
    assert payload['matrices'][0]['cells'][7][6]['status'] == 'entering'


def test_group_snapshot_response_is_strict_json_when_positions_have_nonfinite_values(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 2), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 2), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True, True]]], dtype=bool),
        products_by_group={},
        valid_cols=['P_NAN', 'P_INF'],
        open_ratio_mat=np.zeros(2, dtype=float),
        close_ratio_mat=np.zeros(2, dtype=float),
        close_today_ratio_mat=np.zeros(2, dtype=float),
        index_list=[idx],
        group_names={0: '第一组'},
        hold_amounts_np=np.array([[[0, 0]]], dtype=np.int64),
        position_quantities_np=np.array([[[np.nan, -np.inf]]], dtype=float),
        product_currency_vec=_cny_vec(2),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    raw = resp.get_data(as_text=True)
    assert 'NaN' not in raw
    assert 'Infinity' not in raw
    payload = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    assert payload['success'] is True
    assert payload['matrices'][0]['cells'][0][0]['quantity'] == 0.0
    assert payload['matrices'][0]['cells'][1][0]['amount'] == 0.0


def test_group_snapshot_rebuilds_per_product_amounts_from_quantities_and_prices(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx0 = pd.Timestamp('2026-01-01 09:30:00')
    idx1 = pd.Timestamp('2026-01-01 09:31:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((2, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((2, 1), dtype=float),
        gross_returns_np=np.zeros((2, 1), dtype=float),
        product_gross_contrib_np=np.zeros((2, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((2, 1, 1), dtype=float),
        returns_np=np.zeros((2, 1), dtype=float),
        period_returns_np=np.zeros((2, 1), dtype=float),
        membership_np=np.array([[[True]], [[True]]], dtype=bool),
        products_by_group={},
        valid_cols=['P0'],
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        index_list=[idx0, idx1],
        group_names={0: 'A1'},
        hold_amounts_np=_minor_units([[[3000.0]], [[3300.0]]]),
        position_quantities_np=np.array([[[3.0]], [[3.0]]], dtype=float),
        price_np=np.array([[100.0], [110.0]], dtype=float),
        point_value_mat=np.array([10.0], dtype=float),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx1.timestamp() * 1000),
    })

    payload = resp.get_json()
    cell = payload['matrices'][0]['cells'][0][0]
    assert cell['quantity'] == 3.0
    assert cell['amount'] == 3300.0


def test_group_snapshot_reports_position_changes_and_short_alias_headers(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx0 = pd.Timestamp('2026-01-01 09:30:00')
    idx1 = pd.Timestamp('2026-01-01 09:31:00')
    products = ['P_NEW', 'P_INC', 'P_DEC', 'P_PENDING', 'P_EXIT']
    memberships = np.array([
        [[False, True, True, True, True]],
        [[True, True, True, False, False]],
    ], dtype=bool)
    positions = np.array([
        [[0.0, 1.0, 3.0, 2.0, 1.0]],
        [[1.0, 2.0, 1.0, 1.0, 0.0]],
    ], dtype=float)
    amounts = positions * np.array([[[100.0] * len(products)], [[110.0] * len(products)]], dtype=float)
    # prev_end_amounts_np[t] is the end-of-period amount from t-1
    prev_end = np.zeros_like(amounts)
    prev_end[1:] = amounts[:-1]
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((2, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((2, 1), dtype=float),
        gross_returns_np=np.zeros((2, 1), dtype=float),
        product_gross_contrib_np=np.zeros((2, 1, len(products)), dtype=float),
        product_fee_contrib_np=np.zeros((2, 1, len(products)), dtype=float),
        returns_np=np.zeros((2, 1), dtype=float),
        period_returns_np=np.zeros((2, 1), dtype=float),
        membership_np=memberships,
        products_by_group={},
        valid_cols=products,
        open_ratio_mat=np.zeros(len(products), dtype=float),
        close_ratio_mat=np.zeros(len(products), dtype=float),
        close_today_ratio_mat=np.zeros(len(products), dtype=float),
        index_list=[idx0, idx1],
        group_names={0: 'A1'},
        hold_amounts_np=_minor_units(amounts),
        position_quantities_np=positions,
        prev_end_amounts_np=_minor_units(prev_end),
        price_np=np.array([[100.0] * len(products), [110.0] * len(products)], dtype=float),
        point_value_mat=np.ones(len(products), dtype=float),
        pre_rebalance_total_equity_np=_minor_units([[1000.0], [1250.0]]),
        post_rebalance_total_equity_np=_minor_units([[990.0], [1240.0]]),
        total_equity_np=_minor_units([[1200.0], [1300.0]]),
        pre_rebalance_cash_np=_minor_units([[1000.0], [950.0]]),
        post_rebalance_cash_np=_minor_units([[500.0], [920.0]]),
        cash_np=_minor_units([[1000.0], [900.0]]),
        buy_fee_amount_np=_minor_units([[8.0], [7.0]]),
        sell_fee_amount_np=_minor_units([[2.0], [3.0]]),
        product_currency_vec=_cny_vec(len(products)),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx1.timestamp() * 1000),
    })

    payload = resp.get_json()
    cells = payload['matrices'][0]['cells']
    assert payload['matrices'][0]['columns'][0]['label'] == 'A1'
    assert payload['matrices'][0]['rows'][0]['name'] == '总资产'
    assert cells[0][0]['status'] == 'increasing'
    assert cells[0][0]['amount'] == 1300.0
    assert cells[0][0]['pre_rebalance_amount'] == 1250.0
    assert cells[0][0]['post_rebalance_amount'] == 1240.0
    assert cells[0][0]['end_amount'] == 1300.0
    assert cells[0][0]['buy_fee_amount'] == 7.0
    assert cells[0][0]['sell_fee_amount'] == 3.0
    assert cells[0][0]['fee_amount'] == 10.0
    assert cells[0][0]['delta_amount'] == 60.0
    assert payload['matrices'][0]['rows'][1]['name'] == '现金'
    assert cells[1][0]['status'] == 'decreasing'
    assert cells[1][0]['amount'] == 900.0
    assert cells[1][0]['pre_rebalance_amount'] == 950.0
    assert cells[1][0]['post_rebalance_amount'] == 920.0
    assert cells[1][0]['end_amount'] == 900.0
    assert cells[1][0]['buy_fee_amount'] == 7.0
    assert cells[1][0]['sell_fee_amount'] == 3.0
    assert cells[1][0]['fee_amount'] == 10.0
    assert cells[1][0]['delta_amount'] == -20.0
    assert cells[2][0]['status'] == 'entering'
    assert cells[2][0]['delta_quantity'] == 1.0
    assert cells[2][0]['previous_amount'] == 0.0
    assert cells[2][0]['amount'] == 110.0
    assert cells[2][0]['delta_amount'] == 110.0
    assert cells[3][0]['status'] == 'increasing'
    assert cells[3][0]['delta_quantity'] == 1.0
    assert cells[3][0]['previous_amount'] == 100.0
    assert cells[3][0]['amount'] == 220.0
    assert cells[3][0]['delta_amount'] == 120.0
    assert cells[4][0]['status'] == 'decreasing'
    assert cells[4][0]['delta_quantity'] == -2.0
    assert cells[4][0]['previous_amount'] == 300.0
    assert cells[4][0]['amount'] == 110.0
    assert cells[4][0]['delta_amount'] == -190.0
    assert cells[5][0]['status'] == 'pending_exit'
    assert cells[5][0]['quantity'] == 1.0
    assert cells[5][0]['delta_quantity'] == -1.0
    assert cells[5][0]['previous_amount'] == 200.0
    assert cells[5][0]['amount'] == 110.0
    assert cells[5][0]['delta_amount'] == -90.0
    assert cells[6][0]['status'] == 'exiting'
    assert cells[6][0]['delta_quantity'] == -1.0
    assert cells[6][0]['previous_amount'] == 100.0
    assert cells[6][0]['amount'] == 0.0
    assert cells[6][0]['delta_amount'] == -100.0


def test_group_snapshot_collapses_registered_cn_futures_contract_uid(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    cn_futures_module.CNFutures('SM.CZC')
    monkeypatch.setattr(
        cn_futures_module,
        '_cn_futures_contract_maps',
        lambda path=None: ({'CZCE|F|SM|2605': 'SM.CZC'}, {'SM.CZC': ['CZCE|F|SM|2605']}),
    )
    idx = pd.Timestamp('2026-01-01 09:30:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 1), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True]]], dtype=bool),
        products_by_group={},
        valid_cols=['CZCE|F|SM|2605'],
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        index_list=[idx],
        group_names={0: 'A1'},
        hold_amounts_np=_minor_units([[[100.0]]]),
        position_quantities_np=np.array([[[1.0]]], dtype=float),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    collapsed = next(matrix for matrix in payload['matrices'] if matrix['key'] == 'collapsed')
    assert collapsed['rows'][0]['name'] == 'SM.CZC'


def test_group_snapshot_rebuilds_zero_hold_amounts_from_simulated_positions(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx = pd.Timestamp('2026-01-01 09:30:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((1, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((1, 1), dtype=float),
        gross_returns_np=np.zeros((1, 1), dtype=float),
        product_gross_contrib_np=np.zeros((1, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((1, 1, 1), dtype=float),
        returns_np=np.zeros((1, 1), dtype=float),
        period_returns_np=np.zeros((1, 1), dtype=float),
        membership_np=np.array([[[True]]], dtype=bool),
        products_by_group={},
        valid_cols=['P0'],
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        index_list=[idx],
        group_names={0: 'A1'},
        hold_amounts_np=_minor_units([[[3000.0]]]),
        position_quantities_np=np.array([[[3.0]]], dtype=float),
        price_np=np.array([[100.0]], dtype=float),
        point_value_mat=np.array([10.0], dtype=float),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    assert payload['matrices'][0]['cells'][0][0]['amount'] == 3000.0


def test_group_snapshot_reports_neighbor_change_timestamps(monkeypatch):
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(sft_bp)

    idx0 = pd.Timestamp('2026-01-01 09:30:00')
    idx1 = pd.Timestamp('2026-01-01 09:31:00')
    idx2 = pd.Timestamp('2026-01-01 09:32:00')
    group_result = GroupRunResult(
        fee_costs_np=np.zeros((3, 1), dtype=float),
        trade_notional_ratio_np=np.zeros((3, 1), dtype=float),
        gross_returns_np=np.zeros((3, 1), dtype=float),
        product_gross_contrib_np=np.zeros((3, 1, 1), dtype=float),
        product_fee_contrib_np=np.zeros((3, 1, 1), dtype=float),
        returns_np=np.zeros((3, 1), dtype=float),
        period_returns_np=np.zeros((3, 1), dtype=float),
        membership_np=np.array([[[True]], [[True]], [[False]]], dtype=bool),
        products_by_group={},
        valid_cols=['P0'],
        open_ratio_mat=np.zeros(1, dtype=float),
        close_ratio_mat=np.zeros(1, dtype=float),
        close_today_ratio_mat=np.zeros(1, dtype=float),
        index_list=[idx0, idx1, idx2],
        group_names={0: 'A1'},
        hold_amounts_np=_minor_units([[[100.0]], [[100.0]], [[0.0]]]),
        position_quantities_np=np.array([[[1.0]], [[1.0]], [[0.0]]], dtype=float),
        product_currency_vec=_cny_vec(1),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_page_object', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'product_path_selection_id': 'sub-1',
        'timestamp_ms': group_routes.to_epoch_ms(idx1, 'Asia/Shanghai'),
    })

    payload = resp.get_json()
    assert payload['has_prev_change'] is False
    assert payload['has_next_change'] is True
    assert payload['next_change_timestamp_ms'] == group_routes.to_epoch_ms(idx2, 'Asia/Shanghai')
    assert payload['display_timezone'] == 'Asia/Shanghai'
