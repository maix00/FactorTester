"""FactorExpr bridge for Qlib BaseStrategy.generate_trade_decision."""

from __future__ import annotations

import pandas as pd

from ...factors.events import FactorSignal
from ..factor_step import FactorStepAdapter
from ..frameworks import IncrementalFactorSource, PrecomputedFactorSource


_FIELDS = {
    "OPEN": "$open",
    "HIGH": "$high",
    "LOW": "$low",
    "CLOSE": "$close",
    "VOLUME": "$volume",
}


class QlibFactorAdapter:
    """Read Exchange quote fields during generate_trade_decision."""

    def __init__(
        self,
        factor_alias: str,
        factor_source: PrecomputedFactorSource | IncrementalFactorSource,
        instruments: tuple[str, ...],
    ) -> None:
        self.stepper = FactorStepAdapter(factor_alias, factor_source, instruments)
        unsupported = self.stepper.required_columns - _FIELDS.keys()
        if unsupported:
            raise ValueError(f"Qlib factor columns are unsupported: {sorted(unsupported)}")

    def on_generate_trade_decision(
        self,
        exchange: object,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp | None = None,
    ) -> FactorSignal:
        end_time = start_time if end_time is None else end_time
        fields = {
            instrument: {
                column: float(exchange.get_quote_info(
                    instrument,
                    start_time,
                    end_time,
                    field=_FIELDS[column],
                ))
                for column in self.stepper.required_columns
            }
            for instrument in self.stepper.instruments
        }
        return self.stepper.update(start_time, fields)
