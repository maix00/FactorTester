"""Issue short-lived public-7997 access for retained Job artifacts."""

from __future__ import annotations

import re
import secrets
from urllib.parse import unquote

from server.manager.domain.federation import TargetNotFound, TargetUnavailable
from server.manager.http.job_public_projection import (
    PUBLIC_JOB_PRINCIPAL,
    read_principals,
)
from server.manager.http.responses import json_response
from server.manager.services.job_artifact_catalog import JobArtifactCatalog
from server.manager.services.job_artifact_query import JobArtifactQueryService
from server.manager.transfers.peer_gateway import PeerControlError
from server.manager.transfers.planner import NodeUnavailable

_ACCESS_PATH = re.compile(
    r"^/api/jobs/([A-Za-z0-9._-]{1,128})/artifacts/"
    r"([^/]{1,512})/access$"
)
_QUERY_PATH = re.compile(
    r"^/api/jobs/([A-Za-z0-9._-]{1,128})/artifacts/"
    r"([^/]{1,512})/query$"
)
_STATUS_PATH = re.compile(
    r"^/api/transfers/([A-Za-z0-9._-]{1,128})$"
)
_SUBMISSION_ACCESS_PATH = "/api/transfers/submissions/access"


class JobTransferRoutesMixin:
    def _query_artifact_projection(self, parsed) -> bool:
        match = _QUERY_PATH.fullmatch(parsed.path)
        if match is None:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and not self._anonymous_ui_allowed():
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        principal = (
            str(session["username"])
            if session is not None
            else visitor.principal if visitor is not None
            else PUBLIC_JOB_PRINCIPAL
        )
        job_id = unquote(match.group(1))
        name = unquote(match.group(2))
        if not name or name in {".", ".."} or "\\" in name:
            json_response(
                self, {"success": False, "error": "artifact name is invalid"}, 400,
            )
            return True
        try:
            request = self._json_body(64 * 1024)
            routes = self._job_routes(
                parsed, principal, for_artifact_storage=True,
            )
            principals = read_principals(
                self.state, principal, job_id, routes=routes,
            )
            selected = None
            for route in routes:
                for lookup_principal in principals:
                    try:
                        payload = self._job_artifact_query_payload(
                            route,
                            job_id=job_id,
                            name=name,
                            principal=lookup_principal,
                            request=request,
                        )
                    except KeyError:
                        continue
                    selected = (route, payload)
                    break
                if selected is not None:
                    break
            if selected is None:
                raise KeyError("artifact was not found")
            route, payload = selected
        except KeyError as exc:
            json_response(
                self, {"success": False, "error": str(exc).strip("'")}, 404,
            )
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (NodeUnavailable, TargetUnavailable, TargetNotFound) as exc:
            json_response(self, {
                "success": False,
                "code": getattr(exc, "code", "storage_server_unavailable"),
                "error": str(exc),
            }, 503)
            return True
        except (PeerControlError, ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, {
            "success": True,
            "storage_server_id": route.server_id,
            "data": payload.get("data") or {},
        })
        return True

    def _issue_submission_transfer_access(self, parsed) -> bool:
        if parsed.path != _SUBMISSION_ACCESS_PATH:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if visitor is not None and not visitor.can_submit:
            json_response(
                self,
                {"success": False, "error": "访客模式不能提交任务"},
                403,
            )
            return True
        if session is None and not self._anonymous_ui_allowed():
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if session is not None:
            principal = str(session["username"])
        elif visitor is not None:
            principal = visitor.principal
        else:
            principal = "__public_jobs__"
        try:
            payload = self._json_body(64 * 1024)
            name = _submission_name(payload.get("name"))
            job_id = str(payload.get("job_id") or "").strip()
            if not job_id or len(job_id) > 128:
                raise ValueError("job_id is required and must be at most 128 characters")
            storage_server_id = str(
                payload.get("storage_server_id") or self.state.server_id
            ).strip()
            idempotency = str(
                self.headers.get("Idempotency-Key") or secrets.token_hex(16)
            ).strip()
            access = self._rewrite_client_data_access(
                self.state.prepare_submission_upload(
                principal=principal,
                storage_server_id=storage_server_id,
                job_id=job_id,
                name=name,
                expected_size=int(payload.get("size_bytes")),
                expected_sha256=str(payload.get("sha256") or ""),
                content_type=str(
                    payload.get("content_type") or "application/octet-stream"
                ),
                idempotency_key=idempotency,
                )
            )
        except NodeUnavailable as exc:
            json_response(self, {
                "success": False,
                "code": exc.code,
                "error": str(exc),
            }, 503)
            return True
        except PeerControlError as exc:
            json_response(self, {
                "success": False,
                "code": exc.code,
                "error": str(exc),
            }, 503)
            return True
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return True
        except (ConnectionError, OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return True
        json_response(self, {"success": True, "access": access}, 201)
        return True

    def _get_transfer_access_status(self, parsed) -> bool:
        match = _STATUS_PATH.fullmatch(parsed.path)
        if match is None:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if session is None and not self._anonymous_ui_allowed():
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        if session is not None:
            principal = str(session["username"])
        elif visitor is not None:
            principal = visitor.principal
        else:
            principal = "__public_jobs__"
        try:
            value = self.state.transfer_access_status(
                match.group(1), principal=principal,
            )
        except KeyError:
            json_response(
                self, {"success": False, "error": "transfer was not found"}, 404,
            )
            return True
        json_response(self, {"success": True, "transfer": value})
        return True

    def _issue_artifact_transfer_access(self, parsed) -> bool:
        match = _ACCESS_PATH.fullmatch(parsed.path)
        if match is None:
            return False
        session = self._session()
        visitor = self._visitor_mode()
        if visitor is not None and not visitor.can_download_artifacts:
            json_response(
                self,
                {"success": False, "error": "访客模式不能下载生成物"},
                403,
            )
            return True
        if session is None and not self._anonymous_ui_allowed():
            json_response(
                self, {"success": False, "error": "login required"}, 401,
            )
            return True
        job_id = unquote(match.group(1))
        name = unquote(match.group(2))
        if not name or name in {".", ".."} or "\\" in name:
            json_response(
                self,
                {"success": False, "error": "artifact name is invalid"},
                400,
            )
            return True
        if session is not None:
            principal = str(session["username"])
        elif visitor is not None:
            principal = visitor.principal
        else:
            principal = "__public_jobs__"
        idempotency = str(
            self.headers.get("Idempotency-Key") or secrets.token_hex(16)
        ).strip()
        local_projection = getattr(self.state, "local_run_projection", None)
        local_run = (
            local_projection.get(principal, job_id)
            if local_projection is not None and session is not None
            else None
        )
        if local_run is not None:
            artifact = next(
                (item for item in local_run["task_detail"].get("artifacts") or ()
                 if str(item.get("name") or "") == name),
                None,
            )
            if artifact is None or str(artifact.get("upload_state") or "") != "uploaded":
                json_response(
                    self,
                    {"success": False, "error": "该本地生成物尚未主动上传到服务器"},
                    404,
                )
                return True
            try:
                access = self._rewrite_client_data_access(
                    self.state.prepare_object_download(
                        principal=principal,
                        storage_server_id=self.state.server_id,
                        object_kind="local_run_artifact",
                        object_id=f"{job_id}:{name}",
                        expected_size=int(artifact.get("size_bytes") or 0),
                        expected_sha256=str(artifact.get("content_hash") or "").strip().lower(),
                        content_type=str(
                            artifact.get("content_type")
                            or artifact.get("media_type")
                            or "application/octet-stream"
                        ),
                        idempotency_key=idempotency,
                        job_id=job_id,
                        artifact_name=name,
                    )
                )
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                json_response(self, {"success": False, "error": str(exc)}, 503)
                return True
            json_response(self, {
                "success": True,
                "artifact": {
                    "name": name,
                    "file_name": str(artifact.get("file_name") or name),
                    "content_type": str(artifact.get("content_type") or "application/octet-stream"),
                    "size_bytes": int(artifact.get("size_bytes") or 0),
                    "content_hash": str(artifact.get("content_hash") or ""),
                },
                "access": access,
            })
            return True
        try:
            routes = self._job_routes(
                parsed,
                principal,
                for_artifact_storage=True,
            )
            selected = self._artifact_metadata(
                routes,
                job_id=job_id,
                name=name,
                principal=principal,
            )
            if selected is None:
                raise KeyError("artifact was not found")
            route, artifact, lookup_principal = selected
            if (
                lookup_principal == PUBLIC_JOB_PRINCIPAL
                and str(artifact.get("artifact_role") or "output") == "input"
            ):
                raise PermissionError("登录后才能查看运行输入")
            access = self._rewrite_client_data_access(
                self.state.prepare_artifact_download(
                    # The service and data plane authorize against the
                    # concrete task owner.  Manager has already checked that
                    # this owner is the caller or an allowed direct child.
                    principal=lookup_principal,
                    storage_server_id=route.server_id,
                    job_id=job_id,
                    artifact=artifact,
                    idempotency_key=idempotency,
                )
            )
        except NodeUnavailable as exc:
            json_response(
                self,
                {
                    "success": False,
                    "code": exc.code,
                    "error": str(exc),
                },
                503,
            )
            return True
        except PeerControlError as exc:
            json_response(
                self,
                {
                    "success": False,
                    "code": exc.code,
                    "error": str(exc),
                },
                503,
            )
            return True
        except KeyError as exc:
            json_response(
                self,
                {"success": False, "error": str(exc).strip("'")},
                404,
            )
            return True
        except PermissionError as exc:
            json_response(
                self, {"success": False, "error": str(exc)}, 401,
            )
            return True
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
            json_response(
                self, {"success": False, "error": str(exc)}, 503,
            )
            return True
        json_response(self, {
            "success": True,
            "artifact": {
                "name": str(artifact.get("name") or name),
                "file_name": str(artifact.get("file_name") or name),
                "content_type": str(
                    artifact.get("content_type") or "application/octet-stream"
                ),
                "size_bytes": int(artifact.get("size_bytes") or 0),
                "content_hash": str(artifact.get("content_hash") or ""),
            },
            "access": access,
        })
        return True

    def _artifact_metadata(
        self,
        routes,
        *,
        job_id: str,
        name: str,
        principal: str,
    ):
        principals = read_principals(
            self.state, principal, job_id, routes=routes,
        )
        for route in routes:
            for lookup_principal in principals:
                try:
                    payload = self._job_artifact_payload(
                        route, job_id=job_id, principal=lookup_principal,
                    )
                except (ConnectionError, OSError, TypeError, ValueError):
                    continue
                for artifact in payload.get("artifacts") or []:
                    if not isinstance(artifact, dict):
                        continue
                    artifact_name = str(artifact.get("name") or "").strip()
                    file_name = str(artifact.get("file_name") or "").strip()
                    if name not in {artifact_name, file_name}:
                        continue
                    if str(artifact.get("state") or "") != "active":
                        continue
                    # ``name`` is the immutable API identity.  ``file_name``
                    # is only the download/display name; accepting it here
                    # keeps older declarations and clients readable without
                    # making it the transfer object ID.
                    return (
                        route,
                        {**artifact, "name": artifact_name or name},
                        lookup_principal,
                    )
        return None

    def _job_artifact_payload(
        self, route, *, job_id: str, principal: str,
    ) -> dict[str, object]:
        """Read metadata from the source Manager, never a worker port."""
        if route.server_id in {self.state.server_id, "local"}:
            return {
                "artifacts": JobArtifactCatalog(self.state).list(
                    job_id=job_id, principal=principal,
                ),
            }
        return self.state.federation_gateway.public_data(
            route,
            kind="job-artifacts",
            operation="list",
            principal=principal,
            payload={"job_id": job_id},
        )

    def _job_artifact_query_payload(
        self,
        route,
        *,
        job_id: str,
        name: str,
        principal: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        """Query the storage Manager directly, never an execution service."""
        if route.server_id in {self.state.server_id, "local"}:
            return {
                "data": JobArtifactQueryService(self.state).query(
                    job_id=job_id,
                    name=name,
                    principal=principal,
                    request=request,
                ),
            }
        return self.state.federation_gateway.public_data(
            route,
            kind="job-artifacts",
            operation="query",
            principal=principal,
            payload={
                "job_id": job_id,
                "name": name,
                "query": dict(request),
            },
        )

    def _job_artifact_manifest(self, routes, *, job_id: str, principal: str):
        principals = read_principals(
            self.state, principal, job_id, routes=routes,
        )
        for route in routes:
            for lookup_principal in principals:
                try:
                    payload = self._job_artifact_payload(
                        route, job_id=job_id, principal=lookup_principal,
                    )
                except (ConnectionError, OSError, TypeError, ValueError):
                    continue
                artifacts = [
                    dict(item) for item in payload.get("artifacts") or []
                    if isinstance(item, dict)
                    and str(item.get("state") or "") == "active"
                ]
                if artifacts:
                    return route, artifacts, lookup_principal
        return None


__all__ = ["JobTransferRoutesMixin"]


def _submission_name(value: object) -> str:
    name = str(value or "").strip()
    if (
        not name
        or len(name) > 255
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
    ):
        raise ValueError("submission name is invalid")
    return name
