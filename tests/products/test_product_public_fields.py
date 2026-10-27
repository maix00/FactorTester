from __future__ import annotations

import pandas as pd

from server.modules.shared import price_services
from sources.LocalCNFutures import FeeData
from sources.LocalCNFutures.CNFutures import CNFutures, CNFuturesContract


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
        'min_trade_quantity': 1,
        'max_trade_quantity': 20,
    }])


def test_product_public_fields_reflect_backend_attrs_and_futures_specs(monkeypatch):
    monkeypatch.setattr(FeeData, 'load_latest', _fee_frame)
    future = CNFutures('IF.CFE')
    future.desc = '沪深300'

    fields = price_services.product_public_fields(future)

    def v(key):
        return fields[key]['value']

    assert fields['class'] == {'value': 'CNFutures', 'type': 'str'}
    assert v('name') == 'IF.CFE'
    assert v('is_margin_traded') is True
    assert v('open_fee_ratio') == '0.0001'
    assert v('long_margin_ratio') == '0.12'
    assert v('multiplier') == '300'
    assert v('trading_spec_source') == 'current_variety_snapshot'
    assert fields['MoneyCalculationPolicy']['value'] == 'aggregate'
    assert fields['MoneyCalculationPolicy']['label'] == '金额计算口径'
    assert fields['MoneyCalculationPolicy']['source'] == '中国期货交易所默认清算规则'
    assert '历史字段' in fields['MoneyCalculationPolicy']['source_note']
    assert fields['CostBasisMethod']['value'] == 'DailyMarkToMarket'
    assert fields['CostBasisMethod']['label'] == '成本法'
    assert '逐日盯市' in fields['CostBasisMethod']['note']


def test_contract_public_fields_fall_back_to_variety_specs(monkeypatch):
    monkeypatch.setattr(FeeData, 'load_latest', _fee_frame)
    monkeypatch.setattr(FeeData, 'get_contract_fee_row', lambda *args, **kwargs: None)
    contract = CNFuturesContract('CFE|F|IF|2606')

    fields = price_services.product_public_fields(contract)

    def v(key):
        return fields[key]['value']

    assert fields['class'] == {'value': 'CNFuturesContract', 'type': 'str'}
    assert v('is_margin_traded') is True
    assert v('close_today_fee_ratio') == '0.0003'
    assert v('short_margin_fixed') == '13000'
    assert v('trading_spec_source') == 'current_variety_snapshot_fallback'


def test_bundle_unified_margin_fields_are_shared_by_platform_and_execution(monkeypatch):
    from sources.LocalCNFutures.instrument_fields import instrument_fields
    def frame():
        values = _fee_frame()
        values.loc[0, 'short_margin_ratio'] = 0.12
        values.loc[0, 'long_margin_fixed'] = 0
        values.loc[0, 'short_margin_fixed'] = 0
        return values
    monkeypatch.setattr(FeeData, 'load_latest', frame)
    product = CNFutures('IF.CFE')
    native = instrument_fields(product)
    shown = price_services.product_public_fields(product)
    for key in ('price_increment', 'multiplier', 'margin_init', 'margin_maint',
                'min_quantity', 'max_quantity'):
        assert shown[key]['value'] == str(native[key])
    assert str(native['margin_init']) == str(native['margin_maint']) == '0.12'
    assert str(native['price_increment']) == '0.2'
    assert 'min_tick' not in native and 'point_value' not in native


def test_platform_displays_another_bundle_fields_without_cn_interpretation():
    class OtherBundleProduct:
        name = 'Example'
        def get_instrument_fields(self):
            return {'margin_init': '0.10', 'margin_maint': '0.075',
                    'price_increment': '0.0001', 'multiplier': '5'}
    fields = price_services.product_public_fields(OtherBundleProduct())
    assert fields['margin_init']['value'] == '0.10'
    assert fields['margin_maint']['value'] == '0.075'
    assert fields['price_increment']['value'] == '0.0001'
