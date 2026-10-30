"""Enrollment and challenge routes shared by the peer-control listener."""

from __future__ import annotations

from server.manager.http.federation.node_values import query_value
from server.manager.http.responses import json_response
from server.manager.http.request_security import read_json_object


class NodeControlRoutesMixin:
    def _node_enroll(self) -> None:
        if not self._has_federation_registration_token():
            json_response(self, {
                "success": False,
                "error": "node enrollment is unauthorized",
            }, 401)
            return
        try:
            identity = self.state.node_identities.enroll(
                self._json_body(64 * 1024),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "node": {
                "node_id": identity.node_id,
                "algorithm": identity.algorithm,
                "fingerprint": identity.fingerprint,
                "enrolled_at": identity.enrolled_at,
            },
        })

    def _node_challenge(self, parsed) -> None:
        try:
            challenge = self.state.node_authenticator.issue_challenge(
                query_value(parsed, "node_id"),
            )
        except (KeyError, PermissionError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        json_response(self, {
            "success": True,
            "challenge_id": challenge.challenge_id,
            "challenge": challenge.challenge,
            "expires_at": challenge.expires_at,
        }, headers={"Cache-Control": "no-store"})

    def _node_json_body(self, maximum: int) -> tuple[bytes, dict[str, object]]:
        return read_json_object(self, maximum)

    def _json_body(self, maximum: int) -> dict[str, object]:
        return self._node_json_body(maximum)[1]
