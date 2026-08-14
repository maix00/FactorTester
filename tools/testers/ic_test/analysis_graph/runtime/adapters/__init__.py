"""Built-in execution adapters for registered IC auxiliary analyses."""

from ..contracts import ICAnalysisRuntimeAdapter
from .autocorrelation import ICAutocorrelationAdapter
from .half_life import ICForwardHorizonHalfLifeAdapter
from .periods import ICPeriodDiagnosticsAdapter
from .quantile import ICQuantilePortfolioStatisticsAdapter
from .resample import ICResampleStabilityAdapter
from .rolling import ICRollingStabilityAdapter


def builtin_runtime_adapters() -> dict[str, ICAnalysisRuntimeAdapter]:
    adapters: tuple[ICAnalysisRuntimeAdapter, ...] = (
        ICAutocorrelationAdapter(),
        ICForwardHorizonHalfLifeAdapter(),
        ICPeriodDiagnosticsAdapter(),
        ICQuantilePortfolioStatisticsAdapter(),
        ICResampleStabilityAdapter(),
        ICRollingStabilityAdapter(),
    )
    return {adapter.analysis_type: adapter for adapter in adapters}


__all__ = ["builtin_runtime_adapters"]
