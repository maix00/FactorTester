"""RiskMetricsModule — POST_REPLAY summary statistics from result curves."""

from __future__ import annotations

from typing import Any, ClassVar, cast
import pandas as pd

from tools.analytics import compute_result_metrics, result_metric_manifest
from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.equity_curve import display_equity_curve_for
from tools.testers.backtest.modules.run_window import RunWindowModule


class RiskMetricsModule(ExecutableModule):
    key: ClassVar[str] = "risk_metrics"
    label: ClassVar[str] = "风险指标"

    compute_risk_metrics: ClassVar[Flow] = Flow(
        "compute_risk_metrics", inputs=(), outputs=(),
        phase=Phase.POST_REPLAY, order=20,
        description="计算风险指标",
        compute=lambda state, ctx: _compute_risk_metrics(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (compute_risk_metrics,)

    @classmethod
    def result_metric_manifest(cls) -> list[dict[str, object]]:
        return result_metric_manifest()


def _compute_risk_metrics(state, ctx) -> None:
    for strategy in state.strategy_configs:
        equity = cast(pd.Series, display_equity_curve_for(state, strategy))
        returns = equity.pct_change().dropna()
        split_raw = state.config_for(strategy).get(RunWindowModule.evaluation_split)

        in_sample_metrics = compute_metrics(equity, returns)
        result = {f"{k}": v for k, v in in_sample_metrics.items()}

        if split_raw:
            split = _split_timestamp_for_index(split_raw, equity.index)
            in_equity = cast(pd.Series, equity.loc[equity.index <= split])
            in_returns = cast(pd.Series, returns.loc[returns.index <= split])
            out_equity = cast(pd.Series, equity.loc[equity.index > split])
            out_returns = cast(pd.Series, returns.loc[returns.index > split])
            result.update({f"{k}": v for k, v in compute_metrics(in_equity, in_returns).items()})
            out_metrics = compute_metrics(out_equity, out_returns)
            result.update({f"out_of_sample_{k}": v for k, v in out_metrics.items()})

        state.results.set_final(strategy, **result)


def _split_timestamp_for_index(value: Any, index: pd.Index) -> pd.Timestamp:
    split = pd.Timestamp(value)
    tz = getattr(index, "tz", None)
    if tz is None:
        if split.tzinfo is not None:
            return split.tz_convert(None)
        return split
    if split.tzinfo is None:
        return split.tz_localize(tz)
    return split.tz_convert(tz)


def compute_metrics(equity: pd.Series, returns: pd.Series) -> dict:
    return dict(compute_result_metrics(equity, returns))
