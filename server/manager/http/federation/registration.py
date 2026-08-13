"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import os
import sys
from server.manager.http.responses import json_response


_CATALOG_FIELDS = {
    "schema_version",
    "server_id",
    "role",
    "branch",
    "revision",
    "features",
    "ports",
    "load",
    "lease_seconds",
    "transfer_node",
}


def _catalog_entry(value: dict[str, object]) -> dict[str, object]:
    """Project public discovery metadata without any routing credential."""
    return {
        key: item
        for key, item in value.items()
        if key in _CATALOG_FIELDS
    }


class FederationRegistrationRoutesMixin:
    def _federation_register(self) -> None:
        if not self._has_federation_registration_token():
            json_response(
                self,
                {"success": False, "error": "federation registration is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(512 * 1024)
            value = self.state.accept_federation_registration(payload)
        except (PermissionError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        public = {
            key: item
            for key, item in value.items()
            if key not in {"proxy_token"}
        }
        advertised_endpoint = os.environ.get(
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", ""
        ).strip().rstrip("/")
        peer = None
        try:
            peer = self.state.federation_registration_payload(
                advertised_endpoint,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            sys.stderr.write(f"[federation] peer descriptor unavailable: {exc}\n")
        joining_server_id = str(value.get("server_id") or "").strip()
        catalog_by_id: dict[str, dict[str, object]] = {}
        if isinstance(peer, dict):
            catalog_by_id[self.state.server_id] = peer
        for node in self.state.federation_registry.servers(
            include_offline=False,
        ):
            node_id = str(node.get("server_id") or "").strip()
            if (
                not node_id
                or node_id == joining_server_id
                or node_id == self.state.server_id
            ):
                continue
            catalog_by_id[node_id] = node
        # Registration is service discovery only; task summaries are on-demand.
        json_response(self, {
            "success": True,
            "server": public,
            "bootstrap_server_id": self.state.server_id,
            # The authenticated bootstrap distributes a multi-node directory.
            # A joining server configures one bootstrap, while routing remains
            # keyed by stable server_id and can grow beyond the current pair.
            "nodes": [
                _catalog_entry(catalog_by_id[node_id])
                for node_id in sorted(catalog_by_id)
            ],
            # This is returned only over the already authenticated
            # registration channel.  It lets the caller route back to this
            # Manager's fixed service (normally remote 8000) without exposing
            # any service port directly. Kept for schema-v1 callers.
            "peer": peer,
        })
