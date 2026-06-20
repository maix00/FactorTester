"""Pre-trade risk actors that preserve strategy-relative target weights."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

import numpy as np

from .contracts import PortfolioIntent, TargetKind
from .runtime import EventDraft, EventEnvelope, EventRuntime, EventTopic
from .trading import Ledger


class FuturesMarginConstraint:
    """Approve or proportionally scale target weights by collateral capacity."""

    def __init__(
        self,
        ledger: Ledger,
        margin_ratios: Mapping[str, float],
        *,
        collateral_fraction: float = 1.0,
        reject_instead_of_scale: bool = False,
    ) -> None:
        if not 0 < collateral_fraction <= 1:
            raise ValueError("collateral_fraction must be within (0, 1]")
        if any(not 0 < ratio <= 1 for ratio in margin_ratios.values()):
            raise ValueError("margin ratios must be within (0, 1]")
        self.ledger = ledger
        self.margin_ratios = dict(margin_ratios)
        self.collateral_fraction = collateral_fraction
        self.reject_instead_of_scale = reject_instead_of_scale

    def on_portfolio_intent(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft | None:
        intent = event.payload
        if not isinstance(intent, PortfolioIntent):
            raise TypeError("portfolio.intent payload must be PortfolioIntent")
        if intent.portfolio_id != self.ledger.portfolio_id:
            return None
        if intent.target_kind != TargetKind.WEIGHT:
            raise ValueError("FuturesMarginConstraint requires target weights")
        required_fraction = sum(
            abs(float(weight)) * self.margin_ratios[instrument]
            for instrument, weight in zip(intent.instruments, intent.values, strict=True)
        )
        if required_fraction <= self.collateral_fraction + 1e-12:
            return EventDraft(EventTopic.PORTFOLIO_APPROVED, event.timestamp, intent)
        if self.reject_instead_of_scale:
            return EventDraft(EventTopic.PORTFOLIO_REJECTED, event.timestamp, intent)
        scale = self.collateral_fraction / required_fraction
        approved = replace(intent, values=np.asarray(intent.values) * scale)
        return EventDraft(EventTopic.PORTFOLIO_APPROVED, event.timestamp, approved)
