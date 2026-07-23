"""Minimal Flow-like context for sequential precompute replay."""

from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import FactorSignalModule
from tools.testers.backtest.modules.market_data import MarketDataModule


class TargetPrecomputeContext:
    def __init__(
        self, *, timestamp, prices: dict, historical_fields: dict,
        strategy_fields: dict, factor_values: dict, role_values: dict,
    ) -> None:
        self.timestamp = timestamp
        self._values = {
            MarketDataModule.current_prices: prices,
            MarketDataModule.current_historical_fields: historical_fields,
        }
        self._strategy_fields = strategy_fields
        self._factor_values = factor_values
        self._role_values = role_values

    def get(self, ref, default=None):
        return self._values.get(ref, default)

    def get_for(self, ref, strategy, default=None):
        if ref is MarketDataModule.current_historical_fields:
            return self._strategy_fields.get(strategy, default)
        if ref is FactorSignalModule.signal_value:
            return self._factor_values.get(strategy, default)
        if ref is FactorModule.factor_role_values:
            return self._role_values.get(strategy, default)
        return default
