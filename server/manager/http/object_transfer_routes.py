"""Generic 7998 control routes for object uploads into a Manager."""

from __future__ import annotations

from server.manager.http.responses import json_response
from server.manager.objects.models import TransferObjectKind
from server.manager.objects.references import research_object_id
from server.manager.services.federated_public_data import VISITOR_PRINCIPAL
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)
from server.manager.transfers.peer_gateway import PeerControlError
from server.manager.transfers.planner import NodeUnavailable


_ACCESS_PATH = "/api/transfers/objects/access"
_DOWNLOAD_ACCESS_PATH = "/api/transfers/objects/download-access"
_RESEARCH_KINDS = frozenset({
    TransferObjectKind.RESEARCH_ASSET.value,
    TransferObjectKind.RESEARCH_ATTACHMENT.value,
    TransferObjectKind.RESEARCH_LOCAL_RESOURCE.value,
})


class ObjectTransferRoutesMixin:
    """Issue upload tickets without allowing arbitrary object destinations."""

    def _issue_object_download_access(self, parsed) -> bool:
        if parsed.path != _DOWNLOAD_ACCESS_PATH:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and not self._anonymous_ui_allowed():
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        principal = (
            str(session.get("username") or "").strip()
            if session is not None
            else str(visitor.principal or VISITOR_PRINCIPAL).strip()
            if visitor is not None
            else VISITOR_PRINCIPAL
        )
        viewer = None if principal == VISITOR_PRINCIPAL else principal
        try:
            payload = self._json_body(64 * 1024)
            object_kind = str(payload.get("object_kind") or "").strip()
            if object_kind not in _RESEARCH_KINDS:
                raise ValueError("object kind is not downloadable")
            publication_id = str(payload.get("publication_id") or "").strip()
            item_id = str(payload.get("item_id") or payload.get("object_id") or "").strip()
            if not publication_id or not item_id:
                raise ValueError("publication_id and object_id are required")
            research = getattr(
                self.state, "federated_public_research", self.state.public_research,
            )
            metadata = research.object_metadata(
                publication_id, object_kind, item_id, viewer,
            )
            expected_size = int(metadata.get("size_bytes") or 0)
            expected_sha256 = str(metadata.get("content_hash") or "").strip().lower()
            storage_server_id = str(
                metadata.get("storage_server_id") or self.state.server_id
            ).strip()
            if len(expected_sha256) != 64:
                raise ValueError("research object metadata has no content hash")
            object_id = research_object_id(publication_id, item_id)
            idempotency = str(
                self.headers.get("Idempotency-Key")
                or f"research-download:{object_kind}:{object_id}:{expected_sha256}"
            ).strip()
            access = self._rewrite_client_data_access(
                self.state.prepare_object_download(
                    principal=principal,
                    storage_server_id=storage_server_id,
                    object_kind=object_kind,
                    object_id=object_id,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    idempotency_key=idempotency,
                )
            )
        except NodeUnavailable as exc:
            json_response(self, {
                "success": False, "code": exc.code, "error": str(exc),
            }, 503)
            return True
        except PeerControlError as exc:
            json_response(self, {
                "success": False, "code": exc.code, "error": str(exc),
            }, 503)
            return True
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return True
        except (TypeError, ValueError, KeyError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
            return True
        except (ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, {
            "success": True,
            "object": {
                "object_kind": object_kind,
                "object_id": object_id,
                "filename": metadata.get("filename") or item_id,
                "content_type": metadata.get("content_type") or "application/octet-stream",
                "size_bytes": expected_size,
                "sha256": expected_sha256,
                "storage_server_id": storage_server_id,
            },
            "access": access,
        }, 201)
        return True

    def _issue_object_transfer_access(self, parsed) -> bool:
        if parsed.path != _ACCESS_PATH:
            return False
        session = self._session()
        if session is None and not self._is_loopback_client():
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        try:
            payload = self._json_body(256 * 1024)
            object_kind = str(payload.get("object_kind") or "").strip()
            if object_kind not in _RESEARCH_KINDS:
                raise ValueError("object kind is not uploadable")
            publication_id = str(payload.get("publication_id") or "").strip()
            object_id = str(payload.get("object_id") or "").strip()
            if not publication_id or not object_id:
                raise ValueError("publication_id and object_id are required")
            expected_object_id = research_object_id(publication_id, object_id)
            owner = self._publication_upload_owner(payload, publication_id, session)
            metadata = self.state.public_research.publication_metadata(
                publication_id,
            )
            if str(metadata.get("owner_ref") or "") != owner:
                raise PermissionError("research publication owner does not match")
            store = PublicResearchObjectStore(self.state.public_research)
            descriptor = store.descriptor(
                publication_id, object_kind, object_id, owner,
            )
            expected_size = int(payload.get("size_bytes"))
            expected_sha256 = str(payload.get("sha256") or "").strip().lower()
            declared_size = descriptor.get("size_bytes")
            if declared_size is not None and expected_size != int(declared_size):
                raise ValueError("research object size does not match metadata")
            if expected_sha256 != str(descriptor.get("content_hash") or ""):
                raise ValueError("research object hash does not match metadata")
            filename = _filename(payload.get("filename"))
            storage_server_id = str(
                payload.get("storage_server_id")
                or metadata.get("storage_server_id")
                or self.state.server_id
            ).strip()
            if storage_server_id != self.state.server_id:
                raise ValueError(
                    "research object upload must target its source Manager"
                )
            idempotency = str(
                self.headers.get("Idempotency-Key")
                or f"research-upload:{expected_object_id}:{expected_sha256}"
            ).strip()
            access = self._rewrite_client_data_access(
                self.state.prepare_object_upload(
                    principal=owner,
                    storage_server_id=storage_server_id,
                    object_kind=object_kind,
                    object_id=expected_object_id,
                    filename=filename,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    idempotency_key=idempotency,
                    content_type=str(
                        payload.get("content_type") or descriptor.get("content_type")
                        or "application/octet-stream"
                    ),
                )
            )
        except NodeUnavailable as exc:
            json_response(self, {
                "success": False, "code": exc.code, "error": str(exc),
            }, 503)
            return True
        except PeerControlError as exc:
            json_response(self, {
                "success": False, "code": exc.code, "error": str(exc),
            }, 503)
            return True
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, {
            "success": True,
            "object": {
                "object_kind": object_kind,
                "object_id": expected_object_id,
                "size_bytes": expected_size,
                "sha256": expected_sha256,
            },
            "access": access,
        }, 201)
        return True

    def _publication_upload_owner(self, payload, publication_id, session) -> str:
        if session is not None:
            owner = str(session.get("username") or "").strip()
            supplied = str(payload.get("owner_ref") or "").strip()
            if supplied and supplied != owner:
                raise PermissionError("publication upload owner does not match session")
            return owner
        owner = str(payload.get("owner_ref") or "").strip()
        if not owner:
            raise ValueError("owner_ref is required for a local publication upload")
        return owner


def _filename(value: object) -> str:
    name = str(value or "").strip()
    if (
        not name or len(name) > 255 or name in {".", ".."}
        or "/" in name or "\\" in name
    ):
        raise ValueError("object filename is invalid")
    return name


__all__ = ["ObjectTransferRoutesMixin"]
