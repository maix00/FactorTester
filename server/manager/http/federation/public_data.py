"""Authenticated peer projections for research and client catalogs."""

from __future__ import annotations

import json

from server.manager.http.responses import json_response
from server.manager.services.factor_library_scopes import (
    compose_factor_library_scopes,
)
from server.manager.services.job_artifact_catalog import JobArtifactCatalog
from server.manager.services.job_artifact_query import JobArtifactQueryService
from server.manager.services.profile_directory import (
    PROFILE_DIRECTORY_PRINCIPAL,
    ProfileDirectoryService,
)
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)
from tools.data.account_manage import (
    direct_subordinate_accounts_for,
    get_account,
    is_super_admin_account,
)

VISITOR_PRINCIPAL = "__public_jobs__"


class FederationPublicDataRoutesMixin:
    """Serve bounded read-only data that a peer may present to its users."""

    def _federation_public_data(self) -> None:
        if not self._has_federation_proxy_token():
            json_response(self, {
                "success": False,
                "error": "federation proxy is unauthorized",
            }, 401)
            return
        try:
            request = self._json_body(256 * 1024)
            kind = str(request.get("kind") or "").strip()
            operation = str(request.get("operation") or "").strip()
            principal = str(request.get("principal") or "").strip()
            payload = request.get("payload")
            if not kind or not operation or not principal:
                raise ValueError("federated public-data request is incomplete")
            if not isinstance(payload, dict):
                raise TypeError("federated public-data payload must be an object")
            value = self._public_data_value(
                kind=kind,
                operation=operation,
                principal=principal,
                payload=payload,
            )
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except (ConnectionError, OSError, RuntimeError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        json_response(self, {"success": True, **value})

    def _public_data_value(
        self,
        *,
        kind: str,
        operation: str,
        principal: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        viewer = None if principal == VISITOR_PRINCIPAL else principal
        if kind == "research":
            return self._research_data_value(operation, viewer, payload)
        if kind == "job-artifacts":
            if operation == "list":
                return {
                    "artifacts": JobArtifactCatalog(self.state).list(
                        job_id=str(payload.get("job_id") or ""),
                        principal=principal,
                    ),
                }
            if operation == "query":
                query = payload.get("query")
                if not isinstance(query, dict):
                    raise ValueError("artifact query must be an object")
                return {
                    "data": JobArtifactQueryService(self.state).query(
                        job_id=str(payload.get("job_id") or ""),
                        name=str(payload.get("name") or ""),
                        principal=principal,
                        request=query,
                    ),
                }
        if kind == "catalog":
            if operation == "profiles":
                return {
                    "profiles": self.state.client_state.profiles(
                        principal, include_local_paths=False,
                    ),
                }
            if operation == "profiles-directory":
                if principal != PROFILE_DIRECTORY_PRINCIPAL:
                    raise PermissionError("Profile directory federation requires a Manager identity")
                owners = payload.get("owners")
                if not isinstance(owners, list) or len(owners) > 2048:
                    raise ValueError("Profile directory owners are invalid")
                rows = []
                for owner in sorted({str(item or "").strip() for item in owners if str(item or "").strip()}):
                    values = self.state.client_state.profiles(
                        owner, include_local_paths=False,
                    )
                    agent_service = getattr(self.state, "agent_profiles", None)
                    if agent_service is not None:
                        try:
                            values = agent_service.enrich(owner, values)
                        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                            pass
                    for value in values:
                        if isinstance(value, dict):
                            projected = dict(value) | {"owner_ref": owner}
                            if agent_service is not None:
                                try:
                                    projected["conversation_sharing"] = (
                                        agent_service.conversation_sharing(
                                            owner,
                                            str(value.get("profile_id") or ""),
                                        )
                                    )
                                    projected["conversation_count"] = len(
                                        agent_service.conversations(
                                            owner,
                                            str(value.get("profile_id") or ""),
                                        )
                                    )
                                except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                                    pass
                            rows.append(projected)
                return {"profiles": rows}
            if operation in {"profile-conversations", "profile-conversation-items"}:
                owner = str(payload.get("owner") or "").strip()
                profile_id = str(payload.get("profile_id") or "").strip()
                if not owner or not profile_id:
                    raise ValueError("Profile owner and profile_id are required")
                profile = next(
                    (
                        item for item in self.state.client_state.profiles(
                            owner, include_local_paths=False,
                        )
                        if isinstance(item, dict)
                        and str(item.get("profile_id") or "") == profile_id
                    ),
                    None,
                )
                if profile is None:
                    raise PermissionError("Profile is not available on this server")
                viewer = str(principal or "").strip()
                allowed = viewer == owner
                try:
                    allowed = allowed or is_super_admin_account(get_account(viewer))
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
                if not allowed:
                    direct_children = {
                        str(item.get("username") or "").strip()
                        for item in direct_subordinate_accounts_for(viewer)
                    }
                    # Direct parents can inspect direct-child Agent history by
                    # default.  The federation endpoint remains read-only and
                    # never exposes Agent control or file mutation APIs.
                    allowed = owner in direct_children
                if not allowed and ProfileDirectoryService.visible_to(profile, viewer):
                    allowed = True
                if not allowed:
                    raise PermissionError("Profile conversations are not visible to this account")
                agent_service = getattr(self.state, "agent_profiles", None)
                if agent_service is None:
                    return {"conversations": [], "items": []}
                if operation == "profile-conversations":
                    conversations = agent_service.conversations(owner, profile_id)
                    return {
                        "conversations": [
                            {
                                key: item.get(key)
                                for key in (
                                    "conversation_id", "profile_id", "title",
                                    "preview", "created_at", "updated_at", "active",
                                )
                                if key in item
                            }
                            for item in conversations
                        ],
                    }
                conversation_id = str(payload.get("conversation_id") or "").strip()
                if not conversation_id:
                    raise ValueError("conversation_id is required")
                supervisor = getattr(self.state, "agent_app_server", None)
                reader = getattr(supervisor, "conversation_items", None)
                if not callable(reader):
                    raise RuntimeError("authoritative Provider thread reader is unavailable")
                return reader(
                    owner,
                    profile_id,
                    conversation_id,
                    limit=int(payload.get("limit") or 10),
                    after=str(payload.get("after") or ""),
                    view=str(payload.get("view") or "results"),
                    order=str(payload.get("order") or "desc"),
                )
            if operation == "factors":
                from server.manager.services.public_catalog import (
                    public_factor_library,
                )
                public = public_factor_library()
                if viewer is None:
                    return compose_factor_library_scopes(
                        {"public": public}, principal=principal,
                    )
                scopes = {"public": public}
                scope_reader = getattr(
                    self.state.client_state, "factor_library_scopes", None,
                )
                if callable(scope_reader):
                    scopes.update(scope_reader(principal))
                else:
                    # Compatibility for a small/older Manager seam while all
                    # real Managers migrate to the scoped API.
                    scopes["mine"] = self.state.client_state.factor_library(
                        principal,
                    )
                return compose_factor_library_scopes(
                    scopes, principal=principal,
                )
            if operation == "factor-sets":
                if viewer is None:
                    raise PermissionError(
                        "visitor cannot read private factor sets"
                    )
                return {
                    "items": self.state.client_state.factor_sets(
                        principal,
                        str(payload.get("query") or ""),
                    ),
                }
        raise ValueError("unsupported federated public-data operation")

    def _research_data_value(
        self,
        operation: str,
        viewer: str | None,
        payload: dict[str, object],
    ) -> dict[str, object]:
        library = self.state.public_research
        if operation == "list":
            return {
                "reports": library.list_visible(viewer),
            }
        publication_id = str(payload.get("publication_id") or "")
        if not publication_id:
            raise ValueError("publication_id is required")
        if operation == "projection":
            return {"value": library.projection(publication_id, viewer)}
        if operation == "index":
            return {"value": library.index(publication_id, viewer)}
        args = payload.get("args")
        args = args if isinstance(args, list) else []
        if operation == "chapter":
            if len(args) != 1:
                raise ValueError("chapter_id is required")
            return {"value": library.chapter(
                publication_id,
                str(args[0]),
                viewer,
                include_content=bool(payload.get("include_content", True)),
            )}
        if operation == "component":
            if len(args) != 2:
                raise ValueError("chapter_id and component_id are required")
            return {"value": library.component(
                publication_id, str(args[0]), str(args[1]), viewer,
            )}
        if operation == "object-metadata":
            if len(args) != 1:
                raise ValueError("research object id is required")
            object_kind = str(payload.get("object_kind") or "").strip()
            if not object_kind:
                raise ValueError("research object kind is required")
            return {
                "kind": "object",
                "value": PublicResearchObjectStore(library).metadata(
                    publication_id, object_kind, str(args[0]), viewer,
                ),
            }
        if operation in {"asset", "attachment", "local_resource"}:
            raise ValueError("research object bytes require the 7997 data plane")
        raise ValueError("unsupported federated research operation")
