"""Built-in execution adapters for registered IC auxiliary analyses."""

from ..contracts import ICAnalysisRuntimeAdapter
from .autocorrelation import ICAutocorrelationAdapter
from .periods import ICPeriodDiagnosticsAdapter
from .resample import ICResampleStabilityAdapter
from .rolling import ICRollingStabilityAdapter


def builtin_runtime_adapters() -> dict[str, ICAnalysisRuntimeAdapter]:
    adapters: tuple[ICAnalysisRuntimeAdapter, ...] = (
        ICAutocorrelationAdapter(),
        ICPeriodDiagnosticsAdapter(),
        ICResampleStabilityAdapter(),
        ICRollingStabilityAdapter(),
    )
    return {adapter.analysis_type: adapter for adapter in adapters}


__all__ = ["builtin_runtime_adapters"]
