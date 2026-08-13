"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

from server.manager.http.responses import json_response

class FederationCapabilityRoutesMixin:
    def _federation_capabilities(self) -> None:
        """Return this Manager's data-source capability projection to a peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation capability is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(4 * 1024 * 1024)
            if not isinstance(payload, dict):
                raise ValueError("federation capability payload must be an object")
            value = self.state.local_capability_snapshot(payload)
            requested_port = payload.get("port")
            requested_branch = str(payload.get("branch") or "").strip()
            targets = self.state.local_service_routes(include_offline=False)
            if requested_port not in (None, ""):
                try:
                    requested_port = int(requested_port)
                except (TypeError, ValueError) as exc:
                    raise ValueError("capability port must be an integer") from exc
                targets = [
                    route for route in targets
                    if route.port == requested_port
                    and (not requested_branch or route.branch == requested_branch)
                ]
                if not targets:
                    raise ValueError(
                        "requested capability port is not online on this Manager"
                    )
            target = min(
                targets,
                key=self.state.route_selection_key,
                default=None,
            )
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "server_role": self.state.server_role,
            "target": (
                {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                    **target.as_dict(),
                }
                if target is not None else {
                    "server_id": self.state.server_id,
                    "server_role": self.state.server_role,
                }
            ),
            "ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=False,
                )
            ],
            **value,
        })
