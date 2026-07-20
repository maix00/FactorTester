from __future__ import annotations

from sources.FieldHistory.scripts.audit_transaction_fee_announcement_alignment import (
    _active_fee_unit_field_before,
    _is_zero_unit_companion_aligned,
    _snapshot_index,
)


def _event(**overrides):
    base = {
        "data_source": "CZCE",
        "instrument": "X",
        "contract_codes": [],
        "contract_scope_type": "all",
        "effective_trading_day": "2024-01-02",
        "effective_timestamp": "",
        "value": 0.0,
    }
    base.update(overrides)
    return base


def test_fee_unit_companion_uses_latest_active_unit_before_snapshot() -> None:
    notices = [
        _event(
            field_name="CloseTodayRatioByVolume",
            effective_trading_day="2020-01-01",
            value=2.0,
            source_notice_id="listing-fixed-fee",
        ),
        _event(
            field_name="CloseTodayRatioByMoney",
            effective_trading_day="2023-01-01",
            value=0.0001,
            source_notice_id="switch-to-money",
        ),
    ]
    snapshot_money = _event(
        field_name="CloseTodayRatioByMoney",
        effective_trading_day="2024-01-02",
        value=0.0,
        source_notice_id="CZCE-settlement-parameters-20240102",
    )
    snapshot_volume = _event(
        field_name="CloseTodayRatioByVolume",
        effective_trading_day="2024-01-02",
        value=0.0,
        source_notice_id="CZCE-settlement-parameters-20240102",
    )

    snapshots = [snapshot_money, snapshot_volume]
    index = _snapshot_index(snapshots)

    assert _active_fee_unit_field_before(snapshot_volume, notices) == "CloseTodayRatioByMoney"
    assert _is_zero_unit_companion_aligned(snapshot_volume, notices, snapshot_index=index) is True
    assert _is_zero_unit_companion_aligned(snapshot_money, notices, snapshot_index=index) is False

