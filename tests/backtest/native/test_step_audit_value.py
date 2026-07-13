from dataclasses import dataclass

import pandas as pd

from tools.data.field_history import TimestampTradingDayResolver
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.scheduler import (
    _audit_contract_metadata_value,
    _audit_price_tables_value,
    _audit_ledger_changes,
    _audit_ledger_topology,
    _audit_value,
)
from tools.testers.backtest.modules.target import TargetWeightIntent


@dataclass
class _AuditRecord:
    amount: int


class _FalseDataclassMarker:
    __dataclass_fields__ = None


def test_step_audit_serializes_dataclass_instance_without_treating_class_as_instance() -> None:
    assert _audit_value(_AuditRecord(3)) == {"amount": 3}
    serialized_class = _audit_value(_AuditRecord)
    assert serialized_class["type"] == "type"
    assert serialized_class["repr"].endswith("._AuditRecord'>")
    assert _audit_value(_FalseDataclassMarker())["type"] == "_FalseDataclassMarker"


def test_step_audit_serializes_event_draft_as_compact_record() -> None:
    draft = EventDraft(
        EventKind.LEDGER,
        pd.Timestamp("2026-01-01 15:00:00"),
        payload={"kind": "margin_check", "ledger_id": "private:L1", "extra": {"x": 1}},
        ledger="private:L1",
    )

    assert _audit_value(draft) == {
        "type": "EventDraft",
        "kind": "ledger",
        "timestamp": "2026-01-01 15:00:00",
        "strategy": "",
        "ledger": "private:L1",
        "payload": {"kind": "margin_check", "ledger_id": "private:L1", "extra": {"x": 1}},
        "index_key": None,
    }


def test_step_audit_serializes_target_weight_intent_as_typed_payload() -> None:
    intent = TargetWeightIntent({"RB.SHF": 1.0}, reason="unit_test")

    assert _audit_value(intent) == {
        "type": "TargetWeightIntent",
        "reason": "unit_test",
        "weights": {"RB.SHF": 1.0},
    }


def test_step_audit_serializes_trading_day_resolver_as_summary() -> None:
    resolver = TimestampTradingDayResolver({
        pd.Timestamp("2026-01-05 09:01:00"): pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-05 09:02:00"): pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06 09:01:00"): pd.Timestamp("2026-01-06"),
    })

    serialized = _audit_value(resolver)

    assert serialized["type"] == "TimestampTradingDayResolver"
    assert serialized["purpose"] == "timestamp -> trading_day"
    assert serialized["mapping_count"] == 3
    assert serialized["trading_days"] == {"count": 2, "start": "2026-01-05", "end": "2026-01-06"}
    assert "sample" in serialized
    assert "repr" not in serialized


def test_step_audit_keeps_small_dataframes_complete() -> None:
    frame = pd.DataFrame(
        {"RB.SHF": [1.0, 2.0], "AG.SHF": [3.0, 4.0]},
        index=pd.to_datetime(["2026-01-01 09:00:00", "2026-01-01 09:01:00"]),
    )

    assert _audit_value(frame) == {
        "type": "DataFrame",
        "columns": ["RB.SHF", "AG.SHF"],
        "index": ["2026-01-01 09:00:00", "2026-01-01 09:01:00"],
        "rows": [[1.0, 3.0], [2.0, 4.0]],
    }


def test_step_audit_summarizes_large_dataframes_as_dataframe_samples() -> None:
    index = pd.date_range("2026-01-01 09:00:00", periods=25, freq="min")
    frame = pd.DataFrame(
        {
            "RB.SHF": range(25),
            "AG.SHF": range(100, 125),
        },
        index=index,
    )

    serialized = _audit_value(frame)

    assert serialized["type"] == "DataFrame"
    assert serialized["shape"] == [25, 2]
    assert serialized["columns"] == ["RB.SHF", "AG.SHF"]
    assert serialized["index"] == {
        "start": "2026-01-01 09:00:00",
        "end": "2026-01-01 09:24:00",
    }
    assert serialized["truncated"] is True
    assert serialized["sample"]["head"] == {
        "columns": ["RB.SHF", "AG.SHF"],
        "index": [
            "2026-01-01 09:00:00",
            "2026-01-01 09:01:00",
            "2026-01-01 09:02:00",
        ],
        "rows": [[0, 100], [1, 101], [2, 102]],
    }
    assert serialized["sample"]["tail"] == {
        "columns": ["RB.SHF", "AG.SHF"],
        "index": [
            "2026-01-01 09:22:00",
            "2026-01-01 09:23:00",
            "2026-01-01 09:24:00",
        ],
        "rows": [[22, 122], [23, 123], [24, 124]],
    }
    assert "rows" not in serialized


def test_step_audit_summarizes_wide_dataframes_without_all_columns() -> None:
    index = pd.date_range("2026-01-01 09:00:00", periods=25, freq="min")
    frame = pd.DataFrame(
        {f"C{column}": [column] * 25 for column in range(30)},
        index=index,
    )

    serialized = _audit_value(frame)

    assert serialized["type"] == "DataFrame"
    assert serialized["shape"] == [25, 30]
    assert serialized["columns"] == {
        "count": 30,
        "sampled": ["C0", "C1", "C2", "C3", "C4", "C25", "C26", "C27", "C28", "C29"],
        "sample_truncated": True,
    }
    assert serialized["sample"]["head"]["columns"] == [
        "C0",
        "C1",
        "C2",
        "C3",
        "C4",
        "C25",
        "C26",
        "C27",
        "C28",
        "C29",
    ]
    assert serialized["sample"]["head"]["rows"][0] == [0, 1, 2, 3, 4, 25, 26, 27, 28, 29]


def test_step_audit_summarizes_large_series_with_head_tail_samples() -> None:
    series = pd.Series(range(25), index=pd.date_range("2026-01-01", periods=25, freq="D"), name="close")

    serialized = _audit_value(series)

    assert serialized["type"] == "Series"
    assert serialized["name"] == "close"
    assert serialized["length"] == 25
    assert serialized["index"] == {
        "start": "2026-01-01 00:00:00",
        "end": "2026-01-25 00:00:00",
    }
    assert serialized["truncated"] is True
    assert serialized["sample"]["head"]["values"] == [0, 1, 2]
    assert serialized["sample"]["tail"]["values"] == [22, 23, 24]


def test_step_audit_summarizes_long_mapping_lists() -> None:
    values = [{"contract": f"C{index}", "price": index} for index in range(10)]

    serialized = _audit_value(values)

    assert serialized == {
        "type": "list",
        "length": 10,
        "sample": {
            "head": [
                {"contract": "C0", "price": 0},
                {"contract": "C1", "price": 1},
                {"contract": "C2", "price": 2},
            ],
            "tail": [
                {"contract": "C7", "price": 7},
                {"contract": "C8", "price": 8},
                {"contract": "C9", "price": 9},
            ],
        },
        "truncated": True,
    }


def test_step_audit_keeps_moderate_scalar_lists_complete() -> None:
    assert _audit_value([f"P{index}" for index in range(23)]) == [f"P{index}" for index in range(23)]


def test_step_audit_contract_metadata_keeps_every_contract_as_compact_rows() -> None:
    metadata = [
        {
            "product": "AP.CZC",
            "contract": "AP605.CZC",
            "start": "2025-12-03",
            "end": "2026-04-10",
            "uid": "CZCE|F|AP|2605",
            "extra_field": "not printed",
        },
        {
            "product": "EC.INE",
            "contract_product": "INE|F|EC|2602",
            "start": "2025-11-13",
            "end": "2026-01-09",
            "delivery_date": "2026-02-23",
        },
        {
            "product": "EC.INE",
            "uid": "INE|F|EC|2604",
            "start": "2026-01-12",
            "end": "2026-03-27",
        },
    ]

    assert _audit_contract_metadata_value(metadata) == {
        "type": "ContractMetadataTable",
        "columns": ["product", "contract", "start", "end"],
        "rows": [
            {"product": "AP.CZC", "contract": "AP605.CZC", "start": "2025-12-03", "end": "2026-04-10"},
            {"product": "EC.INE", "contract": "INE|F|EC|2602", "start": "2025-11-13", "end": "2026-01-09"},
            {"product": "EC.INE", "contract": "INE|F|EC|2604", "start": "2026-01-12", "end": "2026-03-27"},
        ],
    }


def test_step_audit_price_tables_summarizes_basis_tables_with_bounded_sample() -> None:
    index = pd.date_range("2026-01-01 09:00:00", periods=25, freq="min")
    close = pd.DataFrame({"RB.SHF": range(25), "AG.SHF": range(100, 125)}, index=index)
    open_ = close + 0.5

    serialized = _audit_price_tables_value({"close": close, "open": open_})

    assert serialized["type"] == "PriceTablesSummary"
    assert serialized["columns"] == ["basis", "shape", "index", "columns"]
    assert len(serialized["rows"]) == 2
    assert serialized["rows"][0]["basis"] == "close"
    assert serialized["rows"][0]["shape"] == [25, 2]
    assert serialized["rows"][0]["index"] == {"start": "2026-01-01 09:00:00", "end": "2026-01-01 09:24:00"}
    assert serialized["rows"][0]["columns"] == ["RB.SHF", "AG.SHF"]
    assert serialized["rows"][0]["sample"]["head"]["rows"] == [[0, 100], [1, 101]]
    assert serialized["rows"][0]["sample"]["tail"]["rows"] == [[23, 123], [24, 124]]
    assert serialized["rows"][1]["basis"] == "open"
    assert serialized["rows"][1]["sample"]["head"]["rows"] == [[0.5, 100.5], [1.5, 101.5]]


def test_step_ledger_topology_omits_unrelated_full_state_but_keeps_identity_and_cash() -> None:
    assert _audit_ledger_topology([{
        "ledger": "L1",
        "strategies": ["A1"],
        "cash_pool": "P1",
        "cash": 123.0,
        "fields": {"Ledger.positions": {"RB": {"quantity": 0}}},
        "ledger_config": {"fee_mode": "auto"},
    }]) == [{
        "ledger": "L1",
        "strategies": ["A1"],
        "cash_pool": "P1",
        "cash": 123.0,
    }]


def test_step_ledger_changes_are_explicitly_ledger_scoped() -> None:
    before = [{
        "ledger": "L1",
        "strategies": ["A1"],
        "cash_pool": "P1",
        "cash": 100.0,
        "fields": {"LedgerModule.positions": {"RB": {"quantity": 0}}},
    }]
    after = [{
        "ledger": "L1",
        "strategies": ["A1"],
        "cash_pool": "P1",
        "cash": 90.0,
        "fields": {"LedgerModule.positions": {"RB": {"quantity": 1}}},
    }]

    changes = _audit_ledger_changes(before, after)

    assert len(changes) == 2
    assert all(change["scope"] == "ledger" for change in changes)
    assert all(change["ledger"] == "L1" for change in changes)
    assert all(change["cash_pool"] == "P1" for change in changes)
    assert all(change["strategies"] == ["A1"] for change in changes)
