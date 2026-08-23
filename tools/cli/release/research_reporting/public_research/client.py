"""Client-side publication workflow for live public research reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from tools.cli.commands.research_report_scope_identity import (
    resolve_branch_report_scope,
)
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.research_reporting.authoring.tree_paths import report_tree_paths
from tools.cli.release.research_reporting.authoring.tree_projection import (
    project_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_store import load_head
from tools.cli.release.research_reporting.public_research.object_uploads import (
    ResearchObjectUpload,
    detach_object_bytes,
    projection_hash,
)
from tools.cli.release.research_reporting.public_research.projection import (
    build_upload_projection,
)

from .outbox import PublicResearchOutbox


class ManagerRequestError(RuntimeError):
    """A publication request failed without changing local authoring."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)

    @property
    def retryable(self) -> bool:
        return self.status_code == 0 or self.status_code in {
            408, 425, 429,
        } or self.status_code >= 500


class PublicResearchClient:
    """Resolve local report trees and control their Manager publication."""

    def __init__(self, client_root: Path, *, manager_url: str | None = None) -> None:
        self.client_root = Path(client_root).expanduser().resolve()
        self.outbox = PublicResearchOutbox(self.client_root)
        configured = manager_url or os.environ.get("FACTORTESTER_MANAGER_URL", "")
        if not configured:
            try:
                from tools.cli.manager.config import load_manager_config

                configured = load_manager_config().base_url
            except (FileNotFoundError, ValueError):
                configured = "http://127.0.0.1:7998"
        self.manager_url = str(configured).rstrip("/")

    def list_publications(self) -> list[dict[str, Any]]:
        # A read is also a reconnect boundary.  Local browsing must continue
        # to work when the last remote snapshot is the only available one.
        self.sync_pending()
        try:
            value = self._request(
                "GET", "/api/public-research", allow_anonymous=True,
            )
            reports = value.get("reports")
            result = (
                [item for item in reports if isinstance(item, dict)]
                if isinstance(reports, list) else []
            )
            self.outbox.save_publication_cache(result)
            return result
        except ManagerRequestError:
            return self.outbox.load_publication_cache()

    def list_local_reports(self) -> list[dict[str, Any]]:
        public_by_report = {
            str(item.get("report_id")): item
            for item in self.list_publications()
            if item.get("report_id")
        }
        pending_by_report = {
            str(item.get("report_id")): item
            for item in self.outbox.pending()
            if item.get("kind") == "publish" and item.get("report_id")
        }
        values: list[dict[str, Any]] = []
        for profile in LocalProfileStore(self.client_root).list():
            profile_id = str(profile["profile_id"])
            workspace = Path(str(profile["workspace_root"])).expanduser()
            for record in profile.get("research_records") or []:
                work_package_id = _work_package_id(record.get("graph_instance_ref"))
                if not work_package_id:
                    continue
                package_root = workspace / "research" / work_package_id
                branches_root = package_root / "branches"
                if not branches_root.is_dir():
                    continue
                for branch_root in sorted(branches_root.iterdir()):
                    head_path = branch_root / "authoring" / "HEAD.json"
                    if not head_path.is_file():
                        continue
                    try:
                        head = load_head(report_tree_paths(package_root, branch_root.name))
                    except (OSError, ValueError):
                        continue
                    report_id = str(head["report_id"])
                    publication = public_by_report.get(report_id)
                    pending = pending_by_report.get(report_id)
                    visibility = (
                        publication.get("visibility", "private")
                        if publication else "private"
                    )
                    shared = visibility in {"authorized", "public"}
                    values.append({
                        "profile_id": profile_id,
                        "work_package_id": work_package_id,
                        "branch_id": branch_root.name,
                        "report_id": report_id,
                        "title": str(head["title"]),
                        "generation": int(head["generation"]),
                        "visibility": visibility,
                        "publication_id": (
                            publication.get("publication_id")
                            if publication else None
                        ),
                        "is_shared": shared,
                        "sharing_state": "shared" if shared else "not_shared",
                        "build_source": "client",
                        "build_source_ref": profile_id,
                        "sync_status": (
                            "pending" if pending else
                            "synced" if publication else "local"
                        ),
                        "pending_sync": pending is not None,
                    })
        return sorted(values, key=lambda item: (item["title"], item["work_package_id"], item["branch_id"]))

    def publish(
        self,
        *,
        profile_id: str,
        work_package_id: str,
        branch_id: str,
        public_title: str = "",
        show_profile: bool = False,
    ) -> dict[str, Any]:
        scope = resolve_branch_report_scope(
            client_root=self.client_root,
            profile_id=profile_id,
            work_package_id=work_package_id,
            branch_id=branch_id,
        )
        paths = report_tree_paths(scope.package_root, branch_id)
        head = load_head(paths)
        snapshot = project_snapshot(paths, head)
        projection, object_uploads = detach_object_bytes(
            build_upload_projection(snapshot),
        )
        title = str(public_title or "").strip()
        if title:
            projection = {**projection, "title": title}
            projection["projection_hash"] = projection_hash(projection)
        owner_ref = str(
            (scope.profile.get("session_binding") or {}).get("principal_ref")
            or ""
        ).strip()
        if not owner_ref:
            raise ValueError("Profile has no authenticated publication owner")
        operation_id = self.outbox.enqueue_publish(
            owner_ref=owner_ref,
            profile_ref=profile_id,
            report_id=str(projection["report_id"]),
            projection=projection,
            public_title=title,
            show_profile=show_profile,
            uploads=object_uploads,
        )
        sync = self.sync_pending(operation_id=operation_id)[0]
        publication_id = str(sync.get("publication_id") or "").strip()
        return {
            **sync,
            "profile_id": profile_id,
            "work_package_id": work_package_id,
            "branch_id": branch_id,
            "generation": projection["generation"],
            "projection_hash": sync.get(
                "projection_hash", projection["projection_hash"],
            ),
            "uploaded_objects": sync.get("uploaded_objects", 0),
            "operation_id": operation_id,
            **({"href": urljoin(
                self.manager_url + "/", f"research/{publication_id}"
            )} if publication_id else {}),
        }

    def sync_pending(self, *, operation_id: str = "") -> list[dict[str, Any]]:
        """Flush shared-report operations when the Manager is reachable.

        The report tree is never reconstructed from the server.  Only its
        source-free projection and detached 7997 objects cross the boundary.
        A network failure leaves the operation pending; a non-retryable server
        response becomes a visible conflict instead of overwriting local data.
        """
        manifests = self.outbox.pending()
        if operation_id:
            manifests = [
                item for item in manifests
                if item.get("operation_id") == operation_id
            ]
        return [self._sync_operation(item["operation_id"]) for item in manifests]

    def _sync_operation(self, operation_id: str) -> dict[str, Any]:
        try:
            operation = self.outbox.load(operation_id)
            manifest = operation["manifest"]
            if manifest["kind"] == "revoke":
                try:
                    value = self._request(
                        "POST", "/api/public-research/revoke",
                        payload={"publication_id": manifest["publication_id"]},
                    )
                except ManagerRequestError as exc:
                    if exc.status_code != 404:
                        raise
                    value = {
                        "status": "already_absent",
                        "publication_id": manifest["publication_id"],
                    }
                self.outbox.update(
                    operation_id, state="completed", last_error="",
                )
                return {
                    "operation_id": operation_id,
                    "status": "synced",
                    **value,
                }

            projection = operation["projection"]
            publication_id = str(manifest.get("publication_id") or "").strip()
            storage_server_id = str(
                manifest.get("storage_server_id") or ""
            ).strip()
            if not publication_id:
                value = self._request(
                    "POST", "/api/public-research/publish",
                    payload={
                        "owner_ref": manifest["owner_ref"],
                        "profile_ref": manifest.get("profile_ref") or "",
                        "report_id": manifest["report_id"],
                        "projection": projection,
                        "public_title": manifest.get("public_title") or "",
                        "show_profile": bool(manifest.get("show_profile")),
                        "build_source": "client",
                        "build_source_ref": manifest.get("profile_ref") or "",
                    },
                )
                publication_id = str(value.get("publication_id") or "").strip()
                if not publication_id:
                    raise ValueError("Manager did not return a publication id")
                storage_server_id = str(
                    value.get("storage_server_id") or ""
                ).strip()
                self.outbox.update(
                    operation_id,
                    state="syncing",
                    publication_id=publication_id,
                    storage_server_id=storage_server_id,
                )
            uploaded = 0
            for upload in operation.get("uploads") or ():
                self._upload_object(
                    publication_id=publication_id,
                    owner_ref=manifest["owner_ref"],
                    storage_server_id=storage_server_id,
                    upload=upload,
                )
                uploaded += 1
            self.outbox.update(
                operation_id, state="completed", last_error="",
            )
            return {
                "operation_id": operation_id,
                "status": "synced",
                "publication_id": publication_id,
                "report_id": manifest["report_id"],
                "generation": manifest["generation"],
                "projection_hash": manifest["projection_hash"],
                "storage_server_id": storage_server_id,
                "uploaded_objects": uploaded,
            }
        except ManagerRequestError as exc:
            return self._record_sync_failure(operation_id, exc)
        except (OSError, ValueError) as exc:
            return self._record_sync_failure(
                operation_id, ManagerRequestError(409, str(exc)),
            )

    def _record_sync_failure(
        self, operation_id: str, error: ManagerRequestError,
    ) -> dict[str, Any]:
        operation = self.outbox.load(operation_id)
        manifest = operation["manifest"]
        state = "pending" if error.retryable else "conflict"
        self.outbox.update(
            operation_id,
            state=state,
            attempts=int(manifest.get("attempts") or 0) + 1,
            last_error=str(error),
        )
        return {
            "operation_id": operation_id,
            "status": "pending_sync" if error.retryable else "conflict",
            "report_id": manifest.get("report_id") or "",
            "publication_id": manifest.get("publication_id") or "",
            "generation": manifest.get("generation"),
            "projection_hash": manifest.get("projection_hash") or "",
            "error": str(error),
        }

    def _upload_object(
        self,
        *,
        publication_id: str,
        owner_ref: str,
        storage_server_id: str,
        upload: ResearchObjectUpload,
    ) -> None:
        access_value = self._request(
            "POST",
            "/api/transfers/objects/access",
            payload={
                "owner_ref": owner_ref,
                "publication_id": publication_id,
                "object_kind": upload.object_kind,
                "object_id": upload.object_id,
                "storage_server_id": storage_server_id,
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": upload.size_bytes,
                "sha256": upload.content_hash,
            },
            extra_headers={
                "Idempotency-Key": (
                    f"research-upload:{publication_id}:"
                    f"{upload.object_kind}:{upload.object_id}:"
                    f"{upload.content_hash}"
                ),
            },
        )
        access = access_value.get("access")
        if not isinstance(access, dict):
            raise ManagerRequestError(
                502, "Manager returned no research object upload access",
            )
        request = Request(
            str(access.get("url") or ""),
            data=upload.content,
            headers={
                "Authorization": f"Bearer {access.get('bearer') or ''}",
                "Content-Length": str(upload.size_bytes),
                "Content-Type": upload.content_type,
                "X-FactorTester-Client": "cli",
            },
            method="PUT",
        )
        try:
            with urlopen(request, timeout=120.0) as response:
                response.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ManagerRequestError(
                exc.code,
                f"research object upload failed ({exc.code}): {raw[:500]}",
            ) from exc
        except OSError as exc:
            raise ManagerRequestError(
                0, "research object data plane is unavailable",
            ) from exc

    def unpublish(self, publication_id: str) -> dict[str, Any]:
        operation_id = self.outbox.enqueue_revoke(
            publication_id=str(publication_id or "").strip(),
        )
        return self.sync_pending(operation_id=operation_id)[0]

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_anonymous: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "X-FactorTester-Client": "cli",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            urljoin(self.manager_url + "/", path.lstrip("/")),
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ManagerRequestError(
                exc.code,
                f"Manager publication request failed ({exc.code}): {raw[:500]}",
            ) from exc
        except OSError as exc:
            raise ManagerRequestError(
                0, "Manager publication service is unavailable",
            ) from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ManagerRequestError(
                502, "Manager returned invalid publication JSON",
            ) from exc
        if not isinstance(value, dict):
            raise ManagerRequestError(
                502, "Manager returned invalid publication JSON",
            )
        if value.get("success") is False:
            raise ManagerRequestError(
                409,
                str(value.get("error") or "Manager publication request failed"),
            )
        return value


def _work_package_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.removeprefix("work-package:") if text.startswith("work-package:") else ""
