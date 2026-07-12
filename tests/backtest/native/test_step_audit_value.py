from dataclasses import dataclass

from tools.testers.backtest.engines.native.scheduler import _audit_value


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
