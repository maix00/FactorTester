"""Composition root for one native event-driven backtest run."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable, Protocol

import pandas as pd

from .contracts import (
    BacktestPlan,
    BacktestProgress,
    BacktestResult,
    EvaluationSegment,
    ExecutionIsolation,
    PortfolioResult,
    PortfolioSnapshot,
)
from .runtime import (
    EventDraft,
    EventEnvelope,
    EventHandler,
    EventObserver,
    EventRuntime,
    EventSource,
    EventTopic,
    MarketSliceBarrier,
)
from ..execution.trading import Ledger, MarketState, OrderManager


class FactorActor(Protocol):
    factor_alias: str

    def on_market_slice(
        self,
        event: EventEnvelope,
        runtime: EventRuntime,
    ) -> EventDraft | Iterable[EventDraft] | None: ...


class StrategyActor(Protocol):
    factor_alias: str
    strategy_id: str
    portfolio_id: str

    def on_factor_signal(
        self,
        event: EventEnvelope,
        runtime: EventRuntime,
    ) -> EventDraft | Iterable[EventDraft] | None: ...


@dataclass(frozen=True, slots=True)
class StrategyLane:
    """An independently accounted strategy path sharing upstream market data."""

    strategy: StrategyActor
    ledger: Ledger
    order_manager: OrderManager
    intent_policy: EventHandler | None = None

    def __post_init__(self) -> None:
        if self.strategy.portfolio_id != self.ledger.portfolio_id:
            raise ValueError("strategy and ledger portfolio ids must match")
        if self.order_manager.ledger is not self.ledger:
            raise ValueError("order manager must use the lane ledger")


@dataclass(frozen=True, slots=True)
class ExecutionVenue:
    """Execution handlers and the portfolios whose orders they may consume."""

    portfolio_ids: frozenset[str]
    on_order: EventHandler
    on_market_data: EventHandler | None = None

    def __post_init__(self) -> None:
        if not self.portfolio_ids:
            raise ValueError("execution venue must own at least one portfolio")


class BacktestRunner:
    """Validate, wire, run, and collect one causal multi-strategy backtest."""

    def __init__(
        self,
        plan: BacktestPlan,
        *,
        market_source: EventSource,
        market: MarketState,
        factors: tuple[FactorActor, ...],
        lanes: tuple[StrategyLane, ...],
        venues: tuple[ExecutionVenue, ...],
        observers: tuple[EventObserver, ...] = (),
        progress: Callable[[BacktestProgress], None] | None = None,
    ) -> None:
        if not factors or not lanes or not venues:
            raise ValueError("backtest requires factors, strategy lanes, and venues")
        self.plan = plan
        self.market_source = market_source
        self.market = market
        self.factors = factors
        self.lanes = lanes
        self.venues = venues
        self.observers = observers
        self.progress = progress
        self._has_run = False
        self._validate_lanes()

    def run(self) -> BacktestResult:
        if self._has_run:
            raise RuntimeError("BacktestRunner instances are single-use")
        self._has_run = True
        runtime = EventRuntime(self.plan.identity.run_id)
        barrier = MarketSliceBarrier(self.plan.instruments)
        runtime.add_source(self.market_source)
        runtime.add_finalizer(barrier.finalize)
        runtime.subscribe(EventTopic.MARKET_DATA, self.market.on_market_data)
        runtime.subscribe(EventTopic.MARKET_DATA, barrier.on_price)
        runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, self._request_report)
        if self.progress is not None:
            runtime.subscribe(EventTopic.REPORT, self._report_progress)

        for venue in self.venues:
            if venue.on_market_data is not None:
                runtime.subscribe(EventTopic.MARKET_DATA, venue.on_market_data)
            runtime.subscribe(
                EventTopic.ORDER_SUBMITTED,
                _route_payload(venue.on_order, "portfolio_id", venue.portfolio_ids),
            )
        for factor in self.factors:
            runtime.subscribe(EventTopic.MARKET_SLICE_CLOSED, factor.on_market_slice)
        recorders: dict[str, _PortfolioRecorder] = {}
        for lane in self.lanes:
            runtime.subscribe(
                EventTopic.FACTOR_SIGNAL,
                _route_payload(
                    lane.strategy.on_factor_signal,
                    "factor_alias",
                    frozenset({lane.strategy.factor_alias}),
                ),
            )
            if lane.intent_policy is None:
                runtime.subscribe(
                    EventTopic.PORTFOLIO_INTENT,
                    _route_payload(
                        lane.order_manager.on_portfolio_intent,
                        "portfolio_id",
                        frozenset({lane.strategy.portfolio_id}),
                    ),
                )
            else:
                runtime.subscribe(
                    EventTopic.PORTFOLIO_INTENT,
                    _route_payload(
                        lane.intent_policy,
                        "portfolio_id",
                        frozenset({lane.strategy.portfolio_id}),
                    ),
                )
                runtime.subscribe(
                    EventTopic.PORTFOLIO_APPROVED,
                    _route_payload(
                        lane.order_manager.on_portfolio_intent,
                        "portfolio_id",
                        frozenset({lane.strategy.portfolio_id}),
                    ),
                )
            runtime.subscribe(
                EventTopic.FILL,
                _route_payload(
                    lane.ledger.on_fill,
                    "portfolio_id",
                    frozenset({lane.strategy.portfolio_id}),
                ),
            )
            runtime.subscribe(EventTopic.SETTLEMENT, lane.ledger.on_settlement)
            recorder = _PortfolioRecorder(lane.ledger, self.plan.evaluation_window)
            recorders[lane.strategy.portfolio_id] = recorder
            runtime.subscribe(EventTopic.REPORT, recorder.on_report)
        for observer in self.observers:
            runtime.add_observer(observer)

        runtime.run()
        result = self._result(runtime, recorders)
        if self.progress is not None:
            self.progress(BacktestProgress(
                self.plan.identity.run_id,
                "complete",
                len(self.plan.timestamps),
                len(self.plan.timestamps),
                "事件驱动回测完成",
            ))
        return result

    def _report_progress(
        self, event: EventEnvelope, runtime: EventRuntime
    ) -> None:
        completed = sum(
            1 for record in runtime.journal if record.event.topic == EventTopic.REPORT
        ) + 1
        self.progress(BacktestProgress(
            self.plan.identity.run_id,
            "event_replay",
            completed,
            len(self.plan.timestamps),
            f"完成时间片 {completed}/{len(self.plan.timestamps)}",
        ))

    @staticmethod
    def _request_report(
        event: EventEnvelope, runtime: EventRuntime
    ) -> EventDraft:
        return EventDraft(EventTopic.REPORT, event.timestamp, priority=100)

    def _validate_lanes(self) -> None:
        strategy_ids = [lane.strategy.strategy_id for lane in self.lanes]
        portfolio_ids = [lane.strategy.portfolio_id for lane in self.lanes]
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("strategy ids must be unique within a run")
        if len(portfolio_ids) != len(set(portfolio_ids)):
            raise ValueError("portfolio ids must be unique within a run")
        expected = set(self.plan.instruments)
        for lane in self.lanes:
            if set(lane.ledger.positions) != expected:
                raise ValueError("every lane ledger must cover plan instruments")
        owned = [portfolio_id for venue in self.venues for portfolio_id in venue.portfolio_ids]
        if len(owned) != len(set(owned)):
            raise ValueError("execution venues must not overlap portfolio ownership")
        if set(owned) != set(portfolio_ids):
            raise ValueError("execution venues must cover every lane portfolio exactly once")
        if (
            self.plan.execution_isolation == ExecutionIsolation.INDEPENDENT_COMPARISON
            and any(len(venue.portfolio_ids) != 1 for venue in self.venues)
        ):
            raise ValueError(
                "independent comparison requires one execution venue per portfolio"
            )
        venue_actors = [
            actor
            for venue in self.venues
            if (actor := getattr(venue.on_order, "__self__", None)) is not None
        ]
        if (
            self.plan.execution_isolation == ExecutionIsolation.INDEPENDENT_COMPARISON
            and len({id(actor) for actor in venue_actors}) != len(venue_actors)
        ):
            raise ValueError(
                "independent comparison requires distinct execution venue state"
            )

    def _result(
        self,
        runtime: EventRuntime,
        recorders: dict[str, _PortfolioRecorder],
    ) -> BacktestResult:
        portfolios = {}
        for lane in self.lanes:
            ledger = lane.ledger
            portfolio_id = lane.strategy.portfolio_id
            portfolios[portfolio_id] = PortfolioResult(
                strategy_id=lane.strategy.strategy_id,
                portfolio_id=portfolio_id,
                snapshots=tuple(recorders[portfolio_id].snapshots),
                fills=tuple(ledger.fills),
            )
        return BacktestResult(
            identity=self.plan.identity,
            engine="native-event-driven",
            portfolios=portfolios,
            event_count=len(runtime.journal),
        )


class _PortfolioRecorder:
    def __init__(self, ledger: Ledger, evaluation_window=None) -> None:
        self.ledger = ledger
        self.evaluation_window = evaluation_window
        self.snapshots: list[PortfolioSnapshot] = []

    def on_report(self, event: EventEnvelope, runtime: EventRuntime) -> None:
        self.snapshots.append(PortfolioSnapshot(
            timestamp=event.timestamp,
            cash_minor=self.ledger.cash_minor,
            margin_minor=self.ledger.margin_minor,
            equity_minor=self.ledger.equity_minor,
            realized_pnl_minor=self.ledger.realized_pnl_minor,
            positions=dict(self.ledger.positions),
            evaluation_segment=(
                self.evaluation_window.segment(event.timestamp)
                if self.evaluation_window is not None else EvaluationSegment.IN_SAMPLE
            ),
        ))


def _route_payload(
    handler: EventHandler,
    attribute: str,
    accepted: frozenset[str],
) -> EventHandler:
    """Route lane-scoped events before invoking mutable actors."""

    def routed(event: EventEnvelope, runtime: EventRuntime):
        if getattr(event.payload, attribute, None) not in accepted:
            return None
        return handler(event, runtime)

    return routed
