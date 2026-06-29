"""FactorModule — declares the `factor` field every strategy's signal
generation reads from. Field declaration only; FactorSignalModule (this
package's factor_signal.py) owns the Flows that actually use it."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef


class FactorModule(ExecutableModule):
    key: ClassVar[str] = "factor"
    label: ClassVar[str] = "因子"

    factor: ClassVar[FieldRef[Any]] = FieldRef("factor")  # a FactorExpr (tools.factors.expr.core.FactorExpr)

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "factor": FieldDefinition(public=True, control_template="custom", tab="factor"),
    }
