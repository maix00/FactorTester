"""Profile runtime, Agent claim, and model-provider HTTP routes."""

from __future__ import annotations

import re
import sqlite3
from typing import Any
from urllib.parse import parse_qs

from server.manager.http.responses import json_response
from server.manager.services.agent_profiles import AgentProfileService
from server.manager.services.agent_runtime_capabilities import public_capabilities
from server.manager.services.agent_skill_catalog import AgentSkillCatalogError
from server.manager.services.profile_workspace_browser import ProfileWorkspaceError
from server.manager.storage.agent_provider_store import ProviderStoreError
from server.manager.storage.profile_runtime_store import (
    ProfileClaimConflict,
    ProfileRuntimeError,
)

PROFILE_ID_PATTERN = r"[^/]+"
PROVIDER_ID_PATTERN = r"[^/]+"


class AgentRoutesMixin:
    """Expose only the authenticated owner's Agent/Profile state."""

    def _agent_service(self) -> AgentProfileService:
        service = getattr(self.state, "agent_profiles", None)
        if not isinstance(service, AgentProfileService):
            raise RuntimeError("Agent Profile service is unavailable")
        return service

    def _agent_session(self) -> dict[str, object] | None:
        session = self._session()
        if session is not None:
            return session
        json_response(
            self,
            {"success": False, "error": "login required"},
            401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        return None

    def _agent_principal(self, session: dict[str, object]) -> str:
        principal = str(session.get("username") or "").strip()
        if not principal:
            raise ProfileRuntimeError("authenticated principal is missing")
        return principal

    def _raw_body(self, maximum: int) -> bytes:
        """Read the raw request body up to ``maximum`` bytes (binary-safe)."""
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > maximum:
            raise ProfileWorkspaceError("invalid request body")
        data = self.rfile.read(length) if length else b""
        if len(data) != length:
            raise ProfileWorkspaceError("incomplete request body")
        return data

    def _local_profiles(self, principal: str) -> list[dict[str, Any]]:
        profile_service = getattr(self.state, "federated_public_data", None)
        if profile_service is None:
            profile_service = self.state.client_state
        profiles = profile_service.profiles(principal)
        return [item for item in profiles if isinstance(item, dict)]

    def _profile_exists(self, principal: str, profile_id: str) -> bool:
        return any(
            str(item.get("profile_id") or "") == profile_id
            for item in self._local_profiles(principal)
        )

    def _profile(self, principal: str, profile_id: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self._local_profiles(principal)
                if str(item.get("profile_id") or "") == profile_id
            ),
            None,
        )

    def _get_agent_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/agent-skills":
            session = self._agent_session()
            if session is None:
                return True
            try:
                runtime_kind = (
                    parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )
                    .get("runtime_kind", ["server"])[0]
                    .strip()
                    or "server"
                )
                skills = self._agent_service().available_skills(
                    runtime_kind=runtime_kind,
                )
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (
                AgentSkillCatalogError,
                ProfileRuntimeError,
                RuntimeError,
                ValueError,
            ) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(
                self,
                {"success": True, "runtime_kind": runtime_kind, "skills": skills},
            )
            return True

        if parsed.path == "/api/client/profile-skills":
            session = self._agent_session()
            if session is None:
                return True
            try:
                principal = self._agent_principal(session)
                profile_id = (
                    parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )
                    .get("profile_id", [""])[0]
                    .strip()
                )
                if not self._profile_exists(principal, profile_id):
                    raise ProfileRuntimeError(
                        "Profile does not belong to current account"
                    )
                value = self._agent_service().profile_skills(principal, profile_id)
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (
                AgentSkillCatalogError,
                ProfileRuntimeError,
                RuntimeError,
                ValueError,
            ) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(self, {"success": True, **value})
            return True

        if parsed.path == "/api/client/profile-workspace":
            session = self._agent_session()
            if session is None:
                return True
            try:
                principal = self._agent_principal(session)
                query = parse_qs(parsed.query, keep_blank_values=True)
                profile_id = query.get("profile_id", [""])[0].strip()
                if not self._profile_exists(principal, profile_id):
                    raise ProfileWorkspaceError(
                        "Profile does not belong to current account",
                    )
                relative_path = query.get("path", [""])[0]
                value = self._agent_service().profile_workspace(
                    principal,
                    profile_id,
                    relative_path,
                )
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (ProfileWorkspaceError, RuntimeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True

        if parsed.path == "/api/client/agent-models":
            session = self._agent_session()
            if session is None:
                return True
            try:
                principal = self._agent_principal(session)
                runtime_kind = (
                    parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )
                    .get("runtime_kind", [""])[0]
                    .strip()
                    or None
                )
                providers = self._agent_service().providers(
                    principal,
                    runtime_kind=runtime_kind,
                )
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (
                ProviderStoreError,
                ProfileRuntimeError,
                RuntimeError,
                ValueError,
            ) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(
                self,
                {
                    "success": True,
                    "providers": providers,
                    "runtime_capabilities": public_capabilities(),
                },
            )
            return True

        if parsed.path == "/api/client/agent-runtime":
            session = self._agent_session()
            if session is None:
                return True
            try:
                principal = self._agent_principal(session)
                profiles = self._local_profiles(principal)
                enriched = self._agent_service().enrich(principal, profiles)
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (
                ProviderStoreError,
                ProfileRuntimeError,
                RuntimeError,
                ValueError,
            ) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(
                self,
                {
                    "success": True,
                    "server_id": self.state.server_id,
                    "profiles": enriched,
                },
            )
            return True

        if parsed.path == "/api/client/profile-claims":
            session = self._agent_session()
            if session is None:
                return True
            try:
                principal = self._agent_principal(session)
                claims = self._agent_service().claims(principal)
            except sqlite3.Error:
                json_response(
                    self,
                    {"success": False, "error": "local Agent state is unavailable"},
                    503,
                )
                return True
            except (
                ProviderStoreError,
                ProfileRuntimeError,
                RuntimeError,
                ValueError,
            ) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
            json_response(self, {"success": True, "claims": claims})
            return True

        return False

    def _post_agent_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/profile-workspace/upload":
            session = self._agent_session()
            if session is None:
                return True
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                principal = self._agent_principal(session)
                profile_id = query.get("profile_id", [""])[0].strip()
                if not self._profile_exists(principal, profile_id):
                    raise ProfileWorkspaceError(
                        "Profile does not belong to current account"
                    )
                relative_path = query.get("path", [""])[0]
                filename = query.get("filename", [""])[0]
                if query.get("chat_attachment", [""])[0] == "1":
                    from datetime import datetime, timezone
                    from uuid import uuid4
                    relative_path = f"uploads/{datetime.now(timezone.utc):%Y-%m-%d}/{uuid4().hex}"
                data = self._raw_body(64 * 1024 * 1024)
                result = self._agent_service().save_profile_workspace_file(
                    principal,
                    profile_id,
                    relative_path,
                    data,
                    filename=filename,
                )
                json_response(self, {"success": True, **result}, 201)
            except (ProfileWorkspaceError, RuntimeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
            return True

        duplicate_match = re.fullmatch(
            rf"/api/client/agent-models/({PROVIDER_ID_PATTERN})/duplicate",
            parsed.path,
        )
        if (
            parsed.path
            not in {
                "/api/client/agent-models",
                "/api/client/agent-models/test",
                "/api/client/profile-skills",
                "/api/client/profile-runtime",
                "/api/client/profile-claims",
                "/api/client/profile-claims/heartbeat",
                "/api/client/profile-claims/release",
            }
            and duplicate_match is None
        ):
            return False
        session = self._agent_session()
        if session is None:
            return True
        try:
            principal = self._agent_principal(session)
            payload = self._json_body(128 * 1024)
            service = self._agent_service()
            if duplicate_match is not None:
                provider = service.duplicate_provider(
                    principal,
                    duplicate_match.group(1),
                )
                json_response(self, {"success": True, "provider": provider}, 201)
                return True
            if parsed.path == "/api/client/agent-models/test":
                result = service.test_provider(principal, payload)
                json_response(self, {"success": True, "test": result})
                return True

            if parsed.path == "/api/client/agent-models":
                provider = service.save_provider(principal, payload)
                json_response(self, {"success": True, "provider": provider}, 201)
                return True

            if parsed.path == "/api/client/profile-skills":
                profile_id = str(payload.get("profile_id") or "").strip()
                if not self._profile_exists(principal, profile_id):
                    raise ProfileRuntimeError(
                        "Profile does not belong to current account"
                    )
                skill_ids = payload.get("skill_ids")
                if not isinstance(skill_ids, list):
                    raise AgentSkillCatalogError("skill_ids must be a list")
                value = service.set_profile_skills(
                    principal,
                    profile_id,
                    [str(item) for item in skill_ids],
                )
                json_response(self, {"success": True, **value})
                return True

            if parsed.path == "/api/client/profile-runtime":
                profile_id = str(payload.get("profile_id") or "").strip()
                runtime_kind = str(payload.get("runtime_kind") or "").strip()
                profile = self._profile(principal, profile_id)
                if profile is None:
                    raise ProfileRuntimeError(
                        "Profile does not belong to current account"
                    )
                server_metadata = profile.get("server")
                existing_server_id = str(
                    profile.get("source_server_id")
                    or (
                        server_metadata.get("server_id")
                        if isinstance(server_metadata, dict)
                        else ""
                    )
                ).strip()
                if (
                    runtime_kind == "server"
                    and existing_server_id
                    and existing_server_id != str(self.state.server_id)
                ):
                    raise ProfileRuntimeError("Profile belongs to another server")
                if runtime_kind == "client" and not self._is_local_ftclient():
                    raise PermissionError(
                        "client Profile bindings must be created by the local client"
                    )
                executor_id = str(payload.get("executor_id") or "").strip()
                if runtime_kind == "server" and not executor_id:
                    executor_id = str(self.state.server_id)
                runtime = service.bind_runtime(
                    principal,
                    profile_id,
                    runtime_kind=runtime_kind,
                    executor_id=executor_id,
                )
                json_response(self, {"success": True, "runtime": runtime})
                return True

            if parsed.path == "/api/client/profile-claims":
                profile_id = str(payload.get("profile_id") or "").strip()
                if not self._profile_exists(principal, profile_id):
                    raise ProfileRuntimeError(
                        "Profile does not belong to current account"
                    )
                result = service.claim(
                    principal,
                    profile_id,
                    provider_id=str(payload.get("provider_id") or "").strip(),
                    agent_id=str(payload.get("agent_id") or "").strip(),
                )
                json_response(self, {"success": True, **result}, 201)
                return True

            if parsed.path == "/api/client/profile-claims/heartbeat":
                result = service.heartbeat(
                    principal,
                    str(payload.get("claim_id") or "").strip(),
                    str(payload.get("agent_id") or "").strip(),
                )
                json_response(self, {"success": True, **result})
                return True

            force = (
                bool(payload.get("force"))
                and str(
                    session.get("role") or "",
                )
                == "super_admin"
            )
            result = service.release(
                principal,
                str(payload.get("claim_id") or "").strip(),
                agent_id=str(payload.get("agent_id") or "").strip(),
                force=force,
            )
            json_response(self, {"success": True, **result})
            return True
        except sqlite3.Error:
            json_response(
                self,
                {"success": False, "error": "local Agent state is unavailable"},
                503,
            )
            return True
        except ProfileClaimConflict as exc:
            json_response(
                self,
                {
                    "success": False,
                    "error": str(exc),
                    "claim": AgentProfileService._public_claim(exc.claim),
                },
                409,
            )
            return True
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return True
        except (
            AgentSkillCatalogError,
            ProviderStoreError,
            ProfileRuntimeError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            json_response(
                self,
                {
                    "success": False,
                    "error": str(exc),
                    "code": str(
                        getattr(exc, "code", "agent_request_invalid")
                        or "agent_request_invalid"
                    ),
                },
                400,
            )
            return True

    def _delete_agent_routes(self, parsed) -> bool:
        if parsed.path == "/api/client/profile-workspace":
            session = self._agent_session()
            if session is None:
                return True
            try:
                payload = self._json_body(64 * 1024)
                principal = self._agent_principal(session)
                profile_id = str(payload.get("profile_id") or "").strip()
                if not self._profile_exists(principal, profile_id):
                    raise ProfileWorkspaceError(
                        "Profile does not belong to current account"
                    )
                result = self._agent_service().delete_profile_workspace_file(
                    principal,
                    profile_id,
                    str(payload.get("path") or ""),
                )
                json_response(self, {"success": True, **result})
            except (ProfileWorkspaceError, RuntimeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        match = re.fullmatch(
            rf"/api/client/agent-models/({PROVIDER_ID_PATTERN})",
            parsed.path,
        )
        if not match:
            return False
        session = self._agent_session()
        if session is None:
            return True
        try:
            principal = self._agent_principal(session)
            deleted = self._agent_service().delete_provider(
                principal,
                match.group(1),
            )
        except sqlite3.Error:
            json_response(
                self,
                {"success": False, "error": "local Agent state is unavailable"},
                503,
            )
            return True
        except (
            ProviderStoreError,
            ProfileRuntimeError,
            RuntimeError,
            ValueError,
        ) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        json_response(self, {"success": True, "deleted": deleted})
        return True
