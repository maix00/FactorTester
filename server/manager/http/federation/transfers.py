"""Signed Manager-to-Manager Transfer context and origin-ticket endpoints."""

from __future__ import annotations

import json

from server.manager.http.federation.node_auth import authenticated_node
from server.manager.http.responses import json_response
from server.manager.transfers.models import TransferMode
from server.manager.transfers.node_models import NewNodeCommand
from server.manager.transfers.wire import parse_transfer_context


class TransferFederationRoutesMixin:
    def _transfer_command_import(self) -> None:
        try:
            body, payload = self._node_json_body(640 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            command = payload.get("command")
            context = payload.get("context")
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported transfer command schema")
            if not isinstance(command, dict) or not isinstance(context, dict):
                raise ValueError("transfer command and context are required")
            transfer, attempt = parse_transfer_context(context)
            if identity.node_id != transfer.request_owner_manager_id:
                raise PermissionError("command sender is not request owner")
            if attempt.connection_owner_manager_id != self.state.server_id:
                raise PermissionError("command targets another connection owner")
            command_type = str(command.get("command_type") or "").strip()
            expected = {
                "source.push": (
                    TransferMode.SOURCE_PUSH, attempt.source_server_id,
                ),
                "destination.pull": (
                    TransferMode.DESTINATION_PULL,
                    attempt.destination_server_id,
                ),
            }.get(command_type)
            if expected is None or attempt.mode is not expected[0]:
                raise PermissionError("command type does not match Attempt mode")
            target = str(command.get("target_server_id") or "").strip()
            expected_target = expected[1]
            if target != expected_target:
                raise PermissionError("command target does not match Attempt")
            self.state.node_presence.require_live(target)
            record = self.state.node_control_hub.enqueue(NewNodeCommand(
                idempotency_key=str(command.get("idempotency_key") or ""),
                transfer_id=transfer.transfer_id,
                attempt_id=attempt.attempt_id,
                command_type=command_type,
                target_server_id=target,
                payload={"schema_version": 1, "context": context},
                expires_at=min(
                    float(command.get("expires_at") or 0),
                    transfer.expires_at,
                    attempt.expires_at,
                ),
            ))
        except (KeyError, PermissionError, ConnectionError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "command_id": record.command_id,
            "sequence": record.sequence,
        })

    def _transfer_context_import(self) -> None:
        try:
            body, payload = self._node_json_body(512 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            transfer, attempt = parse_transfer_context(payload)
            if identity.node_id != transfer.request_owner_manager_id:
                raise PermissionError(
                    "transfer context sender is not request owner"
                )
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
        try:
            body, payload = self._node_json_body(64 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            attempt_id = str(payload.get("attempt_id") or "").strip()
            issued = self.state.origin_ticket_issuer.issue(
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
            "role": "origin_read",
            "node_id": identity.node_id,
            "start_offset": attempt.resume_offset,
            "end_offset": attempt.expected_size,
        })

    def _transfer_producer_ticket(self) -> None:
        try:
            body, payload = self._node_json_body(64 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            attempt_id = str(payload.get("attempt_id") or "").strip()
            issued, endpoint = self.state.producer_ticket_issuer.issue(
                attempt_id=attempt_id,
                source_node_id=identity.node_id,
            )
            attempt = self.state.transfer_attempts.require(attempt_id)
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
            "role": "producer",
            "node_id": identity.node_id,
            "data_endpoint": endpoint,
            "path": f"/v1/transfers/{attempt.attempt_id}/producer",
            "start_offset": attempt.resume_offset,
            "end_offset": attempt.expected_size,
        })
