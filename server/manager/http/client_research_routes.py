"""Authenticated client workspace and local research GET routes."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote

from server.manager.http.local_run_routes import ClientLocalRunRoutesMixin
from server.manager.http.responses import json_response
from server.manager.services.client_state import ProfileAlreadyExistsError
from server.manager.services.profile_directory import ProfileDirectoryError


class ClientResearchRoutesMixin(ClientLocalRunRoutesMixin):
    """Expose owner-scoped local research and workspace projections."""

    def _post_client_research_routes(self, parsed) -> bool:
        if self._post_local_run_routes(parsed):
            return True
        if parsed.path in {
            "/api/client/profile-directory/conversation-sharing",
        }:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                payload = self._json_body(256 * 1024)
                if not isinstance(payload, dict):
                    raise ValueError("request body must be an object")
                principal = str(session["username"])
                directory = self.state.profile_directory
                if parsed.path.endswith("conversation-sharing"):
                    profile_id = str(payload.get("profile_id") or "").strip()
                    if not profile_id:
                        raise ValueError("profile_id is required")
                    directory_value = directory.directory(
                        principal, scope="mine", query=profile_id, page_size=100,
                    )
                    target = next(
                        (
                            item for item in directory_value.get("items", [])
                            if item.get("profile_id") == profile_id
                            and item.get("owner_ref") == principal
                            and item.get("source_server_id") == directory.server_id
                        ),
                        None,
                    )
                    if not target or not target.get("capabilities", {}).get("edit"):
                        raise PermissionError("only the Profile owner may change sharing")
                    enabled = self.state.agent_profiles.set_conversation_sharing(
                        principal, profile_id, bool(payload.get("enabled")),
                    )
                    json_response(self, {
                        "success": True,
                        "profile_id": profile_id,
                        "conversation_sharing": enabled,
                    })
                    return True
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (AttributeError, ProfileDirectoryError, TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
                return True
        if parsed.path not in {
            "/api/client/profiles/create",
            "/api/client/profiles/sync",
        }:
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        try:
            payload = self._json_body(4 * 1024 * 1024)
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            principal = str(session["username"])
            if parsed.path == "/api/client/profiles/create":
                receipt = self.state.client_state.create_profile(
                    principal,
                    profile_id=payload.get("profile_id"),
                    display_name=payload.get("display_name"),
                )
            else:
                profile = payload.get("profile")
                if not isinstance(profile, dict):
                    raise ValueError("profile must be an object")
                receipt = self.state.client_state.sync_profile(
                    principal, profile,
                )
        except ProfileAlreadyExistsError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        status = 201 if parsed.path == "/api/client/profiles/create" else 200
        json_response(self, {"success": True, **receipt}, status)
        return True

    def _get_client_research_routes(self, parsed) -> bool:
        if self._get_local_run_routes(parsed):
            return True
        if parsed.path in {
            "/api/client/profile-directory",
            "/api/client/profile-directory/profile",
            "/api/client/profile-directory/conversations",
            "/api/client/profile-directory/conversation-items",
        }:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                principal = str(session["username"])
                directory = self.state.profile_directory
                scope = str(query.get("scope", ["mine"])[0] or "mine")
                if parsed.path == "/api/client/profile-directory":
                    value = directory.directory(
                        principal,
                        scope=scope,
                        query=str(query.get("query", [""])[0] or ""),
                        page=int(query.get("page", ["1"])[0] or 1),
                        page_size=int(query.get("page_size", ["20"])[0] or 20),
                        server_id=str(query.get("server_id", [""])[0] or ""),
                        binding=str(query.get("binding", [""])[0] or ""),
                        agent=str(query.get("agent", [""])[0] or ""),
                    )
                elif parsed.path == "/api/client/profile-directory/profile":
                    value = directory.detail(
                        principal,
                        str(query.get("profile_key", [""])[0] or ""),
                        scope=scope,
                    )
                elif parsed.path == "/api/client/profile-directory/conversations":
                    value = {
                        "success": True,
                        "conversations": directory.conversations(
                            principal,
                            str(query.get("profile_key", [""])[0] or ""),
                            scope=scope,
                        ),
                    }
                else:
                    page = directory.conversation_items(
                        principal,
                        str(query.get("profile_key", [""])[0] or ""),
                        str(query.get("conversation_id", [""])[0] or ""),
                        scope=scope,
                        limit=int(query.get("limit", ["10"])[0] or 10),
                        after=str(query.get("after", [""])[0] or ""),
                        view=str(query.get("view", ["timeline"])[0] or "timeline"),
                        order=str(query.get("order", ["desc"])[0] or "desc"),
                    )
                    value = {"success": True, **page}
                json_response(self, value)
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
            except (AttributeError, ProfileDirectoryError, TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 400)
            except (ConnectionError, OSError, RuntimeError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        if parsed.path == "/api/client/profiles":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            profile_service = getattr(self.state, "federated_public_data", None)
            if profile_service is None:
                profile_service = self.state.client_state
            principal = str(session["username"])
            receipt = self.state.client_state.ensure_self_profile(principal)
            profiles = profile_service.profiles(principal)
            reserved = (
                receipt.get("profile")
                if isinstance(receipt, dict) else None
            )
            if (
                isinstance(reserved, dict)
                and not any(
                    str(item.get("profile_id") or "") == "self"
                    for item in profiles
                    if isinstance(item, dict)
                )
            ):
                profiles = [*profiles, reserved]
            agent_service = getattr(self.state, "agent_profiles", None)
            if agent_service is not None:
                profiles = agent_service.enrich(principal, profiles)
            json_response(self, {"profiles": profiles})
            return True
        if parsed.path == "/api/client/workspace":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "workspace": self.state.client_state.workspace(
                    str(session["username"]),
                ),
            })
            return True
        if parsed.path == "/api/client/research":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "success": True,
                "research": self.state.client_state.local_research(
                    str(session["username"]),
                ),
            })
            return True
        local_research_resource_match = re.fullmatch(
            r"/api/client/research/([^/]+)/local-resources/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_resource_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                raw, content_type, filename = self.state.client_state.local_research_resource(
                    str(session["username"]),
                    unquote(local_research_resource_match.group(1)),
                    local_research_resource_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "resource"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            disposition = (
                "inline" if parse_qs(parsed.query).get("inline") == ["1"]
                else "attachment"
            )
            self.send_header(
                "Content-Disposition", f'{disposition}; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        local_research_asset_match = re.fullmatch(
            r"/api/client/research/([^/]+)/assets/([a-f0-9]{24})",
            parsed.path,
        )
        if local_research_asset_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                raw, content_type, filename = self.state.client_state.local_research_asset(
                    str(session["username"]),
                    unquote(local_research_asset_match.group(1)),
                    local_research_asset_match.group(2),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            safe_filename = re.sub(
                r"[^A-Za-z0-9._-]", "_", Path(filename).name,
            ) or "asset"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Disposition", f'inline; filename="{safe_filename}"',
            )
            self.send_header("Cache-Control", "private, no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return True
        local_research_component_match = re.fullmatch(
            r"/api/client/research/([^/]+)/chapters/([^/]+)/components/([^/]+)",
            parsed.path,
        )
        if local_research_component_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                value = self.state.client_state.local_research_component(
                    str(session["username"]),
                    unquote(local_research_component_match.group(1)),
                    unquote(local_research_component_match.group(2)),
                    unquote(local_research_component_match.group(3)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        local_research_chapter_match = re.fullmatch(
            r"/api/client/research/([^/]+)/(index|chapters/[^/]+)", parsed.path,
        )
        if local_research_chapter_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            local_ref = unquote(local_research_chapter_match.group(1))
            suffix = local_research_chapter_match.group(2)
            try:
                if suffix == "index":
                    value = self.state.client_state.local_research_index(
                        str(session["username"]), local_ref,
                    )
                else:
                    chapter_id = unquote(suffix.split("/", 1)[1])
                    value = self.state.client_state.local_research_chapter(
                        str(session["username"]), local_ref, chapter_id,
                        include_content=parse_qs(parsed.query).get("metadata") != ["1"],
                    )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        local_research_match = re.fullmatch(
            r"/api/client/research/([^/]+)", parsed.path,
        )
        if local_research_match:
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            try:
                value = self.state.client_state.local_research_report(
                    str(session["username"]),
                    unquote(local_research_match.group(1)),
                )
            except PermissionError as exc:
                json_response(self, {"success": False, "error": str(exc)}, 403)
                return True
            except (OSError, ValueError, KeyError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 404)
                return True
            json_response(self, {"success": True, **value})
            return True
        if parsed.path == "/api/client/preferences":
            session = self._session()
            if session is None:
                json_response(self, {"success": False, "error": "login required"}, 401)
                return True
            json_response(self, {
                "preferences": self.state.user_preferences.read(
                    str(session["username"]),
                ),
            })
            return True
        if self._serve_sqlite_web(parsed, method="GET"):
            return True
        return False
