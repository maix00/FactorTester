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
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.runtime_store = runtime_store
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

    def projection(self, principal: str, server_ref: str) -> dict[str, Any]:
        location = self._location(principal, server_ref)
        value = build_upload_projection(
            load_snapshot(
                package_root=location["package_root"],
                branch_id=location["branch_id"],
            ),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
        )
        return self._decorate(value, location)

    def index(self, principal: str, server_ref: str) -> dict[str, Any]:
        location = self._location(principal, server_ref)
        value = build_upload_index(load_report_index(
            package_root=location["package_root"],
            branch_id=location["branch_id"],
        ))
        return self._decorate(value, location)

    def chapter(
        self,
        principal: str,
        server_ref: str,
        chapter_id: str,
        *,
        include_content: bool = True,
    ) -> dict[str, Any]:
        location = self._location(principal, server_ref)
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
        return self._decorate(value, location)

    def component(
        self,
        principal: str,
        server_ref: str,
        chapter_id: str,
        component_id: str,
    ) -> dict[str, Any]:
        location = self._location(principal, server_ref)
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
        return self._decorate(value, location)

    def asset(
        self, principal: str, server_ref: str, asset_id: str,
    ) -> tuple[bytes, str, str]:
        location = self._location(principal, server_ref)
        value = read_local_asset(self._snapshot(location), asset_id)
        if value is None:
            raise ValueError("research asset is unavailable")
        return value

    def local_resource(
        self, principal: str, server_ref: str, resource_id: str,
    ) -> tuple[bytes, str, str]:
        location = self._location(principal, server_ref)
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
        shared = visibility in {"authorized", "public"}
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

    def _decorate(
        self, value: dict[str, Any], location: dict[str, Any],
    ) -> dict[str, Any]:
        value["source"] = "server"
        value["server_ref"] = location["server_ref"]
        value["profile_id"] = location["profile_id"]
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
