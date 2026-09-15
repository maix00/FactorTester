"""Read and explicitly publish reports built by a server-bound Agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from server.manager.services.agent_workspace import server_profile_workspace
from server.manager.storage.profile_runtime_store import ProfileRuntimeStore
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_projection import (
    load_chapter_snapshot,
    load_component_snapshot,
    load_report_index,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_store import load_head
from tools.cli.release.research_reporting.public_research.object_uploads import (
    projection_hash,
)
from tools.cli.release.research_reporting.public_research.projection import (
    build_upload_index,
    build_upload_projection,
    component_asset_references,
    read_local_asset,
    read_local_resource,
)

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class ServerResearchService:
    """Expose the canonical server Profile workspace as a private report source.

    A server Agent writes the same immutable report tree as the client.  The
    Manager only reads that tree on behalf of its owner; it does not create a
    second report database.  Sharing is a separate, explicit operation that
    copies a bounded projection into ``PublicResearchLibrary``.
    """

    def __init__(
        self,
        data_root: str | Path,
        runtime_store: ProfileRuntimeStore,
        *,
        server_id: str,
        research_catalog=None,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.runtime_store = runtime_store
        self.research_catalog = research_catalog
        self.server_id = str(server_id or "").strip()
        if not self.server_id:
            raise ValueError("server_id is required")

    def list_owner(self, principal: str) -> list[dict[str, Any]]:
        owner = _required_principal(principal)
        values: list[dict[str, Any]] = []
        for profile_id, runtime in self.runtime_store.runtimes(owner).items():
            if (
                str(runtime.get("runtime_kind") or "") != "server"
                or str(runtime.get("executor_id") or "") != self.server_id
            ):
                continue
            workspace = server_profile_workspace(
                self.data_root, owner, profile_id,
            )
            research_root = workspace / "research"
            if not research_root.is_dir():
                continue
            claim = self.runtime_store.active_claim(owner, profile_id)
            source_ref = str(
                (claim or {}).get("agent_id") or profile_id
            ).strip()
            for package_root in sorted(research_root.iterdir()):
                if not package_root.is_dir() or not _safe(package_root.name):
                    continue
                for head_path in sorted(
                    package_root.glob("branches/*/authoring/HEAD.json")
                ):
                    branch_id = head_path.parent.parent.name
                    if not _safe(branch_id):
                        continue
                    try:
                        head = load_head(
                            report_tree_paths(package_root, branch_id),
                        )
                        updated_at = head_path.stat().st_mtime
                    except (OSError, ValueError):
                        continue
                    server_ref = _server_ref(profile_id, package_root.name, branch_id)
                    item = self._list_item(
                        owner,
                        profile_id,
                        package_root.name,
                        branch_id,
                        server_ref,
                        head,
                        source_ref,
                        updated_at,
                    )
                    item["source_server_id"] = self.server_id
                    values.append(item)
        return sorted(
            values,
            key=lambda item: (-float(item["updated_at"]), item["server_ref"]),
        )

    def owner_report(self, principal: str, report_id: str) -> dict[str, Any] | None:
        """Resolve one private server-Profile report by its stable report id."""
        selected = str(report_id or "").strip()
        if not selected:
            return None
        return next(
            (
                item for item in self.list_owner(principal)
                if str(item.get("report_id") or "") == selected
            ),
            None,
        )

    def _read_location(self, viewer: str, target: str, server_ref: str):
        viewer = _required_principal(viewer)
        target = _required_principal(target)
        if viewer != target:
            if self.research_catalog is None:
                raise PermissionError("research report download is not authorized")
            self.research_catalog.authorize_server_report_read(
                owner=target, server_ref=server_ref, viewer=viewer,
            )
        return self._location(target, server_ref)

    def read_branch(
        self,
        viewer: str,
        *,
        target_ref: str,
        profile_id: str,
        package_id: str,
        branch_id: str,
        build_source: str = "server_agent",
    ) -> dict[str, Any]:
        """Read one creator's branch.

        The report tree lives in the *creator's* profile workspace.  ``target_ref``
        is the branch owner (group A member).  Only local ``server_agent`` branches
        are resolved here; a branch whose ``build_source`` is ``client``/
        ``publication`` (or a remote ``server``) is served by the caller's own read
        channel (``public_research``, transfers/data-plane, or the client source).
        For those we report the source location honestly instead of misreading a
        local workspace, so a page or CLI never silently reads the wrong bytes.
        """
        source = str(build_source or "server_agent").strip().lower()
        if source != "server_agent":
            return {
                "viewer_ref": viewer,
                "branch_id": branch_id,
                "profile_id": profile_id,
                "package_id": package_id,
                "build_source": source,
                "available": False,
                "reason": "source-not-local",
                "note": (
                    f"branch 来源为 {source}，不在本机 server 工作区；"
                    "请通过对应读通道(client/publication/transfers)获取。"
                ),
            }
        target = _required_principal(target_ref)
        if not _safe(profile_id) or not _safe(package_id) or not _safe(branch_id):
            raise ValueError("server research reference is invalid")
        server_ref = _server_ref(profile_id, package_id, branch_id)
        location = self._read_location(viewer, target, server_ref)
        value = build_upload_index(load_report_index(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
        ))
        value = self._decorate_read(value, location, viewer)
        value["viewer_ref"] = viewer
        value["available"] = True
        value["build_source"] = "server_agent"
        return value

    def export_report(
        self,
        principal: str,
        server_ref: str,
        output_format: str = "md",
        *,
        target_ref: str | None = None,
    ) -> tuple[bytes, str, str]:
        """Render the server-held report tree as a downloadable document.

        Only Markdown is produced server-side; the PDF renderer is a macOS
        client binary, so a ``pdf`` request is refused here and the caller
        routes it to the native (client) export instead.
        """
        source_format = str(output_format or "md").strip().lower()
        if source_format not in {"md", "markdown"}:
            raise NotImplementedError(
                "服务端仅支持导出 Markdown；PDF 请在客户端导出",
            )
        location = self._read_location(principal, target_ref or principal, server_ref)
        from server.manager.services.research_export import (
            document_identity,
            markdown_export,
        )

        snapshot = self._snapshot(location)
        head = snapshot.setdefault("head", {})
        if not head.get("title"):
            head["title"] = location.get("package_id") or "report"
        identity = document_identity(
            branch=str(location.get("branch_id") or ""),
            owner=str(location.get("owner") or ""),
            profile=str(location.get("profile_id") or ""),
            generation=head.get("generation") or 0,
            projection_hash=str(snapshot.get("projection_hash") or ""),
            report_id=str(head.get("report_id") or ""),
        )
        return markdown_export(snapshot, output_format, identity=identity)

    def projection(self, principal: str, server_ref: str, *, target_ref: str | None = None) -> dict[str, Any]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        value = build_upload_projection(
            load_snapshot(
                package_root=location["package_root"],
                branch_id=location["branch_id"],
            ),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
        )
        return self._decorate_read(value, location, principal)

    def index(self, principal: str, server_ref: str, *, target_ref: str | None = None) -> dict[str, Any]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        value = build_upload_index(load_report_index(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
        ))
        return self._decorate_read(value, location, principal)

    def chapter(
        self,
        principal: str,
        server_ref: str,
        chapter_id: str,
        *,
        include_content: bool = True,
        target_ref: str | None = None,
    ) -> dict[str, Any]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        snapshot = load_chapter_snapshot(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
            chapter_id=chapter_id,
        )
        value = build_upload_projection(
            snapshot,
            asset_refs=component_asset_references(snapshot.get("components") or []),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
            include_component_content=include_content,
        )
        return self._decorate_read(value, location, principal)

    def component(
        self,
        principal: str,
        server_ref: str,
        chapter_id: str,
        component_id: str,
        *, target_ref: str | None = None,
    ) -> dict[str, Any]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        snapshot = load_component_snapshot(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
            chapter_id=chapter_id,
            component_id=component_id,
        )
        value = build_upload_projection(
            snapshot,
            asset_refs=component_asset_references(snapshot.get("components") or []),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
        )
        return self._decorate_read(value, location, principal)

    def asset(
        self,
        principal: str,
        server_ref: str,
        asset_id: str,
        *,
        target_ref: str | None = None,
    ) -> tuple[bytes, str, str]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        value = read_local_asset(self._snapshot(location), asset_id)
        if value is None:
            raise ValueError("research asset is unavailable")
        return value

    def local_resource(
        self,
        principal: str,
        server_ref: str,
        resource_id: str,
        *,
        target_ref: str | None = None,
    ) -> tuple[bytes, str, str]:
        location = self._read_location(principal, target_ref or principal, server_ref)
        value = read_local_resource(self._snapshot(location), resource_id)
        if value is None:
            raise ValueError("research local resource is unavailable")
        return value

    def publish(
        self,
        principal: str,
        server_ref: str,
        *,
        public_research: Any,
        visibility: str = "public",
        authorized_users: list[str] | None = None,
        public_title: str = "",
    ) -> dict[str, Any]:
        """Explicitly mirror one server report into the shared catalog."""
        location = self._location(principal, server_ref)
        projection = build_upload_projection(self._snapshot(location))
        title = str(public_title or "").strip()
        if title:
            projection = {**projection, "title": title}
            projection["projection_hash"] = projection_hash(projection)
        source_ref = str(location["build_source_ref"] or location["profile_id"])
        synced = public_research.sync({
            "report_id": projection["report_id"],
            "owner_ref": principal,
            "profile_ref": location["profile_id"],
            "build_source": "server_agent",
            "build_source_ref": source_ref,
            "projection": projection,
        })
        if synced.get("status") not in {"synced", "stale"}:
            raise ValueError("server research report is not ready to publish")
        settings = public_research.configure(
            owner_ref=principal,
            report_id=projection["report_id"],
            projection=None,
            visibility=visibility,
            auto_sync=True,
            relay_local_files=False,
            authorized_users=authorized_users or [],
            build_source="server_agent",
            build_source_ref=source_ref,
        )
        shared = visibility in {"superiors", "authorized", "public"}
        return {
            **settings,
            "server_ref": server_ref,
            "build_source": "server_agent",
            "build_source_ref": source_ref,
            "sharing_state": "shared" if shared else "not_shared",
            "is_shared": shared,
        }

    def _snapshot(self, location: dict[str, Any]) -> dict[str, Any]:
        return load_snapshot(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
        )

    def _decorate_read(self, value, location, viewer):
        value = self._decorate(value, location)
        if viewer != location["owner"]:
            value["access"]["can_manage"] = False
            value["branches"] = [b for b in value["branches"] if b["selected"]]
        return value

    def _decorate(
        self, value: dict[str, Any], location: dict[str, Any],
    ) -> dict[str, Any]:
        value["source"] = "server"
        value["server_ref"] = location["server_ref"]
        value["profile_id"] = location["profile_id"]
        # Authoring scope is public identity metadata, not a filesystem path.
        # Page assistants must not infer it by splitting a presentation URL.
        value["work_package_id"] = location["package_id"]
        value["branch_id"] = location["branch_id"]
        value["source_server_id"] = self.server_id
        value["branches"] = [
            {
                "branch_ref": str(item.get("branch_id") or ""),
                "title": str(item.get("branch_id") or item.get("title") or ""),
                "publication_id": f"server:{item['server_ref']}",
                "href": f"/research/server:{item['server_ref']}",
                "selected": item["server_ref"] == location["server_ref"],
            }
            for item in self.list_owner(location["owner"])
            if (
                str(item.get("profile_id") or "") == location["profile_id"]
                and str(item.get("work_package_id") or "") == location["package_id"]
            )
        ]
        value["access"] = {
            "visibility": "private",
            "build_source": "server_agent",
            "build_source_ref": location["build_source_ref"],
            "sharing_state": "not_shared",
            "is_shared": False,
            "can_manage": True,
            "source_server_id": self.server_id,
        }
        return value

    def _location(self, principal: str, server_ref: str) -> dict[str, Any]:
        owner = _required_principal(principal)
        profile_id, package_id, branch_id = _parse_server_ref(server_ref)
        runtime = self.runtime_store.runtime(owner, profile_id)
        if (
            runtime is None
            or str(runtime.get("runtime_kind") or "") != "server"
            or str(runtime.get("executor_id") or "") != self.server_id
        ):
            raise PermissionError("server research report is not available")
        package_root = server_profile_workspace(
            self.data_root, owner, profile_id,
        ) / "research" / package_id
        head_path = package_root / "branches" / branch_id / "authoring" / "HEAD.json"
        if not head_path.is_file():
            raise ValueError("server research report was not found")
        claim = self.runtime_store.active_claim(owner, profile_id)
        return {
            "owner": owner,
            "server_ref": _server_ref(profile_id, package_id, branch_id),
            "profile_id": profile_id,
            "package_id": package_id,
            "branch_id": branch_id,
            "package_root": package_root,
            "build_source_ref": str(
                (claim or {}).get("agent_id") or profile_id
            ).strip(),
        }

    @staticmethod
    def _list_item(
        owner: str,
        profile_id: str,
        package_id: str,
        branch_id: str,
        server_ref: str,
        head: dict[str, Any],
        source_ref: str,
        updated_at: float,
    ) -> dict[str, Any]:
        return {
            "server_ref": server_ref,
            "source": "server",
            "source_server_id": "",
            "build_source": "server_agent",
            "build_source_ref": source_ref,
            "sharing_state": "not_shared",
            "is_shared": False,
            "owner_ref": owner,
            "profile_id": profile_id,
            "profile_ref": profile_id,
            "profile_name": profile_id,
            "work_package_id": package_id,
            "branch_id": branch_id,
            "report_id": str(head.get("report_id") or ""),
            "title": str(head.get("title") or package_id),
            "generation": int(head.get("generation") or 0),
            "visibility": "private",
            "status": "active",
            "updated_at": updated_at,
            "href": f"/research/server:{server_ref}",
        }


def _parse_server_ref(value: Any) -> tuple[str, str, str]:
    parts = str(value or "").split(":")
    if len(parts) != 3 or not all(_safe(item) for item in parts):
        raise ValueError("server research reference is invalid")
    return parts[0], parts[1], parts[2]


def _server_ref(profile_id: str, package_id: str, branch_id: str) -> str:
    return f"{profile_id}:{package_id}:{branch_id}"


def _safe(value: str) -> bool:
    return bool(_SAFE_COMPONENT.fullmatch(str(value or "")))


def _required_principal(value: Any) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 256 or "/" in result or "\\" in result:
        raise ValueError("principal is invalid")
    return result


__all__ = ["ServerResearchService"]
