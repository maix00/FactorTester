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
    if not bindings or set(refs) != set(bindings) or "signal" not in bindings:
        raise ValueError("factor roles must exactly bind frozen refs and include signal")
    expressions = {}
    for role, expression in bindings.items():
        ref = refs[role]
        if ref in expressions and expressions[ref].semantic_fingerprint() != expression.semantic_fingerprint():
            raise ValueError("one frozen factor ref resolved to conflicting expressions")
        expressions[ref] = expression
    spec,output_by_ref=_compile_frozen_roots(expressions,products,calendar)
    return spec, {role: output_by_ref[ref] for role, ref in refs.items()}


def _compile_frozen_roots(expressions,products,calendar):
    from tools.factors.expr.streaming.rust_incremental import shared_factor_plan_spec
    spec,_=shared_factor_plan_spec(expressions,products,source_freq=DataFreq.MIN1,session_calendar=calendar)
    return spec,{ref:i for i,ref in enumerate(expressions)}


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


def _family_rule(family):
    if isinstance(family,CrossSectionalGroup):
        return {"kind":"cross_sectional_group",**asdict(family)}
    if isinstance(family,ThresholdState):
        return {"kind":"threshold",**asdict(family)}
    raise ValueError("unsupported native strategy family")


def _build_strategy_family_engine(execution_plan, instruments, *, by_strategy=None):
    from nautilus_trader.model import Venue
    from server.services.nautilus_bridge.engine_factory import build_backtest_engine
    if by_strategy is None:
        if len(execution_plan.strategy_venue_bindings)!=1:
            raise ValueError('multiple strategy routes require explicit per-strategy instruments')
        by_strategy={str(execution_plan.strategy_venue_bindings[0]['strategy_id']):instruments}
    # NETTING exposes one position per instrument; independent target strategies
    # sharing that position cannot use per-strategy position attribution.
    for venue in execution_plan.venues if len(by_strategy)>1 else []:
        if str(venue.get("oms_type","NETTING")).upper()=="NETTING":
            seen=set()
            for rows in by_strategy.values():
                ids={str(x.id) for x in rows if str(x.id.venue).upper()==str(venue["name"]).upper()}
                if seen & ids:raise ValueError("overlapping per-strategy targets require Nautilus HEDGING OMS")
                seen.update(ids)
    engine=build_backtest_engine(execution_plan,by_strategy,trader_id="TR-STRATEGY-001")
    return engine,Venue.from_str(sorted(str(x['name']).upper() for x in execution_plan.venues)[0])


def run_strategy_family_replay(*,inputs,factor_bindings,factor_refs,family,output_dir,
    max_bars=8,execution_plan=None,session_calendar=None,batch_minutes=20,trace_path=None):
    """Single-family compatibility view over the one shared runtime."""
    strategy_id=(str(execution_plan.strategy_venue_bindings[0]['strategy_id'])
                 if execution_plan is not None else 'FactorFamily-000')
    result=run_strategy_families_replay(inputs=inputs,strategies=[dict(strategy_id=strategy_id,
        factor_bindings=factor_bindings,factor_refs=factor_refs,family=family)],output_dir=output_dir,
        max_bars=max_bars,execution_plan=execution_plan,session_calendar=session_calendar,
        batch_minutes=batch_minutes,trace_path=trace_path)
    slots=result['strategy_output_slots'][strategy_id]
    return {**result,'factor_roles':sorted(factor_bindings),
        'publications':{role:result['slices'] for role in factor_bindings},
        'factor_refs':dict(factor_refs),'factor_output_slots':slots}


def run_strategy_families_replay(*,inputs,strategies,output_dir,max_bars=8,execution_plan=None,
    session_calendar=None,batch_minutes=20,trace_path=None,inspect_outputs=False):
    """One Catalog replay and CSE Actor for every compatible native consumer."""
    from nautilus_trader._libnautilus import attach_factor_family
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.execution import MakerTakerFeeModel
    from nautilus_trader.model import AccountType,Currency,Money,OmsType,TraderId,Venue
    if not strategies:raise ValueError('at least one native strategy is required')
    products=tuple(inputs);seen=set();native_ids=set();roots={};role_refs={};consumers=[];scopes={}
    for strategy in strategies:
        identity=str(strategy['strategy_id'])
        if not identity or identity in seen:raise ValueError('duplicate or empty strategy id')
        seen.add(identity)
        native_id=identity if '-' in identity else identity+'-000'
        if native_id in native_ids:raise ValueError('strategy ids collide after Nautilus normalization')
        native_ids.add(native_id)
        bindings=strategy['factor_bindings'];refs=strategy['factor_refs']
        if set(bindings)!=set(refs) or 'signal' not in refs:raise ValueError('factor roles must exactly bind frozen refs and include signal')
        for role,expr in bindings.items():
            ref=str(refs[role])
            if not ref.startswith('factor:v2:'):raise ValueError('factor roles must use frozen factor:v2 refs')
            if ref in roots and roots[ref].semantic_fingerprint()!=expr.semantic_fingerprint():
                raise ValueError('one frozen factor ref resolved to conflicting expressions')
            roots[ref]=expr
        role_refs[identity]=refs
        selected=strategy.get('products')
        chosen=products if selected is None else tuple(selected)
        if not chosen:raise ValueError('strategy product scope must not be empty')
        if len(set(chosen))!=len(chosen) or not set(chosen)<=set(products):raise ValueError('strategy product scope is outside frozen inputs')
        scopes[identity]=chosen
        consumers.append(dict(strategy_id=native_id,
            rule=_family_rule(strategy['family']),product_indices=[products.index(p) for p in chosen]))
    spec,slots=_compile_frozen_roots(roots,products,session_calendar)
    from alpha.factor.spec import scope_plan_outputs
    requests=[];requested_roles=[]
    for consumer,strategy in zip(consumers,strategies,strict=True):
        for role,ref in strategy['factor_refs'].items():
            requests.append((slots[ref],consumer['product_indices']))
            requested_roles.append((strategy['strategy_id'],role))
    spec,scoped_slots=scope_plan_outputs(spec,requests,len(products))
    strategy_slots={identity:{} for identity in role_refs}
    for (identity,role),slot in zip(requested_roles,scoped_slots,strict=True):strategy_slots[identity][role]=slot
    for consumer,strategy in zip(consumers,strategies,strict=True):
        consumer['signal_output']=strategy_slots[strategy['strategy_id']]['signal']
    opened={product:_load_input(item) for product,item in inputs.items()}
    preflight_catalogs(opened.values(),max_input_bars=max_bars*len(opened))
    instruments=[row[3] for row in opened.values()]
    by_strategy={identity:[opened[p][3] for p in scope] for identity,scope in scopes.items()}
    if execution_plan is not None:
        engine,venue=_build_strategy_family_engine(execution_plan,instruments,by_strategy=by_strategy)
    else:
        engine=BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId.from_str('TR-STRATEGY-001')))
        venue=Venue('CFFEX')
        engine.add_venue(venue=venue,oms_type=OmsType.HEDGING if len(strategies)>1 else OmsType.NETTING,
            account_type=AccountType.MARGIN,base_currency=Currency.from_str('CNY'),
            starting_balances=[Money.from_str('1000000 CNY')],
            fee_model=MakerTakerFeeModel(maker_rate=Decimal(0),taker_rate=Decimal(0)))
        for instrument in instruments:engine.add_instrument(instrument)
    try:
        runtime=attach_factor_family(engine=engine,plan_json=json.dumps(spec),products=list(map(str,products)),
            bar_types=[str(row[2]['bar_type']) for row in opened.values()],consumers_json=json.dumps(consumers),
            calendar_json=json.dumps([(x.start_ns,x.end_ns) for x in session_calendar.sessions] if session_calendar else []),
            trace_path=None if trace_path is None else str(trace_path))
        try:
            replay=replay_catalog_batches(engine,opened.values(),max_input_bars=max_bars*len(opened),batch_minutes=batch_minutes)
        except Exception:
            runtime.raise_if_failed();raise
        runtime.ensure_success()
        reports=export_backtest_reports(engine,Path(output_dir),venue=venue)
        latest={identity:{role:runtime.latest_output(slot) for role,slot in outputs.items()} for identity,outputs in strategy_slots.items()} if inspect_outputs else {}
        return dict(latest_outputs=latest,engine='nautilus_trader',products=sorted(map(str,products)),**replay,slices=runtime.slice_count,
            factor_plan_nodes=runtime.node_count,factor_actors=1,strategy_publications=runtime.consumer_counts,
            python_factor_bar_callbacks=0,rank_passes=runtime.rank_passes,
            strategy_output_slots=strategy_slots,
            strategy_factor_refs=role_refs,strategy_runtime_ids=dict(runtime.consumer_strategy_ids),orders=engine.get_result().total_orders,reports=reports)
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

    templates=plan.get('strategy_families')
    if templates is None:templates=[plan.get('strategy')]
    if not isinstance(templates,list) or not templates or any(not isinstance(x,dict) for x in templates):
        raise ValueError('strategy plan is missing')
    shared=((job_spec.get('run_spec') or {}).get('configuration') or {}).get('shared') or {}
    resolver=RunFactorResolver(owner=str(job_spec.get('_owner') or job_spec.get('owner') or ''),
        frozen_factors=shared.get('factors') or [],external_factor_artifacts=shared.get('external_factor_artifacts'))
    resolved_factors={};consumers=[]
    for i,template in enumerate(templates):
        kind=str(template.get('kind') or '');parameters=template.get('parameters') or {}
        if kind=='cross_sectional_group':
            family=CrossSectionalGroup(int(parameters.get('split_count') or 0),int(parameters.get('group_index') or 0))
        elif kind=='threshold':
            family=ThresholdState(float(parameters.get('entry_threshold') or 0),float(parameters.get('exit_threshold') or 0),str(parameters.get('side_mode') or 'long_short'))
        else:raise ValueError(f'unsupported strategy family: {kind}')
        roles=template.get('factor_roles')
        if not isinstance(roles,dict) or not roles:raise ValueError('strategy has no factor role bindings')
        bindings={};factor_refs={}
        for role,binding in roles.items():
            if not isinstance(binding,dict):raise ValueError(f'factor role {role!r} has an invalid binding')
            ref=str(binding.get('ref') or '')
            if not ref.startswith('factor:v2:'):raise ValueError(f'factor role {role!r} must freeze its immutable ref')
            if ref not in resolved_factors:
                factor=resolver.resolve(factor_ref=ref,alias=str(binding.get('alias') or ''))
                expression=getattr(factor,'expr',None)
                if expression is None:raise ValueError(f'factor role {role!r} has no FactorExpr')
                resolved_factors[ref]=expression
            bindings[str(role)]=resolved_factors[ref];factor_refs[str(role)]=ref
        if 'signal' not in bindings and len(bindings)==1:
            role=next(iter(bindings));bindings={'signal':bindings[role]};factor_refs={'signal':factor_refs[role]}
        consumers.append(dict(strategy_id=str(template.get('strategy_id') or f'FactorFamily-{i:03}'),
            family=family,factor_bindings=bindings,factor_refs=factor_refs,products=template.get('products') or None))
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
    aliases={key:key for key in inputs}
    aliases.update({value.expected_contract_uid:key for key,value in inputs.items()})
    selections=shared.get('product_selections') or {}
    routes={str(row['strategy_id']):row for row in execution_plan.strategy_venue_bindings} if execution_plan else {}
    for consumer in consumers:
        selected=consumer.get('products')
        route=routes.get(consumer['strategy_id'])
        if not selected and route:
            refs=route.get('product_scope_refs') or []
            selected=[path for ref in refs for path in (selections.get(ref,{}).get('paths') or selections.get(ref,{}).get('selected_paths') or [])]
        if selected:
            unknown=set(selected)-set(aliases)
            if unknown:raise ValueError(f'strategy scope has no frozen catalog: {sorted(unknown)}')
            consumer['products']=list(dict.fromkeys(aliases[x] for x in selected))
    common=dict(inputs=inputs,output_dir=Path(output_dir),max_bars=int(plan.get('max_input_bars') or 8),
                execution_plan=execution_plan,session_calendar=plan.get('session_calendar'))
    if len(consumers)==1 and 'strategy_families' not in plan:
        consumer=consumers[0]
        return run_strategy_family_replay(**common,factor_bindings=consumer['factor_bindings'],
            factor_refs=consumer['factor_refs'],family=consumer['family'])
    return run_strategy_families_replay(**common,strategies=consumers)
