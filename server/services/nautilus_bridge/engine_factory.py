"""Build one Nautilus backtest engine from one frozen RunSpec.

Every venue, simulated account and strategy in a RunSpec shares one engine.
Immutable instruments and the market-data stream are registered once; no
per-strategy engine fan-out or duplicate matching-liquidity state is created.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from server.services.nautilus_bridge.config import (
    FrozenExecutionPlan,
    UnsupportedExecutionConfig,
)


def build_backtest_engine(
    plan: FrozenExecutionPlan,
    instruments_by_strategy: Mapping[str, Sequence[Any]],
    *,
    fee_models_by_venue: Mapping[str, Any] | None = None,
    trader_id: str = "FT-BACKTEST",
) -> Any:
    """Construct one native BacktestEngine with all frozen venues/instruments.

    ``instruments_by_strategy`` is the source adapter's resolved scope. The
    function verifies each InstrumentId venue against that strategy's frozen
    route, then registers the unique instrument union exactly once.
    """
    historical_fee_venues = {
        str(item["name"])
        for item in plan.venues
        if item.get("native_config", {}).get("fee_model", {}).get("type") == "historical_schedule"
    }
    if historical_fee_venues:
        if not isinstance(fee_models_by_venue, Mapping):
            raise UnsupportedExecutionConfig(
                "venues.native_config.fee_model.schedule_ref",
                "historical fee schedules need per-Venue Nautilus FeeModels",
            )
        missing = historical_fee_venues - set(map(str, fee_models_by_venue))
        unexpected = set(map(str, fee_models_by_venue)) - historical_fee_venues
        if missing or unexpected:
            detail = []
            if missing:
                detail.append("missing " + ", ".join(sorted(missing)))
            if unexpected:
                detail.append("unexpected " + ", ".join(sorted(unexpected)))
            raise UnsupportedExecutionConfig(
                "fee_models_by_venue", "historical FeeModel mapping must match the frozen Venues: "
                + "; ".join(detail),
            )
    elif fee_models_by_venue:
        raise UnsupportedExecutionConfig(
            "fee_models_by_venue", "no Venue selects a historical FeeModel schedule",
        )
    if plan.instrument_execution_policy.requires_daily_settlement_adapter:
        raise UnsupportedExecutionConfig(
            "instrument_execution_policy.daily_settlement",
            "the engine factory requires the frozen official settlement-event stream before enabling DMTM",
        )

    routes = {str(item["strategy_id"]): item for item in plan.strategy_venue_bindings}
    if set(instruments_by_strategy) != set(routes):
        raise UnsupportedExecutionConfig(
            "instruments_by_strategy", "must resolve every frozen strategy instance exactly once",
        )
    venues = {str(item["name"]): item for item in plan.venues}
    resolved: dict[str, Any] = {}
    instrument_scopes: dict[str, set[tuple[str, ...]]] = {}
    actual_venues_by_strategy: dict[str, set[str]] = {}

    for strategy_id, instruments in instruments_by_strategy.items():
        if not instruments:
            raise UnsupportedExecutionConfig(
                "instruments_by_strategy", f"strategy {strategy_id} resolved no executable instruments",
            )
        route = routes[strategy_id]
        allowed_venues = {str(item).upper() for item in route["venue_ids"]}
        scopes = tuple(str(item) for item in route["product_scope_refs"])
        actual_venues: set[str] = set()
        seen_for_strategy: set[str] = set()
        for instrument in instruments:
            instrument_id = getattr(instrument, "id", None)
            venue_id = str(getattr(instrument_id, "venue", "") or "").upper()
            if not venue_id:
                raise UnsupportedExecutionConfig(
                    "instruments_by_strategy", f"strategy {strategy_id} contains an InstrumentId without Venue",
                )
            if venue_id not in allowed_venues:
                raise UnsupportedExecutionConfig(
                    "strategy_venue_bindings.venue_ids",
                    f"strategy {strategy_id} resolved {venue_id}, outside its frozen Venue route",
                )
            instrument_key = str(instrument_id)
            if instrument_key in seen_for_strategy:
                raise UnsupportedExecutionConfig(
                    "instruments_by_strategy", f"strategy {strategy_id} repeats {instrument_key}",
                )
            seen_for_strategy.add(instrument_key)
            previous = resolved.get(instrument_key)
            if previous is not None and previous != instrument:
                raise UnsupportedExecutionConfig(
                    "instruments_by_strategy", f"conflicting Nautilus definitions for {instrument_key}",
                )
            resolved.setdefault(instrument_key, instrument)
            actual_venues.add(venue_id)
            instrument_scopes.setdefault(instrument_key, set()).add(scopes)
        actual_venues_by_strategy[strategy_id] = actual_venues

    configured_venues = set(venues)
    actual_venues = {
        venue for strategy_venues in actual_venues_by_strategy.values()
        for venue in strategy_venues
    }
    if actual_venues != configured_venues:
        raise UnsupportedExecutionConfig(
            "venues", "configured Venues must exactly match the venues in resolved strategy instruments",
        )

    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import (
        BestPriceFillModel,
        CappedOptionFeeModel,
        CompetitionAwareFillModel,
        DefaultFillModel,
        ExecutionEngineConfig,
        FixedFeeModel,
        LimitOrderPartialFillModel,
        MakerTakerFeeModel,
        MarketHoursFillModel,
        OneTickSlippageFillModel,
        PerContractFeeModel,
        ProbabilisticFillModel,
        ProbabilityPriceFeeModel,
        SizeAwareFillModel,
        StaticLatencyModel,
        ThreeTierFillModel,
        TieredNotionalOptionFeeModel,
        TwoTierFillModel,
        VolumeSensitiveFillModel,
    )
    from nautilus_trader.model import (
        AccountType,
        BookType,
        Currency,
        FuturesContract,
        InstrumentId,
        LeveragedMarginModel,
        Money,
        OmsType,
        OtoTriggerMode,
        PositionCostBasis,
        StandardMarginModel,
        TraderId,
        Venue,
    )

    for instrument_id, instrument in resolved.items():
        if not isinstance(instrument, FuturesContract):
            raise UnsupportedExecutionConfig(
                "instruments_by_strategy", "the connected Local source adapter currently resolves futures only",
            )

    overrides = _resolved_cost_basis_overrides(
        plan, instrument_scopes, InstrumentId, PositionCostBasis,
    )
    execution_config = ExecutionEngineConfig(
        position_cost_basis=PositionCostBasis.from_str(
            plan.instrument_execution_policy.cost_basis_default,
        ),
        position_cost_basis_by_instrument=overrides,
    )
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=TraderId.from_str(trader_id),
        exec_engine=execution_config,
    ))
    try:
        for name, config in venues.items():
            native = config["native_config"]
            engine.add_venue(
                venue=Venue.from_str(name),
                oms_type=OmsType.from_str(config["oms_type"]),
                account_type=AccountType.from_str(config["account_type"]),
                starting_balances=[Money.from_str(value) for value in config["starting_balances"]],
                base_currency=Currency.from_str(config["base_currency"]),
                default_leverage=(Decimal(native["default_leverage"])
                                  if native["default_leverage"] is not None else None),
                leverages={
                    InstrumentId.from_str(instrument_id): Decimal(leverage)
                    for instrument_id, leverage in native["leverages"].items()
                },
                margin_model=_margin_model(native, StandardMarginModel, LeveragedMarginModel),
                fill_model=_fill_model(
                    native["fill_model"],
                    DefaultFillModel=DefaultFillModel,
                    BestPriceFillModel=BestPriceFillModel,
                    OneTickSlippageFillModel=OneTickSlippageFillModel,
                    ProbabilisticFillModel=ProbabilisticFillModel,
                    TwoTierFillModel=TwoTierFillModel,
                    ThreeTierFillModel=ThreeTierFillModel,
                    LimitOrderPartialFillModel=LimitOrderPartialFillModel,
                    SizeAwareFillModel=SizeAwareFillModel,
                    CompetitionAwareFillModel=CompetitionAwareFillModel,
                    VolumeSensitiveFillModel=VolumeSensitiveFillModel,
                    MarketHoursFillModel=MarketHoursFillModel,
                ),
                fee_model=_venue_fee_model(
                    plan, config, fee_models_by_venue, Money,
                    FixedFeeModel, PerContractFeeModel,
                    MakerTakerFeeModel, ProbabilityPriceFeeModel,
                    CappedOptionFeeModel, TieredNotionalOptionFeeModel, InstrumentId,
                ),
                latency_model=_latency_model(native["latency_model"], StaticLatencyModel),
                book_type=BookType.from_str(native["book_type"]),
                routing=native["routing"],
                reject_stop_orders=native["reject_stop_orders"],
                support_gtd_orders=native["support_gtd_orders"],
                support_contingent_orders=native["support_contingent_orders"],
                use_position_ids=native["use_position_ids"],
                use_random_ids=native["use_random_ids"],
                use_reduce_only=native["use_reduce_only"],
                use_message_queue=native["use_message_queue"],
                use_market_order_acks=native["use_market_order_acks"],
                bar_execution=native["bar_execution"],
                bar_adaptive_high_low_ordering=native["bar_adaptive_high_low_ordering"],
                trade_execution=native["trade_execution"],
                liquidity_consumption=native["liquidity_consumption"],
                queue_position=native["queue_position"],
                allow_cash_borrowing=native["allow_cash_borrowing"],
                frozen_account=native["frozen_account"],
                oto_trigger_mode=OtoTriggerMode.from_str(native["oto_trigger_mode"]),
                price_protection_points=native["price_protection_points"] or None,
                liquidation_enabled=native["liquidation_enabled"],
                liquidation_trigger_ratio=native["liquidation_trigger_ratio"],
                liquidation_cancel_open_orders=native["liquidation_cancel_open_orders"],
                bar_volume_weights_bps=native["bar_volume_weights_bps"],
                bar_volume_remainder_to=native["bar_volume_remainder_to"],
            )
        for instrument in resolved.values():
            engine.add_instrument(instrument)
    except Exception:
        try:
            engine.dispose()
        except Exception:
            pass
        raise
    return engine


def add_data_batch(engine: Any, batch: Any, *, client_id: Any = None) -> None:
    """Add one immutable, pre-sorted Nautilus data batch to the single engine."""
    if engine is None:
        raise ValueError("a Nautilus BacktestEngine is required")
    if len(batch) == 0:
        raise ValueError("market-data batch must not be empty")
    engine.add_data_batch(batch, client_id=client_id, validate=True, sort=False)


def _resolved_cost_basis_overrides(
    plan: FrozenExecutionPlan,
    scopes_by_instrument: Mapping[str, set[tuple[str, ...]]],
    instrument_id_type: Any,
    basis_type: Any,
) -> dict[Any, Any]:
    policy = plan.instrument_execution_policy
    if not (policy.cost_basis_scope_overrides or policy.cost_basis_instrument_overrides):
        return {}
    result: dict[Any, Any] = {}
    for instrument_id, scopes in scopes_by_instrument.items():
        outcomes = {
            str(policy.resolve_for_instrument(
                instrument_id,
                product_scope_refs=scope,
                daily_settlement_eligible=False,
            )["position_cost_basis"])
            for scope in scopes
        }
        if len(outcomes) != 1:
            raise UnsupportedExecutionConfig(
                "instrument_execution_policy.position_cost_basis",
                f"strategies sharing {instrument_id} specify different Nautilus cost-basis methods",
            )
        basis = next(iter(outcomes))
        if basis != policy.cost_basis_default:
            result[instrument_id_type.from_str(instrument_id)] = basis_type.from_str(basis)
    return result


def _fee_model_for_venue(
    plan: FrozenExecutionPlan, venue_id: str,
    fee_models_by_venue: Mapping[str, Any] | None,
    maker_taker_fee_model: Any, per_contract_fee_model: Any, money_type: Any,
) -> Any:
    if plan.fee == "historical_schedule":
        model = (fee_models_by_venue or {}).get(venue_id)
        if model is None:
            raise UnsupportedExecutionConfig(
                "fee_models_by_venue", f"Venue {venue_id} has no compiled historical Nautilus FeeModel",
            )
        return model
    if plan.fee == "zero":
        return maker_taker_fee_model(Decimal(0), Decimal(0))
    if plan.fee == "per_contract":
        values = dict(plan.fee_details)
        commission = money_type.from_str(f"{values['amount']} {values['currency']}")
        return per_contract_fee_model(commission)
    raise UnsupportedExecutionConfig("fee_mode", f"unsupported compiled fee mode {plan.fee!r}")


def _venue_fee_model(
    plan: FrozenExecutionPlan,
    venue: Mapping[str, Any],
    fee_models_by_venue: Mapping[str, Any] | None,
    money_type: Any,
    fixed_fee_model: Any,
    per_contract_fee_model: Any,
    maker_taker_fee_model: Any,
    probability_price_fee_model: Any,
    capped_option_fee_model: Any,
    tiered_notional_option_fee_model: Any,
    instrument_id_type: Any,
) -> Any:
    spec = venue["native_config"]["fee_model"]
    model_type = spec["type"]
    venue_id = str(venue["name"])
    if model_type == "unconfigured":
        raise UnsupportedExecutionConfig(
            f"venues.{venue_id}.native_config.fee_model",
            "Nautilus requires an explicit FeeModel for every simulated Venue",
        )
    if model_type == "inherit":
        return _fee_model_for_venue(
            plan, venue_id, fee_models_by_venue,
            maker_taker_fee_model, per_contract_fee_model, money_type,
        )
    if model_type == "historical_schedule":
        model = (fee_models_by_venue or {}).get(venue_id)
        if model is None:
            raise UnsupportedExecutionConfig(
                "fee_models_by_venue", f"Venue {venue_id} has no compiled Nautilus FeeModel",
            )
        return model
    if model_type == "zero":
        return maker_taker_fee_model(Decimal(0), Decimal(0))
    if model_type in {"fixed", "per_contract"}:
        commission = money_type.from_str(spec["commission"])
        if model_type == "fixed":
            return fixed_fee_model(
                commission, charge_commission_once=spec["charge_commission_once"],
            )
        return per_contract_fee_model(commission)
    overrides = {
        instrument_id_type.from_str(instrument_id): (
            Decimal(rates[0]), Decimal(rates[1]),
        )
        for instrument_id, rates in spec["overrides"].items()
    }
    rates = (Decimal(spec["maker_rate"]), Decimal(spec["taker_rate"]))
    if model_type == "maker_taker":
        return maker_taker_fee_model(*rates, overrides=overrides)
    if model_type == "probability_price":
        return probability_price_fee_model(*rates, overrides=overrides)
    if model_type == "capped_option":
        cap_rate = spec.get("cap_rate")
        return capped_option_fee_model(
            *rates,
            cap_rate=Decimal(cap_rate) if cap_rate is not None else None,
            overrides=overrides,
        )
    if model_type == "tiered_notional_option":
        return tiered_notional_option_fee_model(*rates, overrides=overrides)
    raise UnsupportedExecutionConfig(
        f"venues.{venue_id}.native_config.fee_model.type",
        f"unsupported FeeModel {model_type!r}",
    )


def _margin_model(config: Mapping[str, Any], standard_model: Any, leveraged_model: Any) -> Any:
    return standard_model() if config["margin_model"] == "standard" else leveraged_model()


def _fill_model(config: Mapping[str, Any], **constructors: Any) -> Any:
    model_type = str(config["type"])
    class_name = {
        "default": "DefaultFillModel",
        "best_price": "BestPriceFillModel",
        "one_tick_slippage": "OneTickSlippageFillModel",
        "probabilistic": "ProbabilisticFillModel",
        "two_tier": "TwoTierFillModel",
        "three_tier": "ThreeTierFillModel",
        "limit_order_partial": "LimitOrderPartialFillModel",
        "size_aware": "SizeAwareFillModel",
        "competition_aware": "CompetitionAwareFillModel",
        "volume_sensitive": "VolumeSensitiveFillModel",
        "market_hours": "MarketHoursFillModel",
    }.get(model_type)
    constructor = constructors.get(class_name)
    if constructor is None:
        raise UnsupportedExecutionConfig(
            "venues.native_config.fill_model.type", f"unsupported FillModel {model_type!r}",
        )
    args = (
        float(config["prob_fill_on_limit"]),
        float(config["prob_slippage"]),
        config["random_seed"],
    )
    if model_type == "competition_aware":
        return constructor(*args, liquidity_factor=float(config["liquidity_factor"]))
    return constructor(*args)


def _latency_model(config: Mapping[str, Any], static_latency_model: Any) -> Any:
    if config["type"] == "none":
        return None
    return static_latency_model(
        base_latency_nanos=config["base_latency_nanos"],
        insert_latency_nanos=config["insert_latency_nanos"],
        update_latency_nanos=config["update_latency_nanos"],
        cancel_latency_nanos=config["cancel_latency_nanos"],
    )


__all__ = ["add_data_batch", "build_backtest_engine"]
