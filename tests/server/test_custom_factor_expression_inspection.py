from server.modules.custom_factors.expression_inspection import (
    fixed_column_refs,
)
from tools.factors.FactorExpr import CLOSE, HIGH, LOW


def test_fixed_column_refs_preserve_first_expression_appearance() -> None:
    expr = (2 * CLOSE - HIGH - LOW) / (HIGH - LOW + 1e-10)

    assert fixed_column_refs(expr) == ["CA", "HA", "LA"]


def test_fixed_column_refs_do_not_report_parameter_references() -> None:
    from tools.parameters import FactorParam

    price = FactorParam("P", default_value="CA")
    expr = (2 * price - HIGH - LOW) / (HIGH - LOW + 1e-10)

    assert fixed_column_refs(expr) == ["HA", "LA"]
