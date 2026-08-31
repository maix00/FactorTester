"""Generic 7998 control routes for object uploads into a Manager."""

from __future__ import annotations

import os

from scripts.data_dir import CACHE_DB_PATH
from server.manager.http.responses import json_response
from server.manager.objects.adapters.evidence_file import EvidenceFileStore
from server.manager.objects.adapters.factor_source import FactorSourceStore
from server.manager.objects.models import TransferObjectKind
from server.manager.objects.references import research_object_id
from server.manager.services.federated_public_data import VISITOR_PRINCIPAL
from server.manager.services.profile_workspace_browser import (
    ProfileWorkspaceError,
)
from server.manager.transfers.peer_gateway import PeerControlError
from server.manager.transfers.planner import NodeUnavailable
from server.services.research_evidence_catalog import evidence_source
from tools.cli.release.research_reporting.public_research.object_store import (
    PublicResearchObjectStore,
)
from tools.data.account_manage import can_view_user_scope

_ACCESS_PATH = "/api/transfers/objects/access"
_DOWNLOAD_ACCESS_PATH = "/api/transfers/objects/download-access"
_RESEARCH_KINDS = frozenset({
    TransferObjectKind.RESEARCH_ASSET.value,
    TransferObjectKind.RESEARCH_ATTACHMENT.value,
    TransferObjectKind.RESEARCH_LOCAL_RESOURCE.value,
})
_UPLOADABLE_KINDS = _RESEARCH_KINDS | frozenset({
    TransferObjectKind.EVIDENCE_FILE.value,
})
_DOWNLOADABLE_KINDS = _RESEARCH_KINDS | frozenset({
    TransferObjectKind.PROFILE_WORKSPACE.value,
    TransferObjectKind.FACTOR_SOURCE.value,
    TransferObjectKind.EVIDENCE_FILE.value,
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
            if object_kind not in _DOWNLOADABLE_KINDS:
                raise ValueError("object kind is not downloadable")
            if object_kind == TransferObjectKind.EVIDENCE_FILE.value:
                if session is None:
                    raise PermissionError("login required")
                evidence_ref = str(payload.get("evidence_ref") or "").strip()
                source_ref = str(payload.get("source_ref") or "").strip()
                catalog = getattr(self.state, "research_catalog", None)
                if catalog is None:
                    raise RuntimeError("Research catalog is unavailable")
                access_decision = catalog.resolve_evidence_access(
                    evidence_ref=evidence_ref, viewer=principal,
                )
                try:
                    evidence_owner = catalog.evidence_owner_ref(evidence_ref)
                except KeyError:
                    evidence_owner = principal
                source = evidence_source(
                    owner=evidence_owner,
                    evidence_ref=evidence_ref,
                    source_ref=source_ref,
                )
                if source is not None and evidence_owner == principal:
                    access_decision = {
                        "can_view": True, "can_preview": True,
                        "can_download": True, "can_manage": True,
                        "access_basis": "owner",
                    }
                if not access_decision.get("can_download"):
                    raise PermissionError("Evidence file download is not authorized")
                if source is None or source.get("source_kind") != "file":
                    raise KeyError("Evidence does not cite this file source")
                identity = source.get("identity") or {}
                object_id = str(identity.get("object_id") or "").strip()
                expected_size = int(identity.get("size_bytes") or 0)
                expected_sha256 = str(source.get("content_hash") or "").lower()
                storage_server_id = str(identity.get("storage_server_id") or "").strip()
                if not object_id or not storage_server_id:
                    raise FileNotFoundError("Evidence file has not been uploaded")
                metadata = {
                    "filename": identity.get("filename") or "evidence-file",
                    "content_type": identity.get("content_type") or "application/octet-stream",
                }
            elif object_kind == TransferObjectKind.PROFILE_WORKSPACE.value:
                if session is None:
                    raise PermissionError("login required")
                profile_id = str(payload.get("profile_id") or "").strip()
                relative_path = str(payload.get("path") or "")
                metadata = self.state.agent_profiles.profile_workspace_file(
                    principal, profile_id, relative_path,
                )
                expected_size = int(metadata.get("size_bytes") or 0)
                expected_sha256 = str(metadata.get("sha256") or "").strip().lower()
                storage_server_id = str(
                    metadata.get("storage_server_id") or self.state.server_id
                ).strip()
                object_id = str(metadata.get("object_id") or "").strip()
            elif object_kind == TransferObjectKind.FACTOR_SOURCE.value:
                if session is None:
                    raise PermissionError("login required")
                object_id = str(payload.get("object_id") or "").strip()
                if not object_id:
                    raise ValueError("object_id is required")
                factor_store = FactorSourceStore(database=CACHE_DB_PATH)
                metadata = factor_store.metadata(object_id)
                owner = str(metadata.get("source_owner") or "").strip()
                if owner != "public" and owner != principal and not can_view_user_scope(
                    principal, owner,
                ):
                    raise PermissionError("factor source is outside your visible scope")
                supplied_hash = str(
                    payload.get("source_sha256") or payload.get("sha256") or ""
                ).strip().lower()
                expected_sha256 = str(
                    metadata.get("source_sha256") or ""
                ).strip().lower()
                if supplied_hash and supplied_hash != expected_sha256:
                    raise ValueError("factor source hash does not match metadata")
                expected_size = int(metadata.get("source_bytes") or 0)
                storage_server_id = str(
                    payload.get("storage_server_id")
                    or os.environ.get("FACTORTESTER_SERVER_ID")
                    or self.state.server_id
                ).strip()
                metadata = {
                    **metadata,
                    "filename": f"{metadata.get('factor_id') or 'factor'}.py",
                    "content_type": "text/x-python",
                    "storage_server_id": storage_server_id,
                }
            else:
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
                    content_type=str(
                        metadata.get("content_type")
                        or metadata.get("media_type")
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
        except FileNotFoundError as exc:
            json_response(self, {
                "success": False,
                "code": "evidence_source_unavailable",
                "error": str(exc),
            }, 409)
            return True
        except (ProfileWorkspaceError, TypeError, ValueError, KeyError) as exc:
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
                "filename": metadata.get("filename") or metadata.get("path") or object_id,
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
            if object_kind not in _UPLOADABLE_KINDS:
                raise ValueError("object kind is not uploadable")
            if object_kind == TransferObjectKind.EVIDENCE_FILE.value:
                if session is None:
                    raise PermissionError("login required")
                owner = str(session.get("username") or "").strip()
                expected_size = int(payload.get("size_bytes"))
                expected_sha256 = str(payload.get("sha256") or "").strip().lower()
                object_id = str(
                    payload.get("object_id")
                    or f"evidence-file:v1:{expected_sha256}"
                ).strip()
                EvidenceFileStore.digest_from_id(object_id)
                if not object_id.endswith(expected_sha256):
                    raise ValueError("Evidence file object id does not match its hash")
                storage_server_id = str(
                    payload.get("storage_server_id") or self.state.server_id
                ).strip()
                if storage_server_id != self.state.server_id:
                    raise ValueError("Evidence file upload must target this Manager")
                filename = _filename(payload.get("filename"))
                idempotency = str(
                    self.headers.get("Idempotency-Key")
                    or f"evidence-file-upload:{owner}:{expected_sha256}"
                ).strip()
                access = self._rewrite_client_data_access(
                    self.state.prepare_object_upload(
                        principal=owner,
                        storage_server_id=storage_server_id,
                        object_kind=object_kind,
                        object_id=object_id,
                        filename=filename,
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        idempotency_key=idempotency,
                        content_type=str(payload.get("content_type") or "application/octet-stream"),
                    )
                )
                json_response(self, {
                    "success": True,
                    "object": {
                        "object_kind": object_kind, "object_id": object_id,
                        "size_bytes": expected_size, "sha256": expected_sha256,
                        "storage_server_id": storage_server_id,
                    },
                    "access": access,
                }, 201)
                return True
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
