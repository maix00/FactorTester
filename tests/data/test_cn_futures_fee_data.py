from __future__ import annotations

from pathlib import Path

import pandas as pd

from sources.LocalCNFutures import FeeData
from sources.OpenCTP import client as openctp_client


def _raw_fee_table() -> pd.DataFrame:
    rows = [
        ['DCE', 'A2605', '豆一2605', 'A', '豆一', 10, 1, 0.0001, 1.0, 0.0002, 2.0, 0.0003, 3.0, 0.12, 1200, 0.13, 1300, 0, 0, 0, 100, 1000],
        ['DCE', 'A2609', '豆一2609', 'A', '豆一', 10, 1, 0.0004, 4.0, 0.0005, 5.0, 0.0006, 6.0, 0.14, 1400, 0.15, 1500, 0, 0, 0, 100, 2000],
    ]
    return pd.DataFrame(rows)


def _isolate_fee_sql(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(FeeData, '_DATA_DIR', tmp_path)
    monkeypatch.setattr(openctp_client, 'CACHE_DIR', tmp_path / 'localdata')
    monkeypatch.setattr(openctp_client, 'CACHE_DB_PATH', tmp_path / 'localdata' / 'onlinedata.sqlite')


def test_parse_contract_rows_keeps_contract_level_margin_specs():
    rows = FeeData._parse_contract_rows(_raw_fee_table())

    assert rows['contract_code'].tolist() == ['A2605', 'A2609']
    assert rows['NormalizedInstrumentID'].tolist() == ['A2605', 'A2609']
    assert rows.loc[0, 'long_margin_ratio'] == 0.12
    assert rows.loc[0, 'short_margin_fixed'] == 1300


def test_parse_variety_rows_records_representative_contract_only_for_display():
    rows = FeeData._parse_raw(_raw_fee_table())

    assert rows.shape[0] == 1
    assert rows.loc[0, 'variety_code'] == 'A'
    assert rows.loc[0, 'representative_contract_code'] == 'A2609'
    assert 'open_interest' not in rows.columns


def test_main_contract_fee_lookup_uses_futures_roller_row(tmp_path: Path, monkeypatch):
    _isolate_fee_sql(monkeypatch, tmp_path)

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


def test_contract_fee_snapshot_uses_asof_forward_fill(tmp_path: Path, monkeypatch):
    _isolate_fee_sql(monkeypatch, tmp_path)

    rows = FeeData._parse_contract_rows(_raw_fee_table())
    old_rows = rows.copy()
    old_rows['date'] = '20260601'
    old_rows['open_ratio'] = 0.001
    old_rows.to_parquet(tmp_path / 'fees_contracts_20260601.parquet', index=False)
    new_rows = rows.copy()
    new_rows['date'] = '20260603'
    new_rows['open_ratio'] = 0.003
    new_rows.to_parquet(tmp_path / 'fees_contracts_20260603.parquet', index=False)

    loaded = FeeData.load_contract_rows_for_date('2026-06-02')

    assert loaded.attrs['fee_source'] == 'historical_forward_fill'
    assert loaded.attrs['fee_source_date'] == '20260601'
    assert loaded.attrs['requested_fee_date'] == '20260602'
    assert loaded.loc[0, 'open_ratio'] == 0.001


def test_contract_fee_snapshot_before_first_uses_latest_inferred(tmp_path: Path, monkeypatch):
    _isolate_fee_sql(monkeypatch, tmp_path)

    rows = FeeData._parse_contract_rows(_raw_fee_table())
    rows['date'] = '20260603'
    rows.to_parquet(tmp_path / 'fees_contracts_20260603.parquet', index=False)

    loaded = FeeData.load_contract_rows_for_date('2026-06-01')

    assert loaded.attrs['fee_source'] == 'latest_inferred'
    assert loaded.attrs['fee_source_date'] == '20260603'
    assert loaded.attrs['requested_fee_date'] == '20260601'
