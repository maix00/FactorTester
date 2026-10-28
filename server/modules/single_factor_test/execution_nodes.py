"""Authorized control-plane projection and explicit node input selection."""
import os
from flask import jsonify

from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
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
                       "target": capabilities["execution_target"], "market_read_available": bool(capabilities.get("market_endpoint")), "offers": [{**item, "source_ref": offer_from_dict(item).source_ref} for item in offers]})
    return values


def bind_prepared_execution(prepared, selection):
    if len(prepared["analyses"]) != 1:
        raise ValueError("an execution target requires exactly one test type")
    target = selection["target"]
    requirements = prepared["run_spec"].get("data_requirements") or []
    rows = visible_targets(prepared["owner"] if "owner" in prepared else require_user())
    from traderesearch_data.execution import offer_from_dict
    visible = {offer_from_dict(item).source_ref for row in rows if row["target"] == target
               for item in row["offers"]}
    if not set(selection["sources"].values()).issubset(visible):
        raise PermissionError("source installation is not visible to this user")
    selections = prepared["run_spec"].get("configuration", {}).get("shared", {}).get("product_selections", {})
    paths = {path for item in selections.values() for path in (item.get("paths") or item.get("selected_paths") or [])}
    if paths != {item["product_ref"] for item in requirements}:
        raise ValueError("Bar requirements must cover exactly the frozen product selection")
    expected = selection.get("expected_installations")
    if expected is not None:
        actual = {item["source_ref"]: item["installation"] for row in rows if row["target"] == target for item in row["offers"]}
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
