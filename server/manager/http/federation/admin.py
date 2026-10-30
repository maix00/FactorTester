"""Semantic slice of the authenticated federation HTTP adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit

from server.identity.federation_identity_sync import (
    DESTINATION_ALLOWED_ATTRIBUTE,
    SOURCE_ENABLED_ATTRIBUTE,
    IdentitySyncTransitionError,
    IdentitySyncVerificationUnavailable,
    assert_destination_sync_can_be_disabled,
    group_sync_value,
    manager_keycloak_admin_adapter,
    organization_group_from_admin_scope,
    organization_group_paths,
    set_group_sync_value,
)
from server.identity.realm_groups import (
    managed_member_group_paths,
    organization_group_path,
)
from server.manager.domain.federation import ServiceRoute
from server.manager.domain.federation.registry import FederationRegistrationConflict
from server.manager.domain.organization_scope import configured_managed_organizations
from server.manager.http.responses import json_response


class FederationAdminRoutesMixin:
    def _bind_legacy_internal_manager(self) -> None:
        """Explicitly review/bind one old registry row; never claim it on heartbeat."""
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        from server.identity.server_admission import current_manager_role, federated_manager_binding
        if (not bool(getattr(self.state, "public_server", False))
                or not self._has_secure_ui_transport()
                or not current_manager_role(session, "admin_console:manage")):
            json_response(self, {"success": False, "error": "current Keycloak super administrator permission required"}, 403)
            return
        try:
            payload = self._json_body(16 * 1024)
            if not set(payload) <= {"server_id", "organization_id", "fingerprint", "expected_sha256", "dry_run"}:
                raise ValueError("unexpected legacy binding field")
            server_id = str(payload.get("server_id") or "").strip()
            organization_id = str(payload.get("organization_id") or "").strip()
            fingerprint = str(payload.get("fingerprint") or "")
            expected_sha256 = str(payload.get("expected_sha256") or "")
            dry_run = payload.get("dry_run", True)
            if (not server_id or len(server_id) > 256 or any(ord(c) < 32 for c in server_id)
                    or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                    or type(dry_run) is not bool
                    or (not dry_run and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256))):
                raise ValueError("invalid legacy binding review")

            def verify():
                from server.manager.storage.transfers.node_identities import decode_public_key
                from server.manager.transfers.node_advertisements import verify_advertisement
                try:
                    node = self.state.node_identities.require(server_id)
                    calculated = hashlib.sha256(decode_public_key(node.public_key)).hexdigest()
                    existing = self.state.federation_registry.describe(server_id) or {}
                    advertisement = existing.get("transfer_node") or {}
                    issued_at = float(advertisement.get("issued_at"))
                    # Expiration does not remove an offline Manager's claim. Verify
                    # its original signature at issue time without treating that
                    # old advertisement as a live route or permitting future data.
                    if issued_at > time.time() + 5:
                        return False
                    verified = verify_advertisement(advertisement, now=issued_at)
                    return (verified.node_id == server_id
                            and verified.identity["public_key"] == node.public_key
                            and hmac.compare_digest(verified.identity["fingerprint"], fingerprint)
                            and hmac.compare_digest(calculated, fingerprint)
                            and hmac.compare_digest(node.fingerprint, fingerprint)
                            and current_manager_role(session, "admin_console:manage")
                            and federated_manager_binding(server_id, organization_id, fingerprint,
                                                          use_cache=False))
                except (KeyError, PermissionError, ValueError, TypeError):
                    return False

            if not verify():
                raise PermissionError("Keycloak binding or enrolled node fingerprint is unavailable or mismatched")
            plan = self.state.federation_registry.legacy_binding_plan(server_id, organization_id)
            if dry_run:
                json_response(self, {"success": True, "dry_run": True, "plan": plan},
                              headers={"Cache-Control": "private, no-store"})
                return
            from server.jobs.dispatch.audit import append_audit
            from server.jobs.repository import JobRepository
            operation_id = hashlib.sha256(json.dumps(
                [server_id, organization_id, fingerprint, expected_sha256],
                separators=(",", ":"), ensure_ascii=False,
            ).encode()).hexdigest()
            actor = str(session.get("username") or "")
            detail = json.dumps({"server_id": server_id, "organization_id": organization_id,
                                 "fingerprint": fingerprint, "review_sha256": expected_sha256,
                                 "issuer": session.get("keycloak_issuer"),
                                 "subject": session.get("keycloak_subject")},
                                ensure_ascii=False, sort_keys=True, separators=(",", ":"))

            def audit(phase, _row):
                append_audit(JobRepository().db_path, action="manager-organization-bind-" + phase,
                             actor=actor, job_id=operation_id, detail=detail, idempotent=True)

            value = self.state.federation_registry.bind_reviewed_legacy(
                server_id, organization_id, expected_sha256=expected_sha256,
                verify=verify, audit=audit,
            )
            json_response(self, {"success": True, "dry_run": False, "binding": value},
                          headers={"Cache-Control": "private, no-store"})
        except FederationRegistrationConflict as exc:
            json_response(self, {"success": False, "code": exc.code, "error": str(exc)}, 409)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
        except Exception as exc:
            # The audit intent may exist after an interrupted write; retrying
            # the exact reviewed request idempotently records completion.
            json_response(self, {"success": False, "code": "binding_or_audit_unavailable",
                                 "error": type(exc).__name__}, 503)

    def _public_identity_sync_verifier_route(self) -> ServiceRoute:
        """Resolve the configured public Manager from its live peer lease."""
        config = self.state.federation_config()
        bootstrap_url = str(config.get("bootstrap_url") or "").strip()
        suffix = "/api/federation/register"
        if not bootstrap_url.endswith(suffix):
            raise IdentitySyncVerificationUnavailable(
                "public Manager is not configured for federation"
            )
        configured_base = bootstrap_url[:-len(suffix)].rstrip("/")
        configured = urlsplit(configured_base)
        if not configured.scheme or not configured.netloc:
            raise IdentitySyncVerificationUnavailable(
                "public Manager federation address is invalid"
            )

        peers = self.state.federation_registry.servers(include_offline=True)
        matching: list[dict[str, object]] = []
        for peer in peers:
            if not bool(peer.get("public_server", peer.get("role") == "main")):
                continue
            transfer = peer.get("transfer_node")
            transfer = transfer if isinstance(transfer, dict) else {}
            endpoint = str(transfer.get("peer_control_endpoint") or "").strip().rstrip("/")
            if endpoint == configured_base:
                matching.append(peer)
        if len(matching) != 1:
            raise IdentitySyncVerificationUnavailable(
                "configured public Manager has no unique registered peer"
            )
        peer = matching[0]
        if not bool(peer.get("online")):
            raise IdentitySyncVerificationUnavailable(
                "public Manager is offline; sync cannot be disabled"
            )
        server_id = str(peer.get("server_id") or "").strip()
        transfer = peer.get("transfer_node")
        transfer = transfer if isinstance(transfer, dict) else {}
        peer_endpoint = str(transfer.get("peer_control_endpoint") or "").strip()
        proxy_token = str(peer.get("proxy_token") or "").strip()
        if not server_id or not peer_endpoint or not proxy_token:
            raise IdentitySyncVerificationUnavailable(
                "public Manager peer route is incomplete"
            )
        return ServiceRoute(
            server_id=server_id,
            role=str(peer.get("role") or ""),
            branch=str(peer.get("branch") or ""),
            revision=str(peer.get("revision") or ""),
            port=0,
            peer_control_endpoint=peer_endpoint,
            proxy_token=proxy_token,
            remote=True,
            online=True,
            public_server=True,
        )

    def _local_source_organization_paths(self) -> set[str]:
        """Resolve only the organizations this internal Manager represents."""
        state = self.state
        organization_ids = tuple(
            str(value).strip()
            for value in (getattr(state, "managed_organizations", ()) or ())
            if str(value).strip()
        )
        if not organization_ids:
            organization_ids = configured_managed_organizations(
                public_server=False,
                server_role=str(getattr(state, "server_role", "") or ""),
            )
        return {organization_group_path(value) for value in organization_ids}

    def _identity_sync_admin_context(self) -> tuple[dict[str, object] | None, bool, set[str]]:
        from server.identity.server_admission import current_administrative_groups

        session = self._session()
        if session is None or not self._has_secure_ui_transport():
            return session, False, set()
        is_super = self._has_super_admin_session()
        if is_super:
            return session, True, set()
        groups = current_administrative_groups(session) or ()
        # An unexpired token may retain a revoked realm-wide role. Do not pass
        # that stale grant to downstream scoped-directory authorization.
        session = {**session, "keycloak_groups": groups,
                   "keycloak_roles": tuple(role for role in (session.get("keycloak_roles") or ())
                                           if role != "admin_console:manage")}
        organization_paths = managed_member_group_paths(groups)
        return session, False, organization_paths

    @staticmethod
    def _group_display_name(group: dict[str, object], group_path: str) -> str:
        return str(group.get("name") or group_path.rsplit("/", 1)[-1])

    def _identity_sync_policy_rows(
        self, *, groups: list[dict[str, object]], is_super: bool,
        organization_paths: set[str],
    ) -> list[dict[str, object]]:
        by_path = {
            str(group.get("path") or ""): group
            for group in groups if isinstance(group, dict)
        }
        is_public = bool(getattr(self.state, "public_server", False))
        if is_public:
            if not is_super:
                return []
            organizations: dict[str, dict[str, object]] = {}
            for peer in self.state.federation_registry.servers(include_offline=True):
                if bool(peer.get("public_server", peer.get("role") == "main")):
                    continue
                server_id = str(peer.get("server_id") or "")
                for organization_id in peer.get("managed_organizations") or ():
                    identifier = str(organization_id or "").strip()
                    if not identifier:
                        continue
                    path = organization_group_path(identifier)
                    organization = by_path.get(path, {})
                    organizations[path] = {
                        "group_path": path,
                        "organization_id": identifier,
                        "name": self._group_display_name(organization, identifier),
                        "server_id": server_id,
                        "server_online": bool(peer.get("online")),
                        "sync_allowed": group_sync_value(
                            organization, DESTINATION_ALLOWED_ATTRIBUTE,
                        ),
                        "configured": bool(organization),
                    }
            return sorted(organizations.values(), key=lambda row: str(row["name"]).casefold())

        local_source_paths = self._local_source_organization_paths()
        if is_super:
            selected_paths = local_source_paths
        else:
            selected_paths = organization_paths & local_source_paths
        rows = []
        for path in sorted(selected_paths):
            group = by_path.get(path)
            if not isinstance(group, dict):
                continue
            rows.append({
                "group_path": path,
                "name": self._group_display_name(group, path),
                "sync_enabled": group_sync_value(group, SOURCE_ENABLED_ATTRIBUTE),
                "configured": True,
            })
        return rows

    def _admin_federation_settings(self) -> None:
        session, is_super, organization_paths = self._identity_sync_admin_context()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        is_public = bool(getattr(self.state, "public_server", False))
        local_source_paths = (
            set() if is_public else self._local_source_organization_paths()
        )
        if not is_super and (
            is_public or not (organization_paths & local_source_paths)
        ):
            json_response(self, {
                "success": False,
                "error": "Keycloak federation administration permission required",
            }, 403)
            return
        try:
            adapter = manager_keycloak_admin_adapter()
            groups = adapter.group_representations()
            config = self.state.federation_config(public=True)
            config_status = self.state.federation_config_status()
        except Exception as exc:
            json_response(self, {
                "success": False,
                "code": "keycloak_federation_admin_unavailable",
                "error": type(exc).__name__,
            }, 503)
            return
        rows = self._identity_sync_policy_rows(
            groups=groups,
            is_super=is_super,
            organization_paths=organization_paths,
        )
        json_response(self, {
            "success": True,
            "server": {
                "server_id": self.state.server_id,
                "public_server": is_public,
                "role": self.state.server_role,
            },
            "connection": {
                "bootstrap_url": str(config.get("bootstrap_url") or ""),
                "enabled": bool(config_status.get("enabled")),
                "active": bool(config_status.get("active")),
                "registration_token_configured": bool(
                    config.get("registration_token_configured")
                ),
            },
            "policy_mode": "destination_allow" if is_public else "source_opt_in",
            "organizations": rows,
            # Until the dedicated Keycloak identity-event stream is deployed,
            # never imply that a saved policy means the directory is syncing.
            "identity_sync_transport": "not_connected",
            "can_manage_all": is_super,
            "can_edit_connection": (
                not is_public
                and (is_super or bool(organization_paths & local_source_paths))
            ),
        }, headers={"Cache-Control": "private, no-store"})

    def _update_admin_federation_settings(self) -> None:
        session, is_super, organization_paths = self._identity_sync_admin_context()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        is_public = bool(getattr(self.state, "public_server", False))
        local_source_paths = (
            set() if is_public else self._local_source_organization_paths()
        )
        if not is_super and (
            is_public or not (organization_paths & local_source_paths)
        ):
            json_response(self, {
                "success": False,
                "error": "Keycloak federation administration permission required",
            }, 403)
            return
        try:
            payload = self._json_body(16 * 1024)
            if set(payload) == {"bootstrap_url"}:
                if is_public:
                    raise PermissionError("public Manager has no upstream bootstrap address")
                value = self.state.update_federation_config({
                    "bootstrap_url": payload.get("bootstrap_url"),
                })
                json_response(self, {
                    "success": True,
                    "connection": {
                        "bootstrap_url": value["config"].get("bootstrap_url", ""),
                        "enabled": bool(value["status"].get("enabled")),
                        "active": bool(value["status"].get("active")),
                    },
                })
                return

            expected_field = "allowed" if is_public else "enabled"
            if set(payload) != {"group_path", expected_field}:
                raise ValueError("request must update one organization sync policy")
            group_path = str(payload.get("group_path") or "").strip()
            enabled = payload.get(expected_field)
            if type(enabled) is not bool:
                raise ValueError(f"{expected_field} must be a boolean")
            verifier_route = None
            if not is_public:
                if group_path not in local_source_paths or (
                    not is_super and group_path not in organization_paths
                ):
                    raise PermissionError(
                        "organization is outside the caller's Keycloak scope"
                    )
                if not enabled:
                    # Use the peer lease before any Keycloak call. Offline or
                    # unknown public Managers reject this transition immediately.
                    verifier_route = self._public_identity_sync_verifier_route()
            adapter = manager_keycloak_admin_adapter()
            groups = adapter.group_representations()
            available_paths = set(organization_group_paths(groups))
            if not is_public:
                available_paths &= local_source_paths
            if is_public and is_super:
                available_paths = {
                    organization_group_path(str(organization_id))
                    for peer in self.state.federation_registry.servers(include_offline=True)
                    if not bool(peer.get("public_server", peer.get("role") == "main"))
                    for organization_id in peer.get("managed_organizations") or ()
                    if str(organization_id or "").strip()
                }
            elif not is_super:
                available_paths &= organization_paths
            if group_path not in available_paths:
                raise PermissionError("organization is outside the caller's Keycloak scope")
            attribute = (
                DESTINATION_ALLOWED_ATTRIBUTE
                if is_public else SOURCE_ENABLED_ATTRIBUTE
            )
            if not enabled and is_public:
                from server.identity.user_session import oidc_settings

                assert_destination_sync_can_be_disabled(
                    adapter,
                    group_path=group_path,
                    roles_client_id=oidc_settings()["roles_client_id"],
                )
            elif not enabled:
                assert verifier_route is not None
                try:
                    result = self.state.federation_gateway.check_identity_sync_disable(
                        verifier_route,
                        requester_server_id=self.state.server_id,
                        requester_proxy_token=self.state.federation_proxy_token(),
                        group_path=group_path,
                    )
                except Exception as exc:
                    raise IdentitySyncVerificationUnavailable(
                        "public Manager did not return a verifiable sync decision"
                    ) from exc
                if result.get("allowed") is not True:
                    raise IdentitySyncTransitionError(
                        "public Manager rejected the sync-disable request; "
                        "review administrator continuity in its Keycloak realm"
                    )
            updated = set_group_sync_value(
                adapter,
                group_path=group_path,
                attribute=attribute,
                enabled=enabled,
            )
            json_response(self, {
                "success": True,
                "group_path": group_path,
                expected_field: group_sync_value(updated, attribute),
            })
        except IdentitySyncTransitionError as exc:
            json_response(self, {
                "success": False,
                "code": "identity_sync_admin_handoff_required",
                "error": str(exc),
            }, 409)
        except IdentitySyncVerificationUnavailable as exc:
            json_response(self, {
                "success": False,
                "code": "identity_sync_verifier_unavailable",
                "error": str(exc),
            }, 503)
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
        except (TypeError, ValueError, OSError, LookupError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
        except Exception as exc:
            json_response(self, {
                "success": False,
                "code": "keycloak_federation_admin_unavailable",
                "error": type(exc).__name__,
            }, 503)

    def _federation_servers(self) -> None:
        visitor = self._visitor_mode()
        if visitor is not None:
            # The test workbench uses this list only to offer an optional
            # execution target.  A visitor may see public local targets, but
            # never the federation registration/proxy metadata of peers.
            json_response(self, {
                "success": True,
                "visitor": True,
                "server_id": self.state.server_id,
                "role": self.state.server_role,
                "local_targets": [
                    route.as_dict()
                    for route in self.state.local_service_routes(
                        include_offline=False,
                    )
                ],
                "servers": [],
            })
            return
        if not self._has_api_authorization():
            self._require_capability()
            return
        servers = []
        for item in self.state.federation_registry.servers(include_offline=True):
            servers.append({
                key: value
                for key, value in item.items()
                if key not in {"proxy_token"}
            })
        json_response(self, {
            "success": True,
            "server_id": self.state.server_id,
            "role": self.state.server_role,
            "local_targets": [
                route.as_dict()
                for route in self.state.local_service_routes(include_offline=False)
            ],
            "servers": servers,
        })

    def _has_super_admin_session(self) -> bool:
        from server.identity.server_admission import current_manager_role

        session = self._session()
        return bool(
            self._has_secure_ui_transport()
            and session
            and current_manager_role(session, "admin_console:manage")
        )

    def _require_super_admin_session(self) -> bool:
        if self._has_super_admin_session():
            return True
        session = self._session()
        status = 401 if session is None else 403
        json_response(
            self,
            {
                "success": False,
                "error": "super administrator permission required",
            },
            status,
        )
        return False

    def _federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "config": self.state.federation_config(public=True),
            "status": self.state.federation_config_status(),
            "available_ports": [
                route.as_dict()
                for route in self.state.local_service_routes(
                    include_offline=False,
                )
            ],
        })

    def _update_federation_config(self) -> None:
        if not self._require_super_admin_session():
            return
        try:
            value = self.state.update_federation_config(
                self._json_body(256 * 1024),
            )
        except (TypeError, ValueError, OSError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
