"""Manager-owned Profile research projection routes."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response
from server.services.research_graph.profile_research_projection import (
    ProfileResearchProjection,
    projection_etag,
)
from server.services.research_graph.work_packages import (
    WorkPackageConflictError,
    transition_lifecycle,
)


class ProfileResearchRoutesMixin:
    """Serve owner-scoped research navigation from the Manager database."""

    def _profile_research_session(self):
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
        return session

    @staticmethod
    def _profile_research_limit(query: dict, default: int) -> int:
        raw = str(query.get("limit", [""])[0] or "")
        return default if not raw else int(raw)

    def _profile_research_response(self, payload: dict) -> None:
        etag = projection_etag(payload)
        quoted = f'"{etag}"'
        if quoted in str(self.headers.get("If-None-Match") or ""):
            self.send_response(304)
            self.send_header("ETag", quoted)
            self.send_header("Cache-Control", "private, no-cache")
            self.end_headers()
            return
        json_response(
            self,
            {"success": True, **payload, "etag": f"sha256:{etag}"},
            headers={"ETag": quoted, "Cache-Control": "private, no-cache"},
        )

    def _profile_research_error(self, exc: Exception) -> None:
        if isinstance(exc, KeyError):
            status = 404
        elif isinstance(exc, WorkPackageConflictError):
            status = 409
        elif isinstance(exc, (TypeError, ValueError)):
            status = 400
        else:
            json_response(self, {
                "success": False,
                "error": "研究投影暂时无法读取，请稍后重试。",
                "error_code": "research_projection_failed",
            }, 500)
            return
        json_response(self, {"success": False, "error": str(exc)}, status)

    def _get_profile_research_routes(self, parsed) -> bool:
        if not parsed.path.startswith("/api/profile-research"):
            return False
        session = self._profile_research_session()
        if session is None:
            return True
        owner = str(session["username"])
        query = parse_qs(parsed.query, keep_blank_values=True)
        projection = ProfileResearchProjection()
        try:
            if parsed.path == "/api/profile-research":
                payload = projection.list_research(
                    owner=owner,
                    workspace_ref=str(query.get("workspace_ref", [""])[0]),
                    lifecycle=str(query.get("lifecycle", ["active"])[0] or "active"),
                    limit=self._profile_research_limit(query, 20),
                    after=str(query.get("after", [""])[0]),
                )
            else:
                payload = self._profile_research_detail(
                    projection, parsed.path, query, owner,
                )
        except Exception as exc:
            self._profile_research_error(exc)
            return True
        self._profile_research_response(payload)
        return True

    def _profile_research_detail(self, projection, path, query, owner):
        carrier = re.fullmatch(
            r"/api/profile-research/([^/]+)/branches/([^/]+)/checkpoints/([^/]+)/report-carrier",
            path,
        )
        if carrier:
            return projection.get_report_checkpoint(
                owner=owner,
                work_package_ref=unquote(carrier.group(1)),
                branch_id=unquote(carrier.group(2)),
                trace_id=unquote(carrier.group(3)),
            )
        branch_timeline = re.fullmatch(
            r"/api/profile-research/([^/]+)/branches/([^/]+)/timeline", path,
        )
        if branch_timeline:
            return projection.list_work_package_timeline(
                owner=owner,
                work_package_ref=unquote(branch_timeline.group(1)),
                branch_id=unquote(branch_timeline.group(2)),
                limit=self._profile_research_limit(query, 50),
                after=str(query.get("after", [""])[0]),
            )
        branch = re.fullmatch(
            r"/api/profile-research/([^/]+)/branches/([^/]+)", path,
        )
        if branch:
            return projection.get_work_package_branch(
                owner=owner,
                work_package_ref=unquote(branch.group(1)),
                branch_id=unquote(branch.group(2)),
            )
        timeline = re.fullmatch(r"/api/profile-research/([^/]+)/timeline", path)
        if timeline:
            return projection.list_timeline(
                owner=owner,
                research_ref=unquote(timeline.group(1)),
                limit=self._profile_research_limit(query, 50),
                after=str(query.get("after", [""])[0]),
            )
        detail = re.fullmatch(r"/api/profile-research/([^/]+)", path)
        if detail:
            return projection.get_research(
                owner=owner, research_ref=unquote(detail.group(1)),
            )
        raise KeyError("profile research route not found")

    def _patch_profile_research_routes(self, parsed) -> bool:
        match = re.fullmatch(
            r"/api/profile-research/([^/]+)/lifecycle", parsed.path,
        )
        if not match:
            return False
        session = self._profile_research_session()
        if session is None:
            return True
        owner = str(session["username"])
        try:
            payload = self._json_body(256 * 1024)
            if not isinstance(payload, dict):
                raise TypeError("request body must be an object")
            value = transition_lifecycle(
                owner=owner,
                work_package_ref=unquote(match.group(1)),
                target=str(payload.get("target") or ""),
                expected_revision=int(payload.get("expected_revision") or 0),
                actor=owner,
                reason=str(payload.get("reason") or ""),
            )
        except Exception as exc:
            self._profile_research_error(exc)
            return True
        self._profile_research_response(value)
        return True


__all__ = ["ProfileResearchRoutesMixin"]
