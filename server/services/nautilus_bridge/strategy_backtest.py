"""Frozen Job control plane over one native factor/strategy runtime."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from server.services.nautilus_bridge.backtest_runner import (
    _load_input, ReplayInput, preflight_catalogs, replay_catalog_batches,
)
from server.services.nautilus_bridge.reports import export_backtest_reports
from server.services.nautilus_bridge.strategy_families import CrossSectionalGroup, ThresholdState
from tools.data.types.time_freq import DataFreq


def _frozen_shared_plan(bindings, refs, products, calendar):
    from tools.factors.expr.streaming.rust_incremental import shared_factor_plan_spec
    if not bindings or set(refs) != set(bindings) or "signal" not in bindings:
        raise ValueError("factor roles must exactly bind frozen refs and include signal")
    expressions = {}
    for role, expression in bindings.items():
        ref = refs[role]
        if ref in expressions and expressions[ref].semantic_fingerprint() != expression.semantic_fingerprint():
            raise ValueError("one frozen factor ref resolved to conflicting expressions")
        expressions[ref] = expression
    spec, _ = shared_factor_plan_spec(expressions, products, source_freq=DataFreq.MIN1,
                                      session_calendar=calendar)
    output_by_ref = {ref: index for index, ref in enumerate(expressions)}
    return spec, {role: output_by_ref[ref] for role, ref in refs.items()}


def run_strategy_replay(*, input: ReplayInput, strategy_kind: str, factor_bindings,
                        factor_refs, product, output_dir: Path, max_bars: int = 8,
                        session_calendar=None, batch_minutes: int = 20):
    if strategy_kind != "threshold":
        raise ValueError("single strategy helper requires threshold family")
    result = run_strategy_family_replay(inputs={product:input}, factor_bindings=factor_bindings,
        factor_refs=factor_refs, family=ThresholdState(1,0), output_dir=output_dir,
        max_bars=max_bars, session_calendar=session_calendar, batch_minutes=batch_minutes)
    return {**result,"strategy_kind":strategy_kind,"order_count":result["orders"],
            "catalog":str(input.catalog_dir)}


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


def run_strategy_family_replay(*, inputs: dict[Any,ReplayInput], factor_bindings,
    factor_refs, family, output_dir: Path, max_bars: int = 8, execution_plan=None,
    session_calendar=None, batch_minutes: int = 20, trace_path: Path | None = None):
    """One Rust Actor/Plan and native consumer; Python never receives a Bar."""
    from nautilus_trader._libnautilus import attach_factor_family
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType, Currency, Money, OmsType, TraderId, Venue

    if isinstance(family,CrossSectionalGroup):
        rule={"kind":"cross_sectional_group",**asdict(family)}
    elif isinstance(family,ThresholdState):
        rule={"kind":"threshold",**asdict(family)}
    else:
        raise ValueError("unsupported native strategy family")
    products=tuple(inputs)
    spec, role_outputs = _frozen_shared_plan(factor_bindings,factor_refs,products,session_calendar)
    opened={product:_load_input(item) for product,item in inputs.items()}
    preflight_catalogs(opened.values(),max_input_bars=max_bars*len(opened))
    instruments=[row[3] for row in opened.values()]
    strategy_id="FactorFamily-000"
    if execution_plan is not None:
        engine,venue=_build_strategy_family_engine(execution_plan,instruments)
        strategy_id=str(execution_plan.strategy_venue_bindings[0]["strategy_id"])
        if "-" not in strategy_id: strategy_id += "-000"
    else:
        engine=BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId.from_str("FT-STRATEGY-001")))
        venue=Venue("CFFEX")
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.MARGIN,
            base_currency=Currency.from_str("CNY"),starting_balances=[Money.from_str("1000000 CNY")],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0),taker_rate=Decimal(0)))
        for instrument in instruments: engine.add_instrument(instrument)
    try:
        runtime=attach_factor_family(engine=engine,plan_json=json.dumps(spec),
            products=list(map(str,products)),bar_types=[str(row[2]["bar_type"]) for row in opened.values()],
            consumers_json=json.dumps([{"strategy_id":strategy_id,"signal_output":role_outputs["signal"],"rule":rule}]),
            calendar_json=json.dumps([(s.start_ns,s.end_ns) for s in session_calendar.sessions] if session_calendar is not None else []),
            trace_path=None if trace_path is None else str(trace_path))
        try:
            replay=replay_catalog_batches(engine,opened.values(),max_input_bars=max_bars*len(opened),batch_minutes=batch_minutes)
        except Exception:
            runtime.raise_if_failed()
            raise
        runtime.ensure_success()
        reports=export_backtest_reports(engine,Path(output_dir),venue=venue)
        return {"engine":"nautilus_trader","products":sorted(map(str,products)),**replay,
            "factor_roles":sorted(factor_bindings),"publications":{role:runtime.slice_count for role in factor_bindings},
            "factor_plan_nodes":runtime.node_count,"factor_actors":1,
            "strategy_publications":runtime.consumer_counts,"python_factor_bar_callbacks":0,
            "factor_refs":dict(factor_refs),"factor_output_slots":role_outputs,"rank_passes":runtime.rank_passes,"orders":engine.get_result().total_orders,"reports":reports}
    finally:
        engine.dispose()


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
    if plan.get("session_calendar") is None:
        try:
            from server.services.nautilus_bridge.catalog_staging import (
                build_run_spec_session_calendar,
            )
            plan["session_calendar"] = build_run_spec_session_calendar(
                catalogs=catalogs,
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
