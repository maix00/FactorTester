"""Data-node HTTP surface: enrolled Managers request bounded local chart data.

This is not a Manager. It exposes only one authenticated
market read backed by the node-owned provider; no Job DB or generic proxy.
"""
from __future__ import annotations
import importlib
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from server.identity.service_access import authenticate_service
from server.manager.http.federation.node_control import NodeControlRoutesMixin
from server.manager.http.responses import json_response
from traderesearch_data.execution import offer_from_dict


class NodeMarketHandler(NodeControlRoutesMixin, BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/execution/market/read":
            self.send_error(404); return
        try:
            body, payload = self._node_json_body(64*1024)
            manager = authenticate_service(self, required_scope="tr:market:read")
            registrations = [item for item in self.state.descriptors()
                             if item["target"]["manager_id"] == manager.manager_id]
            if len(registrations) != 1:
                raise PermissionError("Manager does not own this service registration")
            descriptor = registrations[0]
            principal = payload.get("principal")
            if not isinstance(principal, str) or principal not in manager.principals:
                raise PermissionError("delegated principal is required")
            product = payload.get("product_ref")
            offers = [offer_from_dict(item) for item in descriptor["offers"]]
            matches = [offer for offer in offers if offer.source_ref == payload.get("source_ref")
                       and offer.product_ref == product and offer.available
                       and offer.installation.owner in {"platform", principal}]
            if len(matches) != 1:
                raise PermissionError("source installation is unavailable or unauthorized")
            offer = matches[0]
            if payload.get("installation") != descriptor_offer(offer):
                raise ValueError("source installation changed; refresh selection")
            query = dict(payload.get("query") or {})
            allowed = {"start_date", "end_date", "chart_range", "chart_interval", "max_points", "adjusted", "chart_mode"}
            if set(query) - allowed:
                raise ValueError("unsupported chart request fields")
            maximum = query.get("max_points", 1000)
            if type(maximum) is not int or not 1 <= maximum <= 5000:
                raise ValueError("chart point budget is invalid")
            if not ((query.get("start_date") and query.get("end_date"))
                    or query.get("chart_range") in {"day", "month", "year", "ytd"}):
                raise ValueError("an explicit range or bounded recent range is required")
            if bool(query.get("adjusted")) != (offer.price_basis != "raw"):
                raise ValueError("price basis differs from selected source semantics")
            module, attribute = self.state.provider.split(":", 1)
            provider = getattr(importlib.import_module(module), attribute)
            # Provider owns product/source naming and actual I/O. The platform
            # adapter receives an exact offer, never a caller-selected path.
            value = provider(offer=offer, query=query)
            if not isinstance(value, dict) or not isinstance(value.get("data"), list):
                raise ValueError("market provider returned invalid chart data")
            if len(value["data"]) > maximum:
                raise ValueError("market provider exceeded point budget")
            value["source_ref"] = offer.source_ref
            value["node_id"] = offer.installation.node_id
            if len(json.dumps(value).encode()) > 4*1024**2:
                raise ValueError("chart response exceeds byte budget")
        except PermissionError as exc:
            json_response(self, {"success":False,"error":str(exc)},403); return
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            json_response(self, {"success":False,"error":str(exc)},422); return
        json_response(self, {"success":True, **value})

    def log_message(self, *_):
        pass


def descriptor_offer(offer):
    from dataclasses import asdict
    return asdict(offer.installation)
