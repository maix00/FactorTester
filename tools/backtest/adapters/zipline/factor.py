"""FactorExpr bridge for Zipline handle_data callbacks."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from ...factors.events import FactorSignal
from ..factor_step import FactorStepAdapter
from ..frameworks import IncrementalFactorSource, PrecomputedFactorSource


_FIELDS = {
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "VOLUME": "volume",
}


class ZiplineFactorAdapter:
    """Read Zipline BarData.current values and execute a factor source."""

    def __init__(
        self,
        factor_alias: str,
        factor_source: PrecomputedFactorSource | IncrementalFactorSource,
        instruments: tuple[str, ...],
    ) -> None:
        self.stepper = FactorStepAdapter(factor_alias, factor_source, instruments)
        unsupported = self.stepper.required_columns - _FIELDS.keys()
        if unsupported:
            raise ValueError(f"Zipline factor columns are unsupported: {sorted(unsupported)}")

    def on_handle_data(
        self,
        timestamp: pd.Timestamp,
        data: object,
        assets: Mapping[str, object],
    ) -> FactorSignal:
        if set(assets) != set(self.stepper.instruments):
            raise ValueError("Zipline assets do not match factor instruments")
        fields = {
            instrument: {
                column: float(data.current(asset, _FIELDS[column]))
                for column in self.stepper.required_columns
            }
            for instrument, asset in assets.items()
        }
        return self.stepper.update(timestamp, fields)
