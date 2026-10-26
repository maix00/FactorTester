"""Bounded real Nautilus run of a frozen Strategy on one catalog."""

from __future__ import annotations

from decimal import Decimal
from collections import deque
from pathlib import Path
from typing import Any

from server.services.nautilus_bridge.backtest_runner import _load_input, ReplayInput
from server.services.nautilus_bridge.factor_stream import build_factor_expr_bar_adapter
from server.services.nautilus_bridge.nautilus_events import NautilusEventTimeline
from server.services.nautilus_bridge.reports import export_backtest_reports
from tools.factors.expr.core import FactorExpr
from tools.data.types.time_freq import DataFreq


def _shared_factor_adapter(*, bindings, refs, products, bar_types, events,
                           calendar, publications, publication_counts):
    """One run/input/clock scoped DAG; roles only subscribe to its outputs."""
    if set(refs) != set(bindings):
        raise ValueError("factor role refs must exactly match their frozen bindings")
    expressions = {}
    roles_by_ref = {}
    for role, expression in bindings.items():
        ref = refs[role]
        previous = expressions.get(ref)
        if previous is not None and previous.semantic_fingerprint() != expression.semantic_fingerprint():
            raise ValueError("one frozen factor ref resolved to conflicting expressions")
        expressions[ref] = expression
        roles_by_ref.setdefault(ref, []).append(role)

    def publish(rows):
        for ref, publication in rows.items():
            for role in roles_by_ref[ref]:
                publications[role].append(publication)
                publication_counts[role] += 1

    return build_factor_expr_bar_adapter(
        expressions=expressions, products=products,
        bar_types_by_product=bar_types, source_freq=DataFreq.MIN1,
        session_calendar=calendar, event_line=events,
        bar_clock=lambda _p, bar: _clock(bar),
        factor_fields=lambda _p, bar: _bar_fields(bar),
        first_executable_at=lambda clocks: max(clock.available_at_ns for clock in clocks.values()) + 1,
        on_publication=publish,
    )


def run_strategy_replay(
    *, input: ReplayInput, strategy_kind: str,
    factor_bindings: dict[str, FactorExpr],
    factor_refs: dict[str, str],
    product: Any, output_dir: Path, max_bars: int = 8,
    factor_field: str = "CLOSE_ADJUSTED", session_calendar: Any = None,
) -> dict[str, Any]:
    """Run one FactorExpr strategy in Nautilus and export native reports."""
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import (
        AccountType, BarType, Currency, Money, OmsType, OrderSide, Quantity,
        TimeInForce, TraderId, Venue,
    )
    from nautilus_trader.trading import Strategy

    folder, catalog, receipt, instrument = _load_input(input)
    bar_type = BarType.from_str(str(receipt["bar_type"]))
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str("FT-FACTOR-001"),
    ))
    venue = Venue("CFFEX")
    engine.add_venue(
        venue=venue, oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
        starting_balances=[Money.from_str("1000000 CNY")],
        fee_model=MakerTakerFeeModel(
            maker_rate=Decimal(0), taker_rate=Decimal(0)),
    )
    engine.add_instrument(instrument)
    publications = {role: deque(maxlen=2) for role in factor_bindings}
    publication_counts = dict.fromkeys(factor_bindings, 0)

    class Trader(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.events = NautilusEventTimeline(calendar=session_calendar)
            self.factor_adapter = _shared_factor_adapter(
                bindings=factor_bindings, refs=factor_refs, products=(product,),
                bar_types={product: bar_type}, events=self.events, calendar=session_calendar,
                publications=publications, publication_counts=publication_counts,
            )
            self.seen = 0

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)

        def on_bar(self, bar) -> None:
            self.events.on_bar(bar)
            self.factor_adapter.on_bar(bar)
            self.seen += 1
            if self.seen == 2:
                self.submit_order(self.order_factory.market(
                    instrument_id=bar.bar_type.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str("1"),
                    time_in_force=TimeInForce.AT_THE_OPEN,
                ))

    trader = Trader()
    engine.add_strategy(trader)
    bars = catalog.query_bars(identifiers=[receipt["bar_type"]], start=0, end=2**63 - 1)
    if len(bars) > max_bars:
        raise ValueError("factor replay exceeds explicit bar cap")
    engine.add_data(list(bars))
    engine.run()
    engine.end()
    reports = export_backtest_reports(engine, Path(output_dir), venue=venue)
    return {
        "engine": "nautilus_trader",
        "bars": len(bars),
        "strategy_kind": strategy_kind,
        "factor_roles": sorted(factor_bindings),
        "publications": publication_counts,
        "factor_plan_nodes": trader.factor_adapter.stream._executor.node_count,
        "reports": reports,
        "order_count": engine.get_result().total_orders,
        "catalog": str(folder),
    }


def _bar_fields(bar: Any) -> dict[str, float]:
    return {
        "OPEN_ADJUSTED": float(bar.open),
        "HIGH_ADJUSTED": float(bar.high),
        "LOW_ADJUSTED": float(bar.low),
        "CLOSE_ADJUSTED": float(bar.close),
        "VOLUME": float(getattr(bar, "volume", 0)),
    }


def _clock(bar: Any):
    from server.services.nautilus_bridge.market_data import BarClock
    minute = 60_000_000_000
    end = int(bar.ts_event)
    return BarClock(None, None, end - minute, end, int(bar.ts_init), "factor bar")


def _build_strategy_family_engine(execution_plan: Any, instruments: list[Any]):
    from nautilus_trader.model import Venue
    from server.services.nautilus_bridge.engine_factory import build_backtest_engine

    configured = {str(item["name"]).upper() for item in execution_plan.venues}
    matching = [
        route for route in execution_plan.strategy_venue_bindings
        if {str(value).upper() for value in route["venue_ids"]} == configured
    ]
    if len(matching) != 1:
        raise ValueError(
            "strategy family replay requires exactly one strategy route "
            "covering every frozen Venue",
        )
    engine = build_backtest_engine(
        execution_plan, {str(matching[0]["strategy_id"]): instruments},
        trader_id="FT-STRATEGY-001",
    )
    return engine, Venue.from_str(sorted(configured)[0])


def run_strategy_family_replay(
    *, inputs: dict[Any, ReplayInput], factor_bindings: dict[str, FactorExpr],
    factor_refs: dict[str, str],
    family: Any, output_dir: Path, max_bars: int = 8,
    factor_field: str = "CLOSE_ADJUSTED", execution_plan: Any = None,
    session_calendar: Any = None,
) -> dict[str, Any]:
    """Run one strategy family across multiple frozen product catalogs."""
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import (
        AccountType, BarType, Currency, Money, OmsType, OrderSide, Quantity,
        TimeInForce, TraderId, Venue,
    )
    from nautilus_trader.trading import Strategy

    opened = {product: _load_input(item) for product, item in inputs.items()}
    bar_types = {
        product: BarType.from_str(str(row[2]["bar_type"]))
        for product, row in opened.items()
    }
    instruments = [row[3] for row in opened.values()]
    if execution_plan is not None:
        engine, venue = _build_strategy_family_engine(execution_plan, instruments)
    else:
        engine = BacktestEngine(config=BacktestEngineConfig(
            trader_id=TraderId.from_str("FT-STRATEGY-001"),
        ))
        venue = Venue("CFFEX")
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN, base_currency=Currency.from_str("CNY"),
            starting_balances=[Money.from_str("1000000 CNY")],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0), taker_rate=Decimal(0)),
        )
        for instrument in instruments:
            engine.add_instrument(instrument)
    publications = {role: deque(maxlen=2) for role in factor_bindings}
    publication_counts = dict.fromkeys(factor_bindings, 0)

    class FamilyTrader(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.events = NautilusEventTimeline(calendar=session_calendar)
            self.factor_adapter = _shared_factor_adapter(
                bindings=factor_bindings, refs=factor_refs, products=tuple(opened),
                bar_types=bar_types, events=self.events, calendar=session_calendar,
                publications=publications, publication_counts=publication_counts,
            )
            self.positions_seen: set[Any] = set()
            self.last_signal: Any = None

        def on_start(self) -> None:
            for value in bar_types.values():
                self.subscribe_bars(value)

        def on_bar(self, bar) -> None:
            self.events.on_bar(bar)
            self.factor_adapter.on_bar(bar)
            signal = publications.get("signal") or []
            if not signal or signal[-1] is self.last_signal:
                return
            self.last_signal = signal[-1]
            members = set(family.members(dict(signal[-1].values)))
            for product, member in opened.items():
                instrument_id = BarType.from_str(str(member[2]["bar_type"])).instrument_id
                side = OrderSide.BUY if product in members else OrderSide.SELL
                if side is OrderSide.SELL and product not in self.positions_seen:
                    continue
                if side is OrderSide.BUY and product in self.positions_seen:
                    continue
                self.submit_order(self.order_factory.market(
                    instrument_id=instrument_id, order_side=side,
                    quantity=Quantity.from_str("1"),
                    time_in_force=TimeInForce.AT_THE_OPEN,
                ))
                self.positions_seen.add(product) if side is OrderSide.BUY else self.positions_seen.discard(product)

    trader = FamilyTrader()
    engine.add_strategy(trader)
    bars = []
    for _, catalog, receipt, _ in opened.values():
        bars.extend(catalog.query_bars(
            identifiers=[receipt["bar_type"]], start=0, end=2**63 - 1))
    bars.sort(key=lambda item: int(item.ts_init))
    if len(bars) > max_bars * max(1, len(opened)):
        raise ValueError("strategy replay exceeds explicit bar cap")
    engine.add_data(bars)
    engine.run()
    engine.end()
    reports = export_backtest_reports(engine, Path(output_dir), venue=venue)
    return {
        "engine": "nautilus_trader", "products": sorted(map(str, opened)),
        "factor_roles": sorted(factor_bindings), "bars": len(bars),
        "publications": publication_counts,
        "factor_plan_nodes": trader.factor_adapter.stream._executor.node_count,
        "orders": engine.get_result().total_orders, "reports": reports,
    }


def run_strategy_family_run_spec(
    *, job_spec: dict[str, Any], plan: dict[str, Any], output_dir: Path,
) -> dict[str, Any]:
    """Resolve frozen factor roles and product catalogs from one Job RunSpec."""
    from server.modules.shared.run_spec_resolution.factors import RunFactorResolver
    from server.services.nautilus_bridge.runtime_status import nautilus_runtime_status
    from server.services.nautilus_bridge.strategy_families import (
        CrossSectionalGroup, ThresholdState,
    )

    runtime = nautilus_runtime_status()
    if not runtime["compatible"]:
        raise ValueError(
            "Nautilus runtime unavailable or version-mismatched: "
            f"found={runtime['version'] or 'missing'} expected={runtime['expected']}"
        )

    template = plan.get("strategy")
    if not isinstance(template, dict):
        raise ValueError("strategy plan is missing")
    kind = str(template.get("kind") or "")
    parameters = template.get("parameters") or {}
    if kind == "cross_sectional_group":
        family = CrossSectionalGroup(
            int(parameters.get("split_count") or 0),
            int(parameters.get("group_index") or 0),
        )
    elif kind == "threshold":
        family = ThresholdState(
            float(parameters.get("entry_threshold") or 0),
            float(parameters.get("exit_threshold") or 0),
            str(parameters.get("side_mode") or "long_short"),
        )
    else:
        raise ValueError(f"unsupported strategy family: {kind}")

    shared = ((job_spec.get("run_spec") or {}).get("configuration") or {}).get("shared") or {}
    resolver = RunFactorResolver(
        owner=str(job_spec.get("_owner") or job_spec.get("owner") or ""),
        frozen_factors=shared.get("factors") or [],
        external_factor_artifacts=shared.get("external_factor_artifacts"),
    )
    roles = template.get("factor_roles")
    if not isinstance(roles, dict) or not roles:
        raise ValueError("strategy has no factor role bindings")
    bindings = {}
    factor_refs = {}
    for role, binding in roles.items():
        if not isinstance(binding, dict):
            raise ValueError(f"factor role {role!r} has an invalid binding")
        factor = resolver.resolve(
            factor_ref=str(binding.get("ref") or ""),
            alias=str(binding.get("alias") or ""),
        )
        expression = getattr(factor, "expr", None)
        if expression is None:
            raise ValueError(f"factor role {role!r} has no FactorExpr")
        bindings[str(role)] = expression
        ref = str(binding.get("ref") or "")
        if not ref.startswith("factor:v2:"):
            raise ValueError(f"factor role {role!r} must freeze its immutable ref")
        factor_refs[str(role)] = ref
    catalogs = plan.get("catalog_inputs")
    run_spec_value = job_spec.get("run_spec") if isinstance(job_spec, dict) else None
    source_adapter = plan.get("source_adapter") or {}
    window = plan.get("run_window") or {}
    staging_requests = plan.get("catalog_staging")
    if not isinstance(catalogs, dict) or not catalogs:
        from server.services.nautilus_bridge.catalog_plan import catalog_staging_requests
        from server.services.nautilus_bridge.catalog_staging import stage_run_spec_catalogs

        if not isinstance(run_spec_value, dict):
            raise ValueError("strategy plan has no product catalogs and no RunSpec")
        staging_requests = staging_requests or catalog_staging_requests(run_spec_value)
        catalogs = stage_run_spec_catalogs(
            staging_requests=staging_requests,
            source_key=str(source_adapter.get("member_key") or ""),
            frequency=str(source_adapter.get("frequency") or ""),
            start_utc=str(window.get("start") or ""),
            end_utc=str(window.get("end") or ""),
            target_root=Path(output_dir) / "catalogs",
        )
        plan = {**plan, "catalog_inputs": catalogs}
    if plan.get("session_calendar") is None and staging_requests:
        try:
            from server.services.nautilus_bridge.catalog_staging import (
                build_run_spec_session_calendar,
            )
            plan["session_calendar"] = build_run_spec_session_calendar(
                staging_requests=staging_requests,
                source_key=str(source_adapter.get("member_key") or ""),
                frequency=str(source_adapter.get("frequency") or ""),
                start_utc=str(window.get("start") or ""),
                end_utc=str(window.get("end") or ""),
            )
        except (OSError, ValueError) as error:
            # A fixed-window factor can still run.  A session-window factor
            # must fail its own compilation instead of silently using 1 bar.
            plan["session_calendar_error"] = str(error)
    inputs = {
        product: ReplayInput(
            Path(str(value["catalog_dir"])).resolve(),
            str(value["contract_uid"]),
        )
        for product, value in catalogs.items()
    }
    execution_plan = None
    run_spec = job_spec.get("run_spec") if isinstance(job_spec, dict) else None
    if isinstance(run_spec, dict):
        analyses = (run_spec.get("configuration") or {}).get("analyses") or {}
        backtest = analyses.get("backtest") or {}
        execution = backtest.get("execution") or {}
        contract = execution.get("nautilus_contract") or {}
        settings = contract.get("settings") if isinstance(contract, dict) else None
        if isinstance(settings, dict):
            from server.services.nautilus_bridge.config import compile_frozen_execution_plan

            execution_plan = compile_frozen_execution_plan(
                settings, feed_kind="bar",
                adapter_capabilities=frozenset({
                    "native_bar_open_market_orders",
                    "native_bar_volume_consumption",
                    "daily_settlement",
                }),
            )
    return run_strategy_family_replay(
        inputs=inputs, factor_bindings=bindings, factor_refs=factor_refs, family=family,
        output_dir=Path(output_dir), max_bars=int(plan.get("max_input_bars") or 8),
        execution_plan=execution_plan,
        session_calendar=plan.get("session_calendar"),
    )
