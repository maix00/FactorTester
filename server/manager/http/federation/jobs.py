"""Signed Manager job queries with current cross-realm user authorization."""
from __future__ import annotations

import json

from server.identity.federated_peer_delegation import accept_from_peer, bound_peer
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.server_admission import current_administrative_groups, current_manager_role
from server.manager.http.federation.node_auth import authenticated_node
from server.manager.http.responses import json_response


def _subordinate_username(identity: dict, target_identity_id: str) -> str:
    """Resolve the local subject and check the live Keycloak group hierarchy."""
    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    from server.identity.realm_groups import managed_member_group_paths

    if not target_identity_id or target_identity_id == identity.get("tr_identity_id"):
        raise PermissionError("a distinct subordinate stable identity is required")
    adapter = manager_keycloak_admin_adapter()
    user = adapter.user_by_identity_id(target_identity_id)
    attributes = user.get("attributes") if isinstance(user, dict) else None
    if (not isinstance(user, dict) or user.get("enabled") is not True or not user.get("id")
            or not isinstance(attributes, dict) or attributes.get("tr_identity_id") != [target_identity_id]):
        raise PermissionError("subordinate Keycloak identity is unavailable")
    if not current_manager_role(identity, "admin_console:manage"):
        current_groups = current_administrative_groups(identity)
        roots = managed_member_group_paths(current_groups)
        member_groups = adapter.user_group_paths(str(user["id"]))
        if not roots or not any(
                group == root or group.startswith(root.rstrip("/") + "/")
                for group in member_groups for root in roots):
            raise PermissionError("requested user is outside the current Keycloak hierarchy")
    legacy = attributes.get("legacy_username")
    if legacy is not None and (not isinstance(legacy, list) or len(legacy) != 1 or not legacy[0]):
        raise PermissionError("subordinate local identity is ambiguous")
    username = str(legacy[0] if legacy else user.get("username") or "").strip()
    if not username:
        raise PermissionError("subordinate local identity is unavailable")
    return username


class FederationJobRoutesMixin:
    def _federation_jobs_query(self) -> None:
        """Query local jobs without accepting foreign tokens or local fallbacks."""
        try:
            body, payload = self._node_json_body(64 * 1024)
            node = authenticated_node(self, method="POST", body=body)
            if str(payload.get("requester_server_id") or "") != node.node_id:
                raise PermissionError("requesting Manager does not match the signed node")
            binding = bound_peer(self.state, node.node_id)
            scope = str(payload.get("scope") or "").strip().lower()
            if scope not in {"mine", "subordinates", "visible", "server"}:
                raise ValueError("scope must be mine, subordinates, visible, or server")
            delegated = accept_from_peer(self.state, binding,
                assertion=str(payload.get("delegation_assertion") or ""),
                stable_id=str(payload.get("identity_id") or ""), target_scope="read")
            identity, token = delegated.target_session, delegated.target_token
            principal = str(identity.get("username") or "").strip()
            if not principal:
                raise PermissionError("target realm user is unavailable")
            username = ""
            if scope == "server" and not current_manager_role(identity, "admin_console:manage"):
                raise PermissionError("current Keycloak super administrator role is required")
            if scope == "subordinates":
                username = _subordinate_username(identity, str(payload.get("target_identity_id") or "").strip())
            page, limit = int(payload.get("page") or 1), int(payload.get("limit") or 100)
            cursor = str(payload.get("cursor") or "").strip()
            if len(cursor) > 4096 or page < 1 or not 1 <= limit <= 100:
                raise ValueError("cursor, page or limit is invalid")
            object_filter = {key: str(payload.get(key) or "").strip() for key in
                ("object_kind", "object_ref", "object_owner_ref", "object_alias")
                if str(payload.get(key) or "").strip()}
            if scope == "server":
                value = self.state.aggregate_server_jobs(principal=principal, cursor=cursor,
                    limit=limit, delegated_user_token=token, _allow_federation=False,
                    _allow_stale=False, **object_filter)
            else:
                query = dict(principal=principal, scope=scope, page=page, limit=limit,
                    delegated_user_token=token, _allow_federation=False, _allow_stale=False,
                    **object_filter)
                if username:
                    query["username"] = username
                value = self.state.aggregate_account_jobs(**query)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (AuthorizationUnavailable, ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {**value, "success": True, "source_server_id": self.state.server_id,
                             "source_scope": scope})
