"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import json

from server.manager.http.responses import json_response


class FederationJobRoutesMixin:
    def _federation_jobs_query(self) -> None:
        """Serve a bounded local task projection to a peer Manager.

        The proxy token authenticates the peer-to-peer request.  The local
        aggregation methods are explicitly called with federation disabled so
        this endpoint cannot recurse through the other Manager.
        """
        if not self._has_federation_proxy_token():
            json_response(
                self,
                {"success": False, "error": "federation proxy is unauthorized"},
                401,
            )
            return
        try:
            payload = self._json_body(64 * 1024)
            requester = str(payload.get("requester_server_id") or "").strip()
            principal = str(payload.get("principal") or "").strip()
            scope = str(payload.get("scope") or "").strip().lower()
            page = int(payload.get("page") or 1)
            limit = int(payload.get("limit") or 100)
            if not requester:
                raise ValueError("requester_server_id is required")
            if requester == self.state.server_id:
                raise ValueError("requester_server_id must identify a peer")
            if not principal:
                raise ValueError("principal is required")
            if scope not in {"mine", "subordinates", "visible", "server"}:
                raise ValueError(
                    "scope must be mine, subordinates, visible, or server"
                )
            username = str(payload.get("username") or "").strip()
            if scope == "subordinates" and not username:
                raise ValueError("username is required for subordinate jobs")
            if page < 1 or not 1 <= limit <= 100:
                raise ValueError("page or limit is invalid")
            object_filter = {
                key: str(payload.get(key) or "").strip()
                for key in (
                    "object_kind", "object_ref",
                    "object_owner_ref", "object_alias",
                )
                if str(payload.get(key) or "").strip()
            }
            if scope == "server":
                value = self.state.aggregate_server_jobs(
                    principal=principal,
                    cursor="",
                    limit=limit,
                    **object_filter,
                    _allow_federation=False,
                )
            else:
                account_query = {
                    "principal": principal,
                    "scope": scope,
                    "page": page,
                    "limit": limit,
                    "_allow_federation": False,
                    **object_filter,
                }
                if username:
                    account_query["username"] = username
                value = self.state.aggregate_account_jobs(**account_query)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            **value,
            "success": True,
            "source_server_id": self.state.server_id,
            "source_scope": scope,
        })
