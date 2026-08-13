"""Authenticated 7998 control endpoints for one outbound node channel."""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

from server.manager.http.federation.node_auth import authenticated_node
from server.manager.http.federation.node_values import (
    command_response,
    query_value,
    reachability,
)
from server.manager.http.responses import json_response
from server.manager.transfers.node_models import NodeConnection
from server.manager.transfers.node_protocol import sse_command


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

    def _node_control_poll(self) -> None:
        try:
            body, payload = self._node_json_body(256 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            self.state.node_control_hub.observe_poll(
                node_id=identity.node_id,
                data_endpoint=str(payload.get("data_endpoint") or ""),
                reachable_from=reachability(payload.get("reachable_from")),
            )
            values = self.state.node_control_hub.poll(
                node_id=identity.node_id,
                after_sequence=int(payload.get("after_sequence") or 0),
                timeout=float(payload.get("timeout") or 0),
            )
        except (KeyError, PermissionError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, command_response(values))

    def _node_control_ack(self) -> None:
        try:
            body, payload = self._node_json_body(64 * 1024)
            identity = authenticated_node(self, method="POST", body=body)
            self.state.node_commands.acknowledge(
                str(payload.get("command_id") or ""),
                node_id=identity.node_id,
            )
        except (KeyError, PermissionError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True})

    def _node_control_stream(self, parsed) -> None:
        try:
            identity = authenticated_node(self, method="GET", body=b"")
            data_endpoint = query_value(parsed, "data_endpoint")
            reachable = reachability(query_value(
                parsed, "reachable_from", required=False,
            ))
            after = max(0, int(self.headers.get("Last-Event-ID") or 0))
        except (KeyError, PermissionError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        connection = self.state.node_control_hub.attach(
            node_id=identity.node_id,
            data_endpoint=data_endpoint,
            reachable_from=reachable,
        )
        self._send_node_stream(connection, after_sequence=after)

    def _send_node_stream(
        self,
        connection: NodeConnection,
        *,
        after_sequence: int,
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        cursor = after_sequence
        replay = True
        last_presence = 0.0
        try:
            while self.state.node_control_hub.is_current(connection):
                values = self.state.node_control_hub.poll(
                    node_id=connection.node_id,
                    after_sequence=cursor,
                    timeout=15.0,
                    include_replay=replay,
                )
                replay = False
                if values:
                    for value in values:
                        self.wfile.write(sse_command(value))
                        cursor = max(cursor, value.sequence)
                    self.wfile.flush()
                else:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                current = time.time()
                if current - last_presence >= 10.0:
                    self.state.node_control_hub.refresh(
                        connection,
                        data_endpoint=self.state.node_presence.require_live(
                            connection.node_id, now=current,
                        ).data_endpoint,
                        reachable_from=self.state.node_presence.require_live(
                            connection.node_id, now=current,
                        ).reachable_from,
                        now=current,
                    )
                    last_presence = current
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            self.state.node_control_hub.detach(connection)

    def _node_json_body(self, maximum: int) -> tuple[bytes, dict[str, object]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > maximum:
            raise ValueError("request body is invalid")
        body = self.rfile.read(length)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return body, value
