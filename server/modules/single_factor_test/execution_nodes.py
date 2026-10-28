"""Authorized control-plane projection and explicit node input selection."""
import os
from flask import jsonify

from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.jobs.assurance import canonical_hash
from server.modules.single_factor_test import sft_bp
from server.services.session_runtime import require_user


def node_service():
    manager_id = os.environ.get("FACTORTESTER_SERVER_ID", "").strip()
    if not manager_id:
        raise ValueError("Manager identity must be configured")
    return ExecutionNodeService(JobRepository(), manager_id=manager_id)


def visible_targets(owner):
    # Do not expose another user's installations through global target metadata.
    from traderesearch_data.execution import offer_from_dict
    values = []
    for row in node_service().directory():
        capabilities = row["capabilities"]
        offers = [offer for offer in capabilities["offers"]
                  if offer["installation"]["owner"] in {"platform", owner}]
        values.append({"route_id": row["deployment_id"], "service_port": row["service_port"],
                       "online": row["online"], "expires_at": row["expires_at"],
                       "target": capabilities["execution_target"], "runtime_adapters": {key:value for key,value in capabilities.get("runtime_adapters",{}).items() if key in {offer_from_dict(item).source_ref for item in offers}}, "market_read_available": bool(capabilities.get("market_endpoint")), "offers": [{**item, "source_ref": offer_from_dict(item).source_ref} for item in offers]})
    return values


def bind_prepared_execution(prepared, selection):
    if len(prepared["analyses"]) != 1:
        raise ValueError("an execution target requires exactly one test type")
    requirements = prepared["run_spec"].get("data_requirements") or []
    owner = prepared.get("owner") or require_user()
    rows = visible_targets(owner)
    bundles = selection.get("bundles")
    if bundles is not None:
        keys = {(item["bundle_id"],item["owner"]) for item in bundles}
        if not keys:raise ValueError("select at least one Bundle")
        rows = [{**row,"offers":[offer for offer in row["offers"] if (offer["installation"]["bundle_id"],offer["installation"]["owner"]) in keys]} for row in rows]
    from traderesearch_data.execution import offer_from_dict, requirement_from_dict, deployment_from_dict, compatible_bar_offers
    if selection.get("mode") == "auto":
        if selection.get("manager_id") != node_service().manager_id:
            raise PermissionError("automatic matching is scoped to the selected Manager")
        matches = []
        for row in sorted(rows, key=lambda item: item["route_id"]):
            if not row["online"] or prepared["analyses"][0] not in row["target"]["test_types"]:
                continue
            offers = tuple(offer_from_dict(item) for item in row["offers"])
            sources = {}
            for raw in requirements:
                requirement = requirement_from_dict(raw)
                compatible = compatible_bar_offers(requirement, deployment_from_dict(row["target"]), offers)
                if not compatible:
                    break
                sources[requirement.product_ref] = min(compatible, key=lambda item: item.source_ref).source_ref
            else:
                try:
                    binding = node_service().bind(target=row["target"], requirements=requirements,
                        selections=sources, test_type=prepared["analyses"][0])
                except ValueError:
                    continue
                matches.append(binding)
        if not matches:
            raise ValueError("no authorized online node satisfies all configured Bar requirements")
        selected = matches[0]
        selection = {"target": selected["target"],
                     "sources": {item["requirement"]["product_ref"]: item["source_ref"] for item in selected["inputs"]}}
    target = selection["target"]
    if "sources" not in selection:
        offers = tuple(offer_from_dict(item) for row in rows if canonical_hash(row["target"]) == canonical_hash(target) for item in row["offers"])
        sources = {}
        for raw in requirements:
            requirement = requirement_from_dict(raw)
            compatible = compatible_bar_offers(requirement,deployment_from_dict(target),offers)
            if not compatible:raise ValueError("selected Bundles do not cover the complete configured product group")
            sources[requirement.product_ref] = min(compatible,key=lambda offer:offer.source_ref).source_ref
        selection = {**selection,"sources":sources}
    visible = {offer_from_dict(item).source_ref for row in rows if canonical_hash(row["target"]) == canonical_hash(target)
               for item in row["offers"]}
    if not set(selection["sources"].values()).issubset(visible):
        raise PermissionError("source installation is not visible to this user")
    selections = prepared["run_spec"].get("configuration", {}).get("shared", {}).get("product_selections", {})
    paths = {path for item in selections.values() for path in (item.get("paths") or item.get("selected_paths") or [])}
    if paths != {item["product_ref"] for item in requirements}:
        raise ValueError("Bar requirements must cover exactly the frozen product selection")
    expected = selection.get("expected_installations")
    if expected is not None:
        actual = {item["source_ref"]: item["installation"] for row in rows if canonical_hash(row["target"]) == canonical_hash(target) for item in row["offers"]}
        if set(expected) != set(selection["sources"].values()) or any(actual.get(ref) != install for ref, install in expected.items()):
            raise ValueError("selected installation changed; refresh execution targets")
    return node_service().bind(target=target, requirements=requirements,
                               selections=selection["sources"], test_type=prepared["analyses"][0])


@sft_bp.get("/api/test-authoring/execution-targets")
def execution_targets():
    return jsonify({"success": True, "manager_id": node_service().manager_id,
                    "targets": visible_targets(require_user())})


def peer_execution_route(state, manager_id):
    """Manager control capability, independent of business ports/proxy secrets."""
    from server.manager.domain.federation import ServiceRoute
    peers = [item for item in state.federation_registry.servers(include_offline=False)
             if item.get("server_id") == manager_id]
    if len(peers) != 1:
        raise PermissionError("selected Manager is offline or unauthorized")
    peer = peers[0]
    endpoint = (peer.get("transfer_node") or {}).get("peer_control_endpoint")
    if not endpoint:
        raise ValueError("selected Manager does not advertise a control endpoint")
    return ServiceRoute(server_id=manager_id, role=peer.get("role", ""),
        branch=peer.get("branch", ""), revision=peer.get("revision", ""), port=0,
        peer_control_endpoint=endpoint, remote=True, online=True)


def requirements_for_configuration(configuration, selection, directory):
    """Derive all product/Bar/time inputs from configuration, never picker rows."""
    from dataclasses import asdict
    from datetime import datetime
    from traderesearch_data.execution import BarRequirement
    from server.services.nautilus_bridge.run_spec import _utc_window
    payload=configuration["payload"]
    backtest=payload["analyses"].get("backtest") or {}
    settings=(backtest.get("execution") or {}).get("settings") or {}
    if settings.get("start_utc") and settings.get("end_utc"):
        window={key:settings[key] for key in ("start_utc","end_utc")}
    else:
        window,reason=_utc_window(settings)
        if window is None:raise ValueError(reason)
    def ns(value):
        import pandas as pd
        stamp=pd.Timestamp(value)
        if stamp.tz is None:raise ValueError("configuration time bounds require a timezone")
        return stamp.value
    start,end=ns(window["start_utc"]),ns(window["end_utc"])
    warmup=settings.get("factor_warmup") or {}
    if warmup.get("mode")=="custom":start=ns(warmup["data_start_utc"])
    bundles={(item["bundle_id"],item["owner"]) for item in selection.get("bundles") or []}
    if not bundles:raise ValueError("select at least one Bundle")
    rows=[row for row in directory if row["online"] and (selection.get("mode")=="auto" or canonical_hash(row["target"])==canonical_hash(selection.get("target")))]
    products=sorted({path for group in payload["shared"].get("product_selections",{}).values() for path in (group.get("paths") or group.get("selected_paths") or [])})
    if not products:raise ValueError("strategy must define a frozen product group")
    frequency=str(settings.get("freq_fixed") or "").upper()
    requirements=[]
    for product in products:
        offers=[offer for row in rows for offer in row["offers"] if offer["available"] and offer["product_ref"]==product
                and (offer["installation"]["bundle_id"],offer["installation"]["owner"]) in bundles
                and (not frequency or row.get("runtime_adapters",{}).get(offer["source_ref"],{}).get("frequency")==frequency)]
        contracts={(offer["bar_spec"],offer["price_basis"],offer["time_semantics"]) for offer in offers}
        if len(contracts)!=1:raise ValueError(f"{product}: configure one supported Bar frequency and price/time contract")
        bar,price,timing=next(iter(contracts))
        fields=tuple(sorted(set.intersection(*(set(offer["fields"]) for offer in offers))))
        if not {"open","high","low","close","volume"}.issubset(fields):raise ValueError("selected Bundle has no complete OHLCV contract")
        requirements.append(asdict(BarRequirement(product,bar,price,timing,fields,start,end)))
    return requirements
