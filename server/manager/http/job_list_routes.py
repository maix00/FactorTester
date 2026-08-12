"""Task-list GET routes and cross-server scope selection."""

from __future__ import annotations

from urllib.parse import parse_qs

from server.manager.domain.federation import TargetUnavailable
from server.manager.http.responses import json_response


class JobListRoutesMixin:
    """Serve task scopes while preserving local and federated fallbacks."""

    def _get_job_list_routes(self, parsed) -> bool:
        if parsed.path == "/api/jobs/ports":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            payload = {
                "ports": self.state.service_ports(),
                "automatic_port": self.state.preferred_service_port(),
            }
            if self.state.has_federated_servers():
                payload["targets"] = [
                    route.as_dict()
                    for route in self.state.service_routes(include_offline=True)
                ]
            json_response(self, payload)
            return True
        if parsed.path == "/api/jobs":
            session = self._session()
            query = parse_qs(parsed.query, keep_blank_values=True)
            scope = str(query.get("scope", [""])[0] or "").strip().lower()
            if not scope:
                if session is None or str(session.get("role") or "") == "super_admin":
                    scope = "server"
                else:
                    scope = "mine"
            if session is None and scope != "server":
                # Keep the three scopes visible in the web client without
                # asking an anonymous request to discover private accounts.
                json_response(self, {
                    "success": True,
                    "scope": scope,
                    "requires_login": True,
                    "jobs": [],
                    "page": 1,
                    "page_size": 20,
                    "total": 0,
                    "total_pages": 1,
                    "has_more": False,
                    "next_cursor": None,
                })
                return True
            try:
                limit = int(query.get("limit", ["20"])[0] or 20)
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False,
                    "error": "limit 必须是整数",
                }, 400)
                return True
            if session is None:
                limit = min(limit, 20)
                principal = "__public_jobs__"
            else:
                principal = str(session["username"])
            if scope == "cross-server":
                if session is None:
                    json_response(self, {
                        "success": True,
                        "scope": scope,
                        "requires_login": True,
                        "jobs": [],
                        "page": 1,
                        "page_size": 20,
                        "total": 0,
                        "total_pages": 1,
                        "has_more": False,
                        "next_cursor": None,
                    })
                    return True
                try:
                    requested_page = max(
                        1, int(query.get("page", ["1"])[0] or 1),
                    )
                    source_scope = str(
                        query.get("source_scope", [""])[0] or ""
                    ).strip().lower()
                except (TypeError, ValueError):
                    json_response(self, {
                        "success": False,
                        "error": "page 必须是整数",
                    }, 400)
                    return True
                if not source_scope:
                    source_scope = (
                        "server"
                        if str(session.get("role") or "") == "super_admin"
                        else "mine"
                    )
                if source_scope == "server" and str(
                    session.get("role") or ""
                ) != "super_admin":
                    json_response(self, {
                        "success": False,
                        "error": "只有超级管理员可以查看跨服务器全部任务",
                    }, 403)
                    return True
                try:
                    payload = self.state.aggregate_cross_server_jobs(
                        principal=principal,
                        page=requested_page,
                        limit=limit,
                        source_scope=source_scope,
                    )
                except (ConnectionError, OSError, TypeError, ValueError) as exc:
                    json_response(self, {
                        "success": False,
                        "error": str(exc),
                    }, 503)
                    return True
                payload["success"] = True
                payload["scope"] = scope
                json_response(self, payload)
                return True
            if scope == "server":
                # Server history is a public projection backed by the shared
                # job repository.  Keep its cache fallback so a stale
                # service process cannot turn the whole task page into 502.
                cursor = str(query.get("cursor", [""])[0] or "")
                try:
                    if session is not None and str(session.get("role") or "") == "super_admin":
                        payload = self.state.aggregate_server_jobs(
                            principal=principal, cursor=cursor, limit=limit,
                        )
                    else:
                        payload = self.state.aggregate_public_jobs(
                            cursor=cursor, limit=limit,
                        )
                except TargetUnavailable as exc:
                    json_response(self, {"success": False, "error": str(exc)}, 503)
                    return True
                except (ConnectionError, OSError, ValueError) as exc:
                    json_response(self, {"success": False, "error": str(exc)}, 503)
                    return True
                payload.setdefault("success", True)
                payload.setdefault("scope", scope)
                fallback_port = None
                for item in payload.get("jobs") or ():
                    if isinstance(item, dict):
                        if "port" not in item:
                            if fallback_port is None:
                                fallback_port = self.state.preferred_service_port() or 0
                            item["port"] = fallback_port
                json_response(self, payload)
                return True
            try:
                requested_page = max(1, int(query.get("page", ["1"])[0] or 1))
            except (TypeError, ValueError):
                json_response(self, {
                    "success": False, "error": "page 必须是整数",
                }, 400)
                return True
            try:
                if scope == "mine":
                    payload = self.state.aggregate_account_jobs(
                        principal=principal,
                        scope=scope,
                        page=requested_page,
                        limit=limit,
                    )
                elif scope == "subordinates":
                    users = self._subordinate_users(principal)
                    requested_user = str(
                        query.get("username", query.get("user", [""]))[0] or "",
                    ).strip()
                    base = {
                        "success": True,
                        "scope": scope,
                        "users": users,
                    }
                    if not requested_user:
                        json_response(self, {
                            **base,
                            "selection_required": True,
                            "jobs": [],
                            "page": 1,
                            "page_size": 20,
                            "total": 0,
                            "total_pages": 1,
                            "has_more": False,
                            "next_cursor": None,
                        })
                        return True
                    allowed = {item["username"] for item in users}
                    if requested_user not in allowed:
                        json_response(self, {
                            "success": False, "error": "无权查看该下级用户任务",
                        }, 403)
                        return True
                    payload = self.state.aggregate_account_jobs(
                        principal=principal,
                        scope=scope,
                        username=requested_user,
                        page=requested_page,
                        limit=limit,
                    )
                    payload["users"] = users
                else:
                    json_response(self, {
                        "success": False, "error": "不支持的任务范围",
                    }, 400)
                    return True
            except TargetUnavailable as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            except (ConnectionError, OSError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            payload["success"] = True
            payload["scope"] = scope
            json_response(self, payload)
            return True
        if self._serve_manager_application(parsed, method="GET"):
            return True
        if self._proxy_job_stream(parsed):
            return True
        if self._proxy_job_request(parsed, method="GET"):
            return True
        return False
