"""FactorTester server-to-server control surface on WireGuard port 17998."""

from __future__ import annotations

import hmac
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from server.manager.http.federation_routes import FederationRoutesMixin
from server.manager.http.federation.node_control import NodeControlRoutesMixin
from server.manager.http.federation.transfers import TransferFederationRoutesMixin
from server.manager.http.responses import json_response


class PeerControlHandler(
    NodeControlRoutesMixin,
    TransferFederationRoutesMixin,
    FederationRoutesMixin,
    BaseHTTPRequestHandler,
):
    state: object

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            json_response(self, {
                "success": True,
                "service": "factor-peer-control",
                "server_id": self.state.server_id,
            })
            return
        if parsed.path == "/api/federation/node/challenge":
            self._node_challenge(parsed)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        handlers = {
            "/api/federation/register": self._federation_register,
            "/api/federation/sync/events": self._federation_sync_events,
            "/api/federation/jobs/query": self._federation_jobs_query,
            "/api/federation/sync/reconcile": self._federation_sync_reconcile,
            "/api/federation/proxy": self._federation_proxy,
            "/api/federation/stream": self._federation_stream,
            "/api/federation/capabilities": self._federation_capabilities,
            "/api/federation/node/enroll": self._node_enroll,
            "/api/federation/transfers/context": self._transfer_context_import,
            "/api/federation/transfers/origin-ticket": (
                self._transfer_origin_ticket
            ),
            "/api/federation/transfers/destination-ticket": (
                self._transfer_destination_ticket
            ),
        }
        selected = handlers.get(urlparse(self.path).path)
        if selected is None:
            self.send_error(404)
            return
        selected()

    def _has_federation_registration_token(self) -> bool:
        expected = str(self.state.federation_registration_token or "")
        supplied = self._bearer_token()
        return bool(expected and supplied and hmac.compare_digest(supplied, expected))

    def _has_federation_proxy_token(self) -> bool:
        expected = str(self.state.federation_proxy_token() or "")
        supplied = self._bearer_token()
        return bool(expected and supplied and hmac.compare_digest(supplied, expected))

    def _bearer_token(self) -> str:
        scheme, separator, supplied = str(
            self.headers.get("Authorization") or ""
        ).partition(" ")
        if not separator or scheme.lower() != "bearer":
            return ""
        return supplied.strip()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[peer-control] " + (fmt % args) + "\n")


def peer_control_handler(state):
    """Bind one state instance without sharing mutable class globals."""

    class BoundPeerControlHandler(PeerControlHandler):
        pass

    BoundPeerControlHandler.state = state
    return BoundPeerControlHandler
