"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import json
from server.manager.http.responses import json_response

class FederationSyncRoutesMixin:
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
