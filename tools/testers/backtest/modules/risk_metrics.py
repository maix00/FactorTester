"""RiskMetricsModule — POST_REPLAY only summary statistics derived from
each strategy's equity curve/returns (EquityCurveModule). These have no
meaningful per-event incremental form (Sharpe/drawdown/skew are properties
of the whole series), unlike EquityCurveModule's PER_EVENT/POST_REPLAY
duality.

Sharpe/Sortino/Calmar are computed un-annualized (mean/std of per-event
returns, not scaled by sqrt(periods_per_year)) -- annualizing correctly
requires knowing the signal frequency, which is a per-strategy
FactorSignalModule setting this module doesn't otherwise depend on; reported
values are therefore "per-period" ratios, not annualized ones, until that
wiring is added.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.equity_curve import equity_curve_for, returns_for


class RiskMetricsModule(ExecutableModule):
    key: ClassVar[str] = "risk_metrics"
    label: ClassVar[str] = "风险指标"

    evaluation_split: ClassVar[FieldRef[str]] = FieldRef("evaluation_split")
        # in-sample cutoff date (inclusive); everything after is out-of-sample.
        # None (default) means the whole run is treated as in-sample, no
        # separate out-of-sample segment is reported.

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "evaluation_split": FieldDefinition(
            public=True, default=None, control_template="date", tab="evaluation",
            chip_template="样本切分: {value}", tab_label="样本划分", tab_order=200,
        ),
    }

    compute_risk_metrics: ClassVar[Flow] = Flow(
        "compute_risk_metrics", inputs=(), outputs=(),
        phase=Phase.POST_REPLAY, order=20,
        compute=lambda account, ctx: _compute_risk_metrics(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (compute_risk_metrics,)


def _compute_risk_metrics(account, ctx) -> None:
    for strategy in account.strategy_configs:
        equity = equity_curve_for(account, strategy)
        returns = returns_for(account, strategy)
        split_raw = account.config_for(strategy).get(RiskMetricsModule.evaluation_split)

        in_sample_metrics = compute_metrics(equity, returns)
        result = {f"{k}": v for k, v in in_sample_metrics.items()}

        if split_raw:
            split = pd.Timestamp(split_raw)
            in_equity, in_returns = equity[equity.index <= split], returns[returns.index <= split]
            out_equity, out_returns = equity[equity.index > split], returns[returns.index > split]
            result.update({f"{k}": v for k, v in compute_metrics(in_equity, in_returns).items()})
            out_metrics = compute_metrics(out_equity, out_returns)
            result.update({f"out_of_sample_{k}": v for k, v in out_metrics.items()})

        account.results.set_final(strategy, **result)


def compute_metrics(equity: pd.Series, returns: pd.Series) -> dict:
    if returns.empty:
        return {
            "sharpe_ratio": 0.0, "max_drawdown": 0.0, "sortino_ratio": 0.0,
            "calmar_ratio": 0.0, "win_rate": 0.0, "skewness": 0.0,
            "kurtosis": 0.0, "avg_turnover": 0.0,
        }

    _EPS = 1e-12  # floating-point noise floor -- even bit-identical input returns
                   # rarely produce an exactly-0.0 std from pandas' variance algorithm
    std = returns.std()
    sharpe_ratio = float(returns.mean() / std) if pd.notna(std) and std > _EPS else 0.0

    cummax = equity.cummax()
    drawdown = equity / cummax - 1.0
    max_drawdown = float(drawdown.min())

    downside = returns[returns < 0]
    downside_std = downside.std()  # NaN when fewer than 2 downside observations (sample std undefined)
    sortino_ratio = (
        float(returns.mean() / downside_std)
        if pd.notna(downside_std) and downside_std > _EPS else 0.0
    )

    calmar_ratio = float(returns.mean() / abs(max_drawdown)) if max_drawdown else 0.0

    win_rate = float((returns > 0).mean())
    skewness = float(returns.skew()) if len(returns) >= 3 else 0.0
    kurtosis = float(returns.kurt()) if len(returns) >= 4 else 0.0
    avg_turnover = 0.0  # requires trade-level notional history; not tracked this round

    return {
        "sharpe_ratio": sharpe_ratio, "max_drawdown": max_drawdown,
        "sortino_ratio": sortino_ratio, "calmar_ratio": calmar_ratio,
        "win_rate": win_rate, "skewness": skewness, "kurtosis": kurtosis,
        "avg_turnover": avg_turnover,
    }
