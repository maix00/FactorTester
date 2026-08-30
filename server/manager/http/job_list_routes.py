"""Task-list GET routes and cross-server scope selection."""

from __future__ import annotations

from urllib.parse import parse_qs

from server.manager.domain.federation import TargetUnavailable
from server.manager.http.responses import json_response


def _merge_local_run_page(
    payload: dict,
    local_page: dict | None,
    *,
    limit: int,
) -> dict:
    """Add client-owned local runs to the normal task projection."""
    if not isinstance(local_page, dict):
        return payload
    local_jobs = [item for item in local_page.get("jobs") or () if isinstance(item, dict)]
    remote_jobs = [item for item in payload.get("jobs") or () if isinstance(item, dict)]
    combined = sorted(
        [*local_jobs, *remote_jobs],
        key=_updated_at_key,
        reverse=True,
    )[:max(1, int(limit))]
    result = dict(payload)
    result["jobs"] = combined
    result["total"] = int(payload.get("total") or len(remote_jobs)) + int(
        local_page.get("total") or len(local_jobs)
    )
    result["page_size"] = max(1, int(limit))
    result["has_more"] = bool(payload.get("has_more")) or bool(
        local_page.get("has_more")
    ) or len(remote_jobs) + len(local_jobs) > int(limit)
    result["total_pages"] = max(
        1,
        (int(result["total"]) + int(limit) - 1) // int(limit),
    )
    return result


def _updated_at_key(item: dict) -> tuple[int, float | str]:
    """Sort numeric Manager timestamps without lexicographic regressions."""
    raw = item.get("updated_at")
    try:
        return (1, float(raw))
    except (TypeError, ValueError):
        return (0, str(raw or ""))


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
            visitor = self._visitor_mode()
            query = parse_qs(parsed.query, keep_blank_values=True)
            scope = str(query.get("scope", [""])[0] or "").strip().lower()
            object_filter = {
                key: str(query.get(key, [""])[0] or "").strip()
                for key in (
                    "object_kind", "object_ref",
                    "object_owner_ref", "object_alias",
                )
                if str(query.get(key, [""])[0] or "").strip()
            }
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
                limit = min(limit, visitor.max_server_jobs if visitor else 20)
                principal = (
                    visitor.principal if visitor is not None
                    else "__public_jobs__"
                )
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
                        **object_filter,
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
                cursor = "" if visitor is not None else str(
                    query.get("cursor", [""])[0] or ""
                )
                try:
                    if session is not None and str(session.get("role") or "") == "super_admin":
                        payload = self.state.aggregate_server_jobs(
                            principal=principal, cursor=cursor, limit=limit,
                            **object_filter,
                        )
                        projection = getattr(self.state, "local_run_projection", None)
                        if (projection is not None and not cursor
                                and not object_filter.get("object_kind")):
                            payload = _merge_local_run_page(
                                payload,
                                projection.page(principal, page=1, limit=limit),
                                limit=limit,
                            )
                    else:
                        payload = self.state.aggregate_public_jobs(
                            cursor=cursor, limit=limit,
                            **object_filter,
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
                if visitor is not None:
                    # A visitor sees one bounded snapshot, never a cursor
                    # that can be used to walk beyond the newest 20 jobs.
                    payload = dict(payload)
                    payload["jobs"] = list(
                        payload.get("jobs") or ()
                    )[:visitor.max_server_jobs]
                    payload.update({
                        "page": 1,
                        "total": len(payload["jobs"]),
                        "total_pages": 1,
                        "has_more": False,
                        "next_cursor": None,
                    })
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
                if scope in {"mine", "visible"}:
                    # Account history is a federation-wide view too.  The
                    # cross-server aggregator queries each Manager's local
                    # SQLite projection in parallel and keeps the source
                    # identity needed for detail/artifact routing.
                    payload = self.state.aggregate_cross_server_jobs(
                        principal=principal,
                        page=requested_page,
                        limit=limit,
                        source_scope=scope,
                        **object_filter,
                    )
                    projection = getattr(self.state, "local_run_projection", None)
                    if projection is not None and not object_filter.get("object_kind"):
                        payload = _merge_local_run_page(
                            payload,
                            projection.page(principal, page=requested_page, limit=limit),
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
                    payload = self.state.aggregate_cross_server_jobs(
                        principal=principal,
                        page=requested_page,
                        limit=limit,
                        source_scope="subordinates",
                        username=requested_user,
                        **object_filter,
                    )
                    projection = getattr(self.state, "local_run_projection", None)
                    if projection is not None and not object_filter.get("object_kind"):
                        payload = _merge_local_run_page(
                            payload,
                            projection.page(requested_user, page=requested_page, limit=limit),
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
        if self._proxy_authenticated_local_service(parsed, method="GET"):
            return True
        if self._proxy_job_stream(parsed):
            return True
        if self._proxy_job_request(parsed, method="GET"):
            return True
        return False
