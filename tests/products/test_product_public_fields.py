from __future__ import annotations

import pandas as pd

from server.modules.shared import price_services
from sources.LocalCNFutures import FeeData
from tools.products.Futures import Futures, FuturesContract


def _fee_frame() -> pd.DataFrame:
    return pd.DataFrame([{
        'date': '20260602',
        'variety_code': 'IF',
        'multiplier': 300,
        'min_tick': 0.2,
        'open_ratio': 0.0001,
        'open_fixed': 1.0,
        'close_ratio': 0.0002,
        'close_fixed': 2.0,
        'closetoday_ratio': 0.0003,
        'closetoday_fixed': 3.0,
        'long_margin_ratio': 0.12,
        'long_margin_fixed': 12000,
        'short_margin_ratio': 0.13,
        'short_margin_fixed': 13000,
    }])


def test_product_public_fields_reflect_backend_attrs_and_futures_specs(monkeypatch):
    monkeypatch.setattr(FeeData, 'load_latest', _fee_frame)
    future = Futures('IF.CFE', _local_only=True)
    future.desc = '沪深300'

    fields = price_services.product_public_fields(future)

    assert fields['class'] == 'Futures'
    assert fields['name'] == 'IF.CFE'
    assert fields['is_margin_traded'] is True
    assert fields['open_fee_ratio'] == 0.0001
    assert fields['long_margin_ratio'] == 0.12
    assert fields['point_value'] == 300
    assert fields['trading_spec_source'] == 'current_variety_snapshot'


def test_contract_public_fields_fall_back_to_variety_specs(monkeypatch):
    monkeypatch.setattr(FeeData, 'load_latest', _fee_frame)
    monkeypatch.setattr(FeeData, 'get_contract_fee_row', lambda *args, **kwargs: None)
    contract = FuturesContract('CFE|F|IF|2606', _local_only=True)

    fields = price_services.product_public_fields(contract)

    assert fields['class'] == 'FuturesContract'
    assert fields['is_margin_traded'] is True
    assert fields['close_today_fee_ratio'] == 0.0003
    assert fields['short_margin_fixed'] == 13000
    assert fields['trading_spec_source'] == 'current_variety_snapshot_fallback'
