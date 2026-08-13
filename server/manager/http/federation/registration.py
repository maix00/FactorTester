"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import os
import sys
from server.manager.http.responses import json_response

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
            advertisement = payload.get("transfer_node")
            if not isinstance(advertisement, dict):
                raise ValueError("transfer node advertisement is required")
            self.state.accept_transfer_node_advertisement(advertisement)
            value = self.state.federation_registry.register(payload)
        except (PermissionError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        public = {
            key: item
            for key, item in value.items()
            if key not in {"proxy_token"}
        }
        forwarded_proto = str(
            self.headers.get("X-Forwarded-Proto") or "http"
        ).split(",", 1)[0].strip().lower()
        if forwarded_proto not in {"http", "https"}:
            forwarded_proto = "http"
        advertised_endpoint = os.environ.get(
            "FACTORTESTER_MANAGER_PUBLIC_ENDPOINT", ""
        ).strip().rstrip("/")
        if not advertised_endpoint:
            host = str(self.headers.get("Host") or "").strip()
            if host:
                advertised_endpoint = f"{forwarded_proto}://{host}"
        peer = None
        if advertised_endpoint:
            try:
                federation_config = self.state.federation_config()
                peer = self.state.peer_registration_payload(
                    advertised_endpoint,
                )
            except (OSError, RuntimeError, ValueError) as exc:
                sys.stderr.write(f"[federation] peer descriptor unavailable: {exc}\n")
        # Registration is service discovery only; task summaries are on-demand.
        json_response(self, {
            "success": True,
            "server": public,
            # This is returned only over the already authenticated
            # registration channel.  It lets the caller route back to this
            # Manager's fixed service (normally remote 8000) without exposing
            # any service port directly.
            "peer": peer,
        })
