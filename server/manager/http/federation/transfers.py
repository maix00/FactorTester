"""Signed peer-only Transfer context and ticket endpoints on port 17998."""

from __future__ import annotations

import json

from server.manager.http.federation.node_auth import authenticated_node
from server.manager.http.responses import json_response
from server.manager.transfers.wire import parse_transfer_context


class TransferFederationRoutesMixin:
    def _transfer_context_import(self) -> None:
        try:
            body, payload = self._node_json_body(512 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            transfer, attempt = parse_transfer_context(payload)
            if identity.node_id != transfer.request_owner_manager_id:
                raise PermissionError("transfer context sender is not request owner")
            self.state.transfer_replicas.import_context(transfer, attempt)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "transfer_id": transfer.transfer_id,
            "attempt_id": attempt.attempt_id,
        })

    def _transfer_origin_ticket(self) -> None:
        self._transfer_peer_ticket(kind="origin")

    def _transfer_destination_ticket(self) -> None:
        self._transfer_peer_ticket(kind="destination")

    def _transfer_peer_ticket(self, *, kind: str) -> None:
        try:
            body, payload = self._node_json_body(64 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            attempt_id = str(payload.get("attempt_id") or "").strip()
            issuer = (
                self.state.origin_ticket_issuer
                if kind == "origin"
                else self.state.destination_ticket_issuer
            )
            issued = issuer.issue(
                attempt_id=attempt_id,
                requester_node_id=identity.node_id,
            )
            _transfer, attempt = self.state.transfer_replicas.require_context(
                attempt_id,
            )
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "bearer": issued.bearer,
            "attempt_id": attempt.attempt_id,
            "role": "origin_read" if kind == "origin" else "destination_write",
            "node_id": identity.node_id,
            "start_offset": attempt.resume_offset,
            "end_offset": attempt.expected_size,
        })
