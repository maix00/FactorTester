"""Bounded real Nautilus run of a frozen Strategy on one catalog."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from pathlib import Path
from typing import Any

from server.services.nautilus_bridge.backtest_runner import _load_input, ReplayInput
from server.services.nautilus_bridge.factor_stream import build_factor_expr_bar_adapter
from server.services.nautilus_bridge.reports import export_backtest_reports
from tools.factors.expr.core import FactorExpr
from tools.data.types.time_freq import DataFreq


def run_strategy_replay(
    *, input: ReplayInput, strategy_kind: str,
    factor_bindings: dict[str, FactorExpr],
    product: Any, output_dir: Path, max_bars: int = 8,
    factor_field: str = "CLOSE_ADJUSTED",
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
    publications: dict[str, list[Any]] = {role: [] for role in factor_bindings}

    class Trader(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.factors = {
                role: build_factor_expr_bar_adapter(
                    factor_ref="factor:v2:" + role.encode().hex().ljust(43, "0")[:43],
                    expression=expression, products=(product,),
                    bar_types_by_product={product: bar_type}, source_freq=DataFreq.MIN1,
                    bar_clock=lambda _p, bar: _clock(bar),
                    factor_fields=lambda _p, bar: _bar_fields(bar),
                    first_executable_at=lambda clocks: max(
                        clock.available_at_ns for clock in clocks.values()) + 1,
                    on_publication=publications[role].append,
                )
                for role, expression in factor_bindings.items()
            }
            self.seen = 0

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)

        def on_bar(self, bar) -> None:
            for factor in self.factors.values():
                factor.on_bar(bar)
            self.seen += 1
            if self.seen == 2:
                self.submit_order(self.order_factory.market(
                    instrument_id=bar.bar_type.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str("1"),
                    time_in_force=TimeInForce.AT_THE_OPEN,
                ))

    engine.add_strategy(Trader())
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
        "publications": {role: len(rows) for role, rows in publications.items()},
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


def run_strategy_family_replay(
    *, inputs: dict[Any, ReplayInput], factor_bindings: dict[str, FactorExpr],
    family: Any, output_dir: Path, max_bars: int = 8,
    factor_field: str = "CLOSE_ADJUSTED",
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
    for _, _, _, instrument in opened.values():
        engine.add_instrument(instrument)
    publications: dict[str, list[Any]] = {role: [] for role in factor_bindings}

    class FamilyTrader(Strategy):
        def __init__(self) -> None:
            super().__init__()
            self.factors = {
                role: build_factor_expr_bar_adapter(
                    factor_ref="factor:v2:" + role.encode().hex().ljust(43, "0")[:43],
                    expression=expression, products=tuple(opened),
                    bar_types_by_product=bar_types, source_freq=DataFreq.MIN1,
                    bar_clock=lambda _p, bar: _clock(bar),
                    factor_fields=lambda _p, bar: _bar_fields(bar),
                    first_executable_at=lambda clocks: max(
                        clock.available_at_ns for clock in clocks.values()) + 1,
                    on_publication=publications[role].append,
                )
                for role, expression in factor_bindings.items()
            }
            self.positions_seen: set[Any] = set()
            self.last_signal: Any = None

        def on_start(self) -> None:
            for value in bar_types.values():
                self.subscribe_bars(value)

        def on_bar(self, bar) -> None:
            for factor in self.factors.values():
                factor.on_bar(bar)
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

    engine.add_strategy(FamilyTrader())
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
        "publications": {role: len(rows) for role, rows in publications.items()},
        "orders": engine.get_result().total_orders, "reports": reports,
    }


def run_strategy_family_run_spec(
    *, job_spec: dict[str, Any], plan: dict[str, Any], output_dir: Path,
) -> dict[str, Any]:
    """Resolve frozen factor roles and product catalogs from one Job RunSpec."""
    from server.modules.shared.run_spec_resolution.factors import RunFactorResolver
    from server.services.nautilus_bridge.strategy_families import (
        CrossSectionalGroup, ThresholdState,
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
    catalogs = plan.get("catalog_inputs")
    if not isinstance(catalogs, dict) or not catalogs:
        raise ValueError("strategy plan has no product catalogs")
    inputs = {
        product: ReplayInput(
            Path(str(value["catalog_dir"])).resolve(),
            str(value["contract_uid"]),
        )
        for product, value in catalogs.items()
    }
    return run_strategy_family_replay(
        inputs=inputs, factor_bindings=bindings, family=family,
        output_dir=Path(output_dir), max_bars=int(plan.get("max_input_bars") or 8),
    )
