"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import json
import time

from server.identity.federation_identity_sync import (
    IdentitySyncTransitionError,
    assert_destination_sync_can_be_disabled,
    manager_keycloak_admin_adapter,
    verify_identity_sync_disable_signature,
)
from server.identity.realm_groups import organization_group_path
from server.manager.http.responses import json_response


class FederationSyncRoutesMixin:
    def _federation_identity_sync_check_disable(self) -> None:
        """Return a one-time public-Keycloak decision for an internal Manager."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        if not bool(getattr(self.state, "public_server", False)):
            json_response(
                self,
                {"success": False, "error": "public Manager verification required"},
                403,
            )
            return
        try:
            payload = self._json_body(16 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            group_path = str(payload.get("group_path") or "").strip()
            issued_at = payload.get("issued_at")
            request_id = str(payload.get("request_id") or "")
            signature = str(payload.get("signature") or "")
            if (
                not requester
                or requester == self.state.server_id
                or type(issued_at) is not int
                or not group_path
                or set(payload) != {
                    "requester_server_id", "group_path", "issued_at",
                    "request_id", "signature",
                }
            ):
                raise ValueError("invalid identity-sync verification request")
            peer = self.state.federation_registry.describe(requester)
            if not isinstance(peer, dict):
                json_response(self, {
                    "success": False,
                    "error": "requesting Manager is not registered",
                }, 403)
                return
            if bool(peer.get("public_server", peer.get("role") == "main")):
                json_response(self, {
                    "success": False,
                    "error": "requesting Manager must be internal",
                }, 403)
                return
            live_peer = next((
                row for row in self.state.federation_registry.servers(
                    include_offline=True,
                ) if str(row.get("server_id") or "") == requester
            ), None)
            if not isinstance(live_peer, dict) or not bool(live_peer.get("online")):
                json_response(self, {
                    "success": False,
                    "error": "requesting Manager is offline",
                }, 409)
                return
            managed_paths = {
                organization_group_path(str(value))
                for value in peer.get("managed_organizations") or ()
                if str(value or "").strip()
            }
            if group_path not in managed_paths:
                json_response(self, {
                    "success": False,
                    "error": "organization is outside requesting Manager scope",
                }, 403)
                return
            peer_secret = str(peer.get("proxy_token") or "").strip()
            if not peer_secret or not verify_identity_sync_disable_signature(
                peer_secret,
                requester_server_id=requester,
                group_path=group_path,
                issued_at=issued_at,
                request_id=request_id,
                signature=signature,
                now=time.time(),
            ):
                json_response(self, {
                    "success": False,
                    "error": "requesting Manager proof is invalid or expired",
                }, 403)
                return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return

        try:
            from server.identity.user_session import oidc_settings

            assert_destination_sync_can_be_disabled(
                manager_keycloak_admin_adapter(),
                group_path=group_path,
                roles_client_id=oidc_settings()["roles_client_id"],
            )
        except IdentitySyncTransitionError as exc:
            json_response(self, {
                "success": True,
                "allowed": False,
                "requester_server_id": requester,
                "group_path": group_path,
                "request_id": request_id,
                "reason": str(exc),
            })
            return
        except Exception as exc:  # noqa: BLE001
            json_response(self, {
                "success": False,
                "code": "keycloak_sync_verification_unavailable",
                "error": type(exc).__name__,
            }, 503)
            return
        json_response(self, {
            "success": True,
            "allowed": True,
            "requester_server_id": requester,
            "group_path": group_path,
            "request_id": request_id,
        })

    def _federation_sync_events(self) -> None:
        """Serve the local Manager event stream to an authenticated peer."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            after_sequence = int(payload.get("after_sequence") or 0)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if after_sequence < 0:
                raise ValueError("after_sequence must not be negative")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            value = self.state.job_index.events_for_peer(
                requester,
                after_sequence=after_sequence,
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, value)
    def _federation_sync_reconcile(self) -> None:
        """Return a bounded current projection for a peer's repair request."""
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(2 * 1024 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            raw_job_ids = payload.get("job_ids") or []
            limit = int(payload.get("limit") or 200)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not isinstance(raw_job_ids, list):
                raise ValueError("job_ids must be a list")
            if not 1 <= limit <= 200:
                raise ValueError("limit must be between 1 and 200")
            jobs = self.state.job_index.reconcile_for_peer(
                requester,
                job_ids=raw_job_ids[:200],
                limit=limit,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "source_server_id": self.state.server_id,
            "jobs": jobs,
        })

    def _federation_sync(self) -> None:
        """Run one manual event pull from the Manager settings page."""
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "reports": self.state.sync_federation_once(),
        })
