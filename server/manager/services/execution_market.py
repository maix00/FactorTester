"""Locate an authorized node installation and forward only bounded chart reads."""
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.identity.service_access import ServiceHTTPClient, configured_client
from traderesearch_data.execution import offer_from_dict
from dataclasses import asdict


def read_node_market(state, *, principal, payload):
    service = ExecutionNodeService(getattr(state, "job_repository", None) or JobRepository(), manager_id=state.server_id)
    rows = [row for row in service.directory() if row["deployment_id"] == payload.get("route_id")
            and row["online"]]
    if len(rows) != 1:
        raise ValueError("selected data node is offline or unavailable")
    cap = rows[0]["capabilities"]
    matches = [offer_from_dict(item) for item in cap["offers"]
               if offer_from_dict(item).source_ref == payload.get("source_ref")
               and item["product_ref"] == payload.get("product_ref")
               and item["installation"]["owner"] in {"platform", principal}]
    if len(matches) != 1:
        raise PermissionError("source installation is unavailable or unauthorized")
    endpoint = cap.get("market_endpoint")
    if not endpoint:
        raise ValueError("selected node does not provide market reads")
    client = ServiceHTTPClient(endpoint, oidc=configured_client("TR_MARKET_OIDC"), response_limit=4*1024**2)
    query = {key: value for key, value in payload.items() if key in {
        "start_date", "end_date", "chart_range", "chart_interval", "max_points", "adjusted", "chart_mode"}}
    maximum = query.get("max_points", 1000)
    if type(maximum) is not int or not 1 <= maximum <= 5000:
        raise ValueError("invalid chart point budget")
    value = client.post_json("/api/execution/market/read", {
        "principal": principal, "product_ref": matches[0].product_ref,
        "source_ref": matches[0].source_ref, "installation": asdict(matches[0].installation),
        "query": query})
    if (value.get("source_ref") != matches[0].source_ref
            or value.get("node_id") != matches[0].installation.node_id
            or not isinstance(value.get("data"), list) or len(value["data"]) > maximum):
        raise ValueError("node returned mismatched or excessive chart data")
    return value
