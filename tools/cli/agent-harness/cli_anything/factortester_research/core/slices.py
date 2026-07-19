from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal


SliceKind = Literal[
    "calendar",
    "rolling",
    "volatility_regime",
    "trend_regime",
    "event_window",
    "custom",
]
SlicePurpose = Literal["selection", "validation", "diagnostic", "oos_annotation"]


@dataclass(frozen=True)
class ResearchSlice:
    """A research-layer time window.

    Backtest engines should receive concrete start/end dates. The research
    harness owns why these windows exist and whether they are allowed for
    parameter selection.
    """

    name: str
    start: str
    end: str
    kind: SliceKind
    purpose: SlicePurpose
    rule: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
            "purpose": self.purpose,
            "rule": self.rule,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ResearchSliceSet:
    name: str
    description: str
    slices: tuple[ResearchSlice, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "slices": [item.to_dict() for item in self.slices],
        }


@dataclass(frozen=True)
class ValidationPlan:
    name: str
    in_sample_start: str
    in_sample_end: str
    oos_start: str
    oos_end: str
    slice_sets: tuple[ResearchSliceSet, ...]
    selection_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "in_sample_start": self.in_sample_start,
            "in_sample_end": self.in_sample_end,
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "selection_policy": self.selection_policy,
            "slice_sets": [item.to_dict() for item in self.slice_sets],
        }


def default_factor_validation_plan(
    *,
    in_sample_start: str,
    in_sample_end: str,
    oos_start: str,
    oos_end: str,
) -> ValidationPlan:
    """Build an explicit legacy factor-research validation plan.

    Ordinary planning uses an immutable TrialPlan. This compatibility helper
    requires callers to provide every boundary and never assigns OOS from the
    current date. The caller remains responsible for proving that the holdout
    was untouched after factor and plan freeze.
    """

    calendar = ResearchSliceSet(
        name="calendar_quarterly",
        description="Calendar quarters for coarse market-regime sanity checks.",
        slices=tuple(
            calendar_quarter_slices(
                start=in_sample_start,
                end=in_sample_end,
                purpose="validation",
            )
        ),
    )
    rolling = ResearchSliceSet(
        name="rolling_63d_step21d",
        description="Approximate 3-month walk-forward diagnostic windows stepped by one month.",
        slices=tuple(
            rolling_slices(
                start=in_sample_start,
                end=in_sample_end,
                window_days=63,
                step_days=21,
                purpose="diagnostic",
            )
        ),
    )
    oos = ResearchSliceSet(
        name="oos_annotation",
        description="Holdout risk annotation windows; not eligible for selection.",
        slices=(ResearchSlice(
            name=f"oos_{oos_start}_{oos_end}",
            start=oos_start,
            end=oos_end,
            kind="custom",
            purpose="oos_annotation",
            rule="explicit caller-assigned holdout; freeze proof required",
        ),),
    )
    return ValidationPlan(
        name="factor_research_default",
        in_sample_start=in_sample_start,
        in_sample_end=in_sample_end,
        oos_start=oos_start,
        oos_end=oos_end,
        slice_sets=(calendar, rolling, oos),
        selection_policy=(
            "Only slices with purpose=selection or validation inside the in-sample "
            "date range may influence factor, product-group, or strategy-policy "
            "selection. purpose=oos_annotation is report-only."
        ),
    )


def calendar_quarter_slices(
    *,
    start: str,
    end: str,
    purpose: SlicePurpose = "validation",
) -> list[ResearchSlice]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    quarter_start = date(start_date.year, ((start_date.month - 1) // 3) * 3 + 1, 1)
    result: list[ResearchSlice] = []
    current = quarter_start
    while current <= end_date:
        q_end = _quarter_end(current)
        s = max(current, start_date)
        e = min(q_end, end_date)
        if s <= e:
            quarter = (current.month - 1) // 3 + 1
            result.append(ResearchSlice(
                name=f"{current.year}Q{quarter}",
                start=s.isoformat(),
                end=e.isoformat(),
                kind="calendar",
                purpose=purpose,
                rule="calendar quarter clipped to plan boundaries",
            ))
        current = _add_months(current, 3)
    return result


def rolling_slices(
    *,
    start: str,
    end: str,
    window_days: int,
    step_days: int,
    purpose: SlicePurpose = "diagnostic",
) -> list[ResearchSlice]:
    if window_days <= 0 or step_days <= 0:
        raise ValueError("window_days and step_days must be positive")
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    result: list[ResearchSlice] = []
    current = start_date
    index = 1
    while current <= end_date:
        slice_end = current + timedelta(days=window_days - 1)
        if slice_end > end_date:
            break
        result.append(ResearchSlice(
            name=f"roll{index:02d}_{current.isoformat()}_{slice_end.isoformat()}",
            start=current.isoformat(),
            end=slice_end.isoformat(),
            kind="rolling",
            purpose=purpose,
            rule=f"{window_days} calendar days, step {step_days} calendar days",
            metadata={"window_days": window_days, "step_days": step_days},
        ))
        current = current + timedelta(days=step_days)
        index += 1
    return result


def regime_slice_placeholder_set() -> ResearchSliceSet:
    """Declare data-driven regime slicing requirements without fabricating labels.

    Concrete volatility/trend/event windows should be generated from point-in-time
    data by separate analysis scripts. The placeholder keeps the workflow honest:
    calendar and rolling slices are mandatory, while data-driven slices need
    auditable generation artifacts before use.
    """

    return ResearchSliceSet(
        name="data_driven_regimes_required",
        description=(
            "Generate volatility, trend, liquidity/cost, and IC sign-change slices "
            "from point-in-time data before making regime-specific claims."
        ),
        slices=(),
    )


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _quarter_end(value: date) -> date:
    return _add_months(value, 3) - timedelta(days=1)


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)
