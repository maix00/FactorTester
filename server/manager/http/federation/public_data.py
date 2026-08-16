"""Authenticated peer projections for research and client catalogs."""

from __future__ import annotations

import json

from server.manager.http.responses import json_response
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
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
                raise ValueError("federated public-data payload must be an object")
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
        if kind == "catalog":
            if operation == "profiles":
                return {
                    "profiles": self.state.client_state.profiles(
                        principal, include_local_paths=False,
                    ),
                }
            if operation == "factors":
                from server.manager.services.public_catalog import (
                    public_factor_library,
                )
                public = public_factor_library()
                if viewer is None:
                    return public
                from server.modules.custom_factors.client_library import (
                    build_client_library_projection,
                )
                private = self.state.client_state.factor_library(principal)
                return build_client_library_projection({
                    "factors": [
                        *list(public.get("factors") or []),
                        *list(private.get("factors") or []),
                    ],
                    "errors": [
                        *list(public.get("errors") or []),
                        *list(private.get("errors") or []),
                    ],
                }, principal=principal)
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
