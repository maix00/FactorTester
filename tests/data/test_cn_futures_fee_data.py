from __future__ import annotations

from pathlib import Path

import pandas as pd

from sources.LocalCNFutures import FeeData


def _raw_fee_table() -> pd.DataFrame:
    rows = [
        ['DCE', 'A2605', '豆一2605', 'A', '豆一', 10, 1, 0.0001, 1.0, 0.0002, 2.0, 0.0003, 3.0, 0.12, 1200, 0.13, 1300, 0, 0, 0, 100, 1000],
        ['DCE', 'A2609', '豆一2609', 'A', '豆一', 10, 1, 0.0004, 4.0, 0.0005, 5.0, 0.0006, 6.0, 0.14, 1400, 0.15, 1500, 0, 0, 0, 100, 2000],
    ]
    return pd.DataFrame(rows)


def test_parse_contract_rows_keeps_contract_level_margin_specs():
    rows = FeeData._parse_contract_rows(_raw_fee_table())

    assert rows['contract_code'].tolist() == ['A2605', 'A2609']
    assert rows['contract_key'].tolist() == ['A2605', 'A2609']
    assert rows.loc[0, 'long_margin_ratio'] == 0.12
    assert rows.loc[0, 'short_margin_fixed'] == 1300


def test_parse_variety_rows_records_representative_contract_only_for_display():
    rows = FeeData._parse_raw(_raw_fee_table())

    assert rows.shape[0] == 1
    assert rows.loc[0, 'variety_code'] == 'A'
    assert rows.loc[0, 'representative_contract_code'] == 'A2609'
    assert 'open_interest' not in rows.columns


def test_main_contract_fee_lookup_uses_futures_roller_row(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(FeeData, '_DATA_DIR', tmp_path)
    monkeypatch.setattr(FeeData, '_CONTRACT_LATEST_PATH', tmp_path / 'fees_contracts_latest.parquet')

    rows = FeeData._parse_contract_rows(_raw_fee_table())
    rows['date'] = '20260602'
    rows.to_parquet(tmp_path / 'fees_contracts_20260602.parquet', index=False)

    class _Future:
        def get_contract_row_from_trading_day(self, trading_day):
            return pd.Series({'CONTRACT': 'A2605.DCE'})

    row = FeeData.get_main_contract_fee_row(_Future(), '2026-06-02')

    assert row is not None
    assert row['contract_code'] == 'A2605'
    assert row['open_ratio'] == 0.0001
