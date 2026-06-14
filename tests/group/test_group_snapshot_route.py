from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from flask import Flask

from server.modules.single_factor_test import group as group_routes
from server.modules.single_factor_test import sft_bp
from tools.factors.tests.single_factor_test.group.result import GroupRunResult


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
        open_ratio_vec=np.array([0.01], dtype=float),
        close_ratio_vec=np.array([0.02], dtype=float),
        close_today_ratio_vec=np.array([0.03], dtype=float),
        index_list=[idx],
        group_names={0: '第一组'},
        hold_amounts_np=np.array([[[100.0]]], dtype=float),
        position_quantities_np=np.array([[[1.0]]], dtype=float),
    )
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_factor_tester', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'submission_id': 'sub-1',
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
    assert payload['summary']['total_prod_count'] == 1


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
        open_ratio_vec=np.zeros(8, dtype=float),
        close_ratio_vec=np.zeros(8, dtype=float),
        close_today_ratio_vec=np.zeros(8, dtype=float),
        index_list=[idx],
        group_names={i: f'第{i + 1}组' for i in range(7)},
        hold_amounts_np=np.zeros((1, 7, 8), dtype=float),
        position_quantities_np=np.zeros((1, 7, 8), dtype=float),
    )
    group_result.membership_np[0, 6, 7] = True
    group_result.hold_amounts_np[0, 6, 7] = 100.0
    group_result.position_quantities_np[0, 6, 7] = 1.0
    tester = SimpleNamespace(results={'group': SimpleNamespace(group_result=group_result)}, last_group_factor='group')

    monkeypatch.setattr(group_routes.runtime_state, 'get_factor_tester', lambda *args, **kwargs: tester)

    client = app.test_client()
    resp = client.post('/get_group_snapshot', json={
        'submission_id': 'sub-1',
        'timestamp_ms': int(idx.timestamp() * 1000),
    })

    payload = resp.get_json()
    assert resp.status_code == 200
    assert payload['success'] is True
    assert len(payload['matrices'][0]['columns']) == 7
    assert payload['matrices'][0]['cells'][7][6]['status'] == 'entering'
