"""POST/PUT/PATCH/DELETE dispatch and Manager lifecycle actions."""

from __future__ import annotations

import hashlib
import json
import sys
from urllib.parse import parse_qs, urlparse

from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class WriteRoutesMixin:
    """Dispatch state-changing routes after the public-entry gate."""

    def _invalidate_federated_public_research(self) -> None:
        service = getattr(self.state, "federated_public_research", None)
        invalidate = getattr(service, "invalidate_research_cache", None)
        if callable(invalidate):
            invalidate()

    def _sync_research_metadata(
        self, publication_id: str, *, deleted: bool = False,
    ) -> None:
        """Enqueue publication metadata; report bytes stay on the source node."""
        synchronizer = getattr(self.state, "account_domain_sync", None)
        if synchronizer is None:
            return
        try:
            metadata = self.state.public_research.publication_metadata(
                publication_id,
            )
            synchronizer.sync_research_publication(
                metadata, deleted=deleted,
            )
        except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            # The local publication has already been committed. The SQLite
            # outbox is best-effort here and will be retried on a later read.
            return

    def do_POST(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        # Authentication is the one public POST route in the protected
        # instance.  Registration itself is rejected by _register when the
        # server disables public account creation.
        if parsed.path == "/auth/login":
            self._login()
            return
        if parsed.path == "/auth/register":
            self._register()
            return
        if not self._public_login_gate(parsed, method="POST"):
            return
        if parsed.path == "/api/catalog/refresh":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                # Drain an optional JSON body before closing the TLS response.
                # Leaving even '{}' unread can truncate the response on HTTPS.
                if int(self.headers.get("Content-Length", "0")):
                    self._json_body(4096)
            except (ValueError, UnicodeError):
                json_response(self, {"success": False, "error": "invalid refresh request"}, 400)
                return
            result = self.state.client_state.refresh_account_catalog(str(session["username"]))
            json_response(self, {"success": result.get("status") == "synced", "sync": result},
                          200 if result.get("status") == "synced" else 503)
            return
        if self._mihomo_write(parsed, "POST"):
            return
        if self._post_agent_app_routes(parsed):
            return
        if self._post_page_assistance_routes(parsed):
            return
        if self._post_agent_routes(parsed):
            return
        if self._post_client_research_routes(parsed):
            return
        if self._post_research_catalog_routes(parsed):
            return
        if self._post_research_object_routes(parsed):
            return
        if parsed.path == "/api/device/challenge":
            self._device_challenge()
            return
        if parsed.path == "/api/device/verify":
            self._device_verify()
            return
        if self._issue_client_release_upload_access(parsed):
            return
        if parsed.path == "/api/devices/enroll":
            self._device_enroll()
            return
        if parsed.path == "/api/devices/revoke":
            self._device_revoke()
            return
        if parsed.path == "/api/admin/public-visitor-allowlist":
            self._admin_add_visitor_allowlist()
            return
        if parsed.path == "/api/admin/access-control/devices/revoke":
            self._admin_revoke_device()
            return
        if parsed.path == "/api/admin/users":
            self._admin_create_user()
            return
        if parsed.path == "/api/admin/organizations":
            self._admin_create_organization()
            return
        if parsed.path == "/api/admin/levels":
            self._admin_create_level()
            return
        if parsed.path == "/api/federation/sync":
            self._federation_sync()
            return
        if self._serve_sqlite_web(parsed, method="POST"):
            return
        if self.path == "/auth/logout":
            token = self._bearer_token()
            if self.state.session_principal(token) is None:
                self._require_capability()
                return
            self.state.logout(token)
            json_response(
                self,
                {"success": True},
                headers={"Set-Cookie": self._session_cookie(token, clear=True)},
            )
            return
        if self._serve_manager_application(parsed, method="POST"):
            return
        if self._query_artifact_projection(parsed):
            return
        if self._issue_artifact_transfer_access(parsed):
            return
        if self._issue_submission_transfer_access(parsed):
            return
        if self._issue_object_download_access(parsed):
            return
        if self._issue_object_transfer_access(parsed):
            return
        if self._proxy_job_request(parsed, method="POST"):
            return
        if self.path == "/api/research-publications/sync":
            client_session = self._session()
            if not self._is_local_ftclient() and client_session is None:
                json_response(self, {"success": False, "error": "authenticated FTClient required"}, 403)
                return
            try:
                payload = self._json_body(32 * 1024 * 1024)
                from .research_branch_routes import ResearchBranchRoutesMixin
                ResearchBranchRoutesMixin._require_branch_profile_actor(self, str(payload.get("profile_ref") or ""))
                if client_session is not None:
                    owner = str(client_session["username"])
                    if payload.get("owner_ref") not in (None, "", owner):
                        raise PermissionError("report owner does not match the authenticated principal")
                    payload["owner_ref"] = owner
                value = self.state.public_research.sync(payload)
                if value.get("publication_id"):
                    self._sync_research_metadata(str(value["publication_id"]))
                self._invalidate_federated_public_research()
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/research-publications/publish":
            payload = self._json_body(32 * 1024 * 1024)
            server_ref = str(payload.get("server_ref") or "").strip()
            if server_ref:
                session = self._session()
                if session is None:
                    json_response(
                        self,
                        {"success": False, "error": "login required"},
                        401,
                    )
                    return
                try:
                    value = self.state.server_research.publish(
                        str(session.get("username") or ""),
                        server_ref,
                        public_research=self.state.public_research,
                        visibility=str(payload.get("visibility") or "public"),
                        authorized_users=list(
                            payload.get("authorized_users") or []
                        ),
                        public_title=str(payload.get("public_title") or ""),
                    )
                    self._sync_research_metadata(
                        str(value["publication_id"]),
                    )
                    self._invalidate_federated_public_research()
                except PermissionError as exc:
                    json_response(
                        self, {"success": False, "error": str(exc)}, 403,
                    )
                    return
                except (OSError, TypeError, ValueError, KeyError) as exc:
                    json_response(
                        self, {"success": False, "error": str(exc)}, 400,
                    )
                    return
                json_response(self, {"success": True, **value}, 201)
                return
            local_client = self._is_local_ftclient()
            client_session = None if local_client else self._session()
            if not local_client and client_session is None:
                json_response(self, {"success": False, "error": "authenticated FTClient required"}, 403)
                return
            try:
                from .research_branch_routes import ResearchBranchRoutesMixin
                ResearchBranchRoutesMixin._require_branch_profile_actor(self, str(payload.get("profile_ref") or ""))
                projection = payload.get("projection")
                report_id = str(payload.get("report_id") or "")
                owner_ref = str(
                    client_session.get("username") if client_session is not None
                    else payload.get("owner_ref") or ""
                )
                supplied_owner = str(payload.get("owner_ref") or "").strip()
                if client_session is not None and supplied_owner != owner_ref:
                    raise PermissionError("report owner does not match authenticated user")
                if isinstance(projection, dict) and str(payload.get("public_title") or "").strip():
                    projection = {
                        **projection,
                        "title": str(payload["public_title"]).strip(),
                    }
                    # The title is part of the content-addressed projection.
                    # Recompute the hash after the optional public override so
                    # the list ETag and the mirrored payload describe the same
                    # bytes instead of retaining the local title's hash.
                    projection["projection_hash"] = hashlib.sha256(
                        json.dumps(
                            {
                                key: value
                                for key, value in projection.items()
                                if key != "projection_hash"
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                synced = self.state.public_research.sync({
                    "report_id": report_id,
                    "publication_key": str(payload.get("publication_key") or report_id),
                    "branch_ref": str(payload.get("branch_ref") or ""),
                    "owner_ref": owner_ref,
                    "profile_ref": str(payload.get("profile_ref") or ""),
                    "projection": projection,
                })
                if synced.get("status") != "synced":
                    json_response(self, {"success": False, **synced}, 409)
                    return
                settings = self.state.public_research.configure(
                    owner_ref=owner_ref,
                    report_id=report_id,
                    publication_key=str(payload.get("publication_key") or report_id),
                    projection=None,
                    visibility=str(payload.get("visibility") or "public"),
                    auto_sync=True,
                    relay_local_files=False,
                    authorized_users=list(payload.get("authorized_users") or []),
                )
                self._sync_research_metadata(str(settings["publication_id"]))
                self._invalidate_federated_public_research()
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {
                "success": True,
                "status": "published",
                "publication_id": settings["publication_id"],
                "report_id": settings["report_id"],
                "visibility": settings["visibility"],
                "generation": settings.get("generation"),
                "projection_hash": projection["projection_hash"],
                "storage_server_id": settings.get("storage_server_id") or self.state.server_id,
            })
            return
        if self.path == "/api/research-publications/revoke":
            revoke_session = None if self._is_local_ftclient() else self._session()
            if not self._is_local_ftclient() and revoke_session is None:
                json_response(self, {"success": False, "error": "authenticated FTClient required"}, 403)
                return
            try:
                payload = self._json_body(64 * 1024)
                publication_id = str(payload.get("publication_id") or "")
                if revoke_session is not None:
                    metadata = self.state.public_research.publication_metadata(
                        publication_id,
                    )
                    if str(metadata.get("owner_ref") or "") != str(
                        revoke_session.get("username") or ""
                    ):
                        raise PermissionError(
                            "publication does not belong to authenticated user"
                        )
                self._sync_research_metadata(publication_id, deleted=True)
                value = self.state.public_research.revoke_publication(
                    publication_id,
                )
                self._invalidate_federated_public_research()
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except ValueError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return
            json_response(self, {"success": True, **value})
            return
        if self.path == "/api/research-publications/settings":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                payload = self._json_body(256 * 1024)
                owner = str(session["username"])
                report_id = str(payload.get("report_id") or "")
                publication_id = str(payload.get("publication_id") or "").strip()
                visibility = str(payload.get("visibility") or "private")
                authorized_users = list(payload.get("authorized_users") or [])
                if visibility == "superiors":
                    authorized_users = self._research_catalog_superior_refs(owner)
                publication = None
                if publication_id:
                    publication = self.state.public_research.owner_settings(
                        publication_id, owner,
                    )
                    if report_id and report_id != publication["report_id"]:
                        raise PermissionError("report settings target does not match")
                    report_id = str(publication["report_id"])
                server_report = self.state.server_research.owner_report(
                    owner, report_id,
                )
                if server_report is not None and publication is None:
                    value = self.state.server_research.publish(
                        owner,
                        str(server_report["server_ref"]),
                        public_research=self.state.public_research,
                        visibility=visibility,
                        authorized_users=list(
                            authorized_users
                        ),
                    )
                else:
                    value = self.state.public_research.configure(
                        owner_ref=owner,
                        report_id=report_id,
                        publication_key=str(
                            (publication or {}).get("publication_key") or report_id
                        ),
                        projection=None,
                        visibility=visibility,
                        auto_sync=bool(payload.get("auto_sync", True)),
                        relay_local_files=bool(
                            payload.get("relay_local_files", False)
                        ),
                        authorized_users=list(
                            authorized_users
                        ),
                    )
                research_id = str(payload.get("research_id") or "").strip()
                if not research_id:
                    matches = {
                        str(item.get("research_id") or "")
                        for item in self.state.research_catalog.list_reports_for_scope(
                            viewer=owner, scope="mine",
                        )
                        if str(item.get("report_id") or "") == report_id
                    }
                    matches.discard("")
                    if len(matches) == 1:
                        research_id = matches.pop()
                if research_id:
                    self.state.research_catalog.update_report(
                        research_id,
                        report_id,
                        actor=owner,
                        visibility=visibility,
                        authorized_users=authorized_users,
                    )
                    self._sync_research_report_publications(
                        owner=owner,
                        report_id=report_id,
                        visibility=visibility,
                        authorized_users=authorized_users,
                    )
                self._sync_research_metadata(str(value["publication_id"]))
                self._invalidate_federated_public_research()
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            json_response(self, {"success": True, "settings": value})
            return
        if self.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return
            try:
                value = self.state.user_preferences.update(
                    str(session["username"]),
                    self._json_body(64 * 1024),
                )
            except (TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return
            except ControlDatabaseError:
                json_response(
                    self,
                    {
                        "success": False,
                        "error": "preference store is temporarily unavailable",
                    },
                    503,
                )
                return
            json_response(self, {"success": True, "preferences": value})
            return
        if self._proxy_service_write(parsed, method="POST"):
            return
        if self._proxy_authenticated_local_service(parsed, method="POST"):
            return
        actions = {
            "/vibe/start",
            "/vibe/stop",
            "/start",
            "/stop",
            "/restart-api",
            "/restart-bundle",
            "/force-stop",
        }
        if self.path not in actions:
            self.send_error(404)
            return
        if not (
            self._has_api_authorization()
            or self._is_same_origin_browser_action()
        ):
            self._require_capability()
            return
        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        if set(params) != {"instance_id"} or len(params["instance_id"]) != 1:
            json_response(
                self,
                {"success": False, "error": "instance_id is required and is the only accepted target"},
                400,
            )
            return
        instance_id = str(params["instance_id"][0])
        try:
            operation = self._resolve_operation(instance_id)
        except LookupError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return
        if self.headers.get("Prefer", "").strip().lower() == "respond-async":
            json_response(self, {
                "success": True,
                "submitted": True,
                "instance_id": instance_id,
            }, 202)
            self.state.submit_action(operation, f"{self.path} {instance_id}")
            return
        try:
            message = operation()
        except Exception as exc:
            sys.stderr.write(f"[manager] action {self.path} failed: {exc}\n")
            json_response(
                self,
                {"success": False, "error": "manager action failed"},
                409,
            )
            return
        json_response(self, {
            "success": True,
            "instance_id": instance_id,
            "message": message,
        })

    def do_PATCH(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="PATCH"):
            return
        if self._mihomo_write(parsed, "PATCH"):
            return
        if self._patch_research_catalog_routes(parsed):
            return
        if self._patch_research_object_routes(parsed):
            return
        # Manager-owned application APIs, including Strategy library CRUD,
        # must be dispatched before the business-port proxies.  PATCH used to
        # skip this seam even though GET/POST/PUT/DELETE all reached it,
        # making visibility and edit operations fail with a misleading 404.
        if self._serve_manager_application(parsed, method="PATCH"):
            return
        if self._proxy_job_request(parsed, method="PATCH"):
            return
        if self._proxy_service_write(parsed, method="PATCH"):
            return
        if self._proxy_authenticated_local_service(parsed, method="PATCH"):
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="PUT"):
            return
        if self._mihomo_write(parsed, "PUT"):
            return
        if parsed.path == "/api/control-database/config":
            self._update_control_database_config()
            return
        if parsed.path == "/api/federation/config":
            self._update_federation_config()
            return
        if self._serve_manager_application(parsed, method="PUT"):
            return
        if parsed.path.startswith("/api/admin/users/"):
            self._admin_update_user()
            return
        if parsed.path.startswith("/api/admin/levels/"):
            self._admin_update_level()
            return
        if self._proxy_service_write(parsed, method="PUT"):
            return
        if self._proxy_authenticated_local_service(parsed, method="PUT"):
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        if self._redirect_plain_http_to_https():
            return
        parsed = urlparse(self.path)
        if not self._public_login_gate(parsed, method="DELETE"):
            return
        if self._mihomo_write(parsed, "DELETE"):
            return
        if self._delete_page_assistance_routes(parsed):
            return
        if self._delete_agent_routes(parsed):
            return
        if self._delete_research_catalog_routes(parsed):
            return
        if self._proxy_job_request(parsed, method="DELETE"):
            return
        if self._serve_manager_application(parsed, method="DELETE"):
            return
        if self._delete_research_object_routes(parsed):
            return
        if self._proxy_service_write(parsed, method="DELETE"):
            return
        # Manager-owned policy must be handled before the broad /api/admin/ proxy.
        if parsed.path == "/api/admin/public-visitor-allowlist":
            self._admin_remove_visitor_allowlist()
            return
        if self._proxy_authenticated_local_service(parsed, method="DELETE"):
            return
        self.send_error(404)

    def _resolve_operation(self, instance_id: str):
        if self.path == "/vibe/start":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.start_vibe
        if self.path == "/vibe/stop":
            if instance_id != "service-vibe-trading":
                raise LookupError("managed instance not found")
            return self.state.stop_vibe
        worktree = self.state.worktree_for_instance(instance_id)
        if worktree is None:
            raise LookupError("managed instance not found")
        if self.path == "/start":
            return lambda: self.state.start(worktree.path, worktree.port)
        if self.path == "/stop":
            return lambda: self.state.stop(worktree.path)
        if self.path == "/restart-api":
            return lambda: self.state.restart_api(worktree.path, worktree.port)
        if self.path == "/restart-bundle":
            return lambda: self.state.restart_bundle(worktree.path, worktree.port)
        return lambda: self.state.stop(worktree.path, force=True)
