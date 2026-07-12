from dataclasses import dataclass

from tools.testers.backtest.engines.native.scheduler import (
    _audit_ledger_changes,
    _audit_ledger_topology,
    _audit_value,
)


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
