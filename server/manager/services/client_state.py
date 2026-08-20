"""Principal-owned FTClient state exposed through Manager 7998."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
from typing import Any

from tools.cli.release.locations import default_client_root
from tools.cli.release.user_layout import (
    default_user_factor_library,
    default_user_profile_root,
    default_user_root,
)
from tools.cli.release.local_profile_contracts import validate_local_identifier
from server.manager.services.profile_projection import (
    ProfileProjectionCache,
    control_profile_projection,
    safe_profile_value,
)
from server.manager.storage.control_db import ControlDatabaseError
from server.manager.services.client_factor_catalog import ClientFactorCatalogMixin
from server.manager.services.client_product_catalog import ClientProductCatalogMixin


class ProfileAlreadyExistsError(ValueError):
    """Raised when an owner already has the requested Profile identifier."""




class ClientStateService(ClientProductCatalogMixin, ClientFactorCatalogMixin):
    """Project and update principal-owned state without invoking a service port."""

    def __init__(
        self,
        client_root: Path | None = None,
        *,
        control_store: object | None = None,
        profile_cache_root: Path | None = None,
        account_domain_sync: object | None = None,
        local_account_store: object | None = None,
    ) -> None:
        self.client_root = (client_root or default_client_root()).resolve()
        self.control_store = control_store
        self.account_domain_sync = account_domain_sync
        self.local_account_store = local_account_store
        self.profile_cache = (
            ProfileProjectionCache(profile_cache_root)
            if profile_cache_root is not None else None
        )
        self._profile_refresh_lock = threading.RLock()
        self._profile_refresh_inflight: set[str] = set()
        self._catalog_refresh_lock = threading.RLock()
        self._catalog_refresh_inflight: set[str] = set()

    def _refresh_account_domain_async(self, principal: str) -> None:
        """Refresh the local account mirror without delaying a catalog read."""
        owner = str(principal or "").strip()
        synchronizer = self.account_domain_sync
        if not owner or synchronizer is None:
            return
        with self._catalog_refresh_lock:
            if owner in self._catalog_refresh_inflight:
                return
            self._catalog_refresh_inflight.add(owner)

        def refresh() -> None:
            try:
                synchronizer.sync(owner)
            except (
                AttributeError,
                ConnectionError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                pass
            finally:
                with self._catalog_refresh_lock:
                    self._catalog_refresh_inflight.discard(owner)

        threading.Thread(
            target=refresh,
            name=f"account-catalog-refresh:{owner}",
            daemon=True,
        ).start()

    def _local_account(self, principal: str) -> dict[str, Any]:
        """Read the account projection from this Manager's SQLite first.

        Catalog pages must remain usable while PostgreSQL is unavailable.  In
        particular, resolving an owner alias is presentation metadata and
        must never open a remote connection just to render a family heading.
        """
        owner = str(principal or "").strip()
        store = self.local_account_store
        if store is None:
            try:
                from server.manager.storage.local_accounts import LocalAccountStore

                store = LocalAccountStore()
            except (ImportError, OSError, RuntimeError, TypeError, ValueError):
                store = None
        if store is not None:
            try:
                rows = store.load_accounts()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                rows = []
            for row in rows:
                if isinstance(row, dict) and str(row.get("username") or "") == owner:
                    return dict(row)
        # The canonical username grammar keeps a useful display alias even
        # when an old/partial SQLite projection has not been restored yet.
        parts = owner.split("@")
        alias = parts[1] if len(parts) == 3 and parts[2].isdigit() else owner
        organization = parts[0] if len(parts) == 3 else ""
        return {
            "username": owner,
            "alias": alias,
            "organization_id": organization,
            "organization_name": organization,
        }

    def profiles(
        self,
        principal: str,
        *,
        include_local_paths: bool = True,
    ) -> list[dict[str, Any]]:
        root = self.client_root / "profiles"
        result: list[dict[str, Any]] = []
        if root.is_dir():
            for path in sorted(root.glob("*.json"))[:512]:
                try:
                    if path.stat().st_size > 4 * 1024 * 1024:
                        continue
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(value, dict):
                    continue
                binding = value.get("session_binding")
                owner = (
                    str(binding.get("principal_ref") or "")
                    if isinstance(binding, dict) else ""
                )
                if owner == principal:
                    result.append(value)

        if self.profile_cache is not None:
            cached = self.profile_cache.read(principal)
            indexed = {
                str(item.get("profile_id") or ""): item
                for item in result
                if str(item.get("profile_id") or "")
            }
            for item in cached:
                profile_id = str(item.get("profile_id") or "").strip()
                if not profile_id:
                    continue
                if profile_id in indexed:
                    merged = dict(item)
                    merged.update(indexed[profile_id])
                    indexed[profile_id] = merged
                else:
                    indexed[profile_id] = item
            result = list(indexed.values())

        # The generic local mirror is the recovery path for a Profile created
        # on another Manager while PostgreSQL was unavailable. Keep the
        # dedicated control_profiles table below for compatibility with older
        # deployments and merge the two projections by stable profile_id.
        if self.account_domain_sync is not None:
            try:
                rows = self.account_domain_sync.entities(
                    principal,
                    entity_type="profile",
                    include_shared=False,
                    sync=False,
                )
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                rows = []
            indexed = {
                str(item.get("profile_id") or ""): item
                for item in result
                if str(item.get("profile_id") or "")
            }
            for row in rows:
                payload = row.get("payload") if isinstance(row, dict) else None
                if not isinstance(payload, dict):
                    continue
                profile_id = str(payload.get("profile_id") or row.get("entity_id") or "").strip()
                if not profile_id:
                    continue
                if profile_id in indexed:
                    merged = dict(payload)
                    merged.update(indexed[profile_id])
                    indexed[profile_id] = merged
                else:
                    indexed[profile_id] = dict(payload)
            result = list(indexed.values())

        # A deployed public Manager does not mount a user's device-local
        # Client root.  Refresh the durable Profile projection in the
        # background, but never make a catalog read wait for PostgreSQL.
        self._schedule_profile_refresh(principal)
        if self.profile_cache is not None:
            indexed = {
                str(item.get("profile_id") or ""): item
                for item in result
                if str(item.get("profile_id") or "")
            }
            for item in self.profile_cache.read(principal):
                profile_id = str(item.get("profile_id") or "").strip()
                if not profile_id:
                    continue
                if profile_id in indexed:
                    merged = dict(item)
                    merged.update(indexed[profile_id])
                    indexed[profile_id] = merged
                else:
                    indexed[profile_id] = item
            result = list(indexed.values())

        if not include_local_paths:
            result = [
                cleaned
                for item in result
                if isinstance(cleaned := safe_profile_value(item), dict)
            ]
        return sorted(
            result,
            key=lambda item: str(item.get("profile_id") or ""),
        )

    def sync_profile(
        self, principal: str, profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Durably project one local Profile and best-effort sync it to PG.

        The local projection is written before the database call.  A database
        outage therefore returns a successful *local* handoff with
        ``status=pending`` rather than making Profile registration disappear
        or pretending that the global copy was committed.
        """
        owner = str(principal or "").strip()
        if not owner:
            raise ValueError("profile principal is required")
        if not isinstance(profile, dict):
            raise ValueError("profile must be an object")
        projected = safe_profile_value(profile)
        if not isinstance(projected, dict):
            raise ValueError("profile projection must be an object")
        profile_id = str(projected.get("profile_id") or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required")
        display_name = str(
            projected.get("display_name") or profile_id
        ).strip() or profile_id
        projected["profile_id"] = profile_id
        projected["display_name"] = display_name
        projected["session_binding"] = {"principal_ref": owner}

        if self.profile_cache is not None:
            self.profile_cache.upsert(owner, projected)

        if self.account_domain_sync is not None:
            try:
                self.account_domain_sync.upsert(
                    owner, "profile", profile_id, projected,
                )
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                pass

        if self.control_store is None:
            return self._profile_sync_receipt(
                owner, projected, synced=False,
                reason="control database is not configured",
            )
        try:
            self.control_store.upsert_profile(
                owner, profile_id, display_name, projected,
            )
        except (
            ControlDatabaseError, ConnectionError, OSError, RuntimeError,
        ):
            return self._profile_sync_receipt(
                owner, projected, synced=False,
                reason="control database is unavailable",
            )
        if self.profile_cache is not None:
            self.profile_cache.mark_synced(owner, profile_id)
        return self._profile_sync_receipt(owner, projected, synced=True)

    def create_profile(
        self,
        principal: str,
        *,
        profile_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        """Create a minimal server Profile without importing client state.

        The Manager owns the initial server-side projection.  Runtime binding,
        workspace creation, provider selection, and Agent claiming remain
        explicit follow-up operations on the Profile detail page.
        """
        owner = str(principal or "").strip()
        if not owner:
            raise ValueError("profile principal is required")
        identifier = validate_local_identifier(profile_id, "profile_id")
        label = str(display_name or "").strip()
        if not label:
            raise ValueError("display_name is required")

        if any(
            str(item.get("profile_id") or "") == identifier
            for item in self.profiles(owner, include_local_paths=False)
        ):
            raise ProfileAlreadyExistsError(
                f"profile already exists: {identifier}"
            )

        # A central lookup closes the duplicate race when PostgreSQL is
        # reachable.  If it is unavailable, the local cache remains the
        # authoritative creation surface and sync_profile reports pending.
        if self.control_store is not None:
            try:
                central_rows = self.control_store.list_profiles(owner)
            except (
                AttributeError, ControlDatabaseError, ConnectionError, OSError,
                RuntimeError, TypeError, ValueError,
            ):
                central_rows = []
            if any(
                str(row.get("profile_id") or "") == identifier
                for row in central_rows
                if isinstance(row, dict)
            ):
                raise ProfileAlreadyExistsError(
                    f"profile already exists: {identifier}"
                )

        return self.sync_profile(owner, {
            "schema_version": 9,
            "profile_id": identifier,
            "status": "active",
            "display_name": label,
            "runtime_kind": "server",
            "workspaces": [],
            "agents": [],
            "research_records": [],
        })

    def _flush_profile_cache(self, principal: str) -> None:
        if self.control_store is None or self.profile_cache is None:
            return
        for profile in self.profile_cache.pending(principal):
            profile_id = str(profile.get("profile_id") or "").strip()
            if not profile_id:
                continue
            display_name = str(
                profile.get("display_name") or profile_id
            ).strip() or profile_id
            try:
                self.control_store.upsert_profile(
                    principal, profile_id, display_name, profile,
                )
            except (
                ControlDatabaseError, ConnectionError, OSError, RuntimeError,
            ):
                return
            self.profile_cache.mark_synced(principal, profile_id)

    def _schedule_profile_refresh(self, principal: str) -> None:
        """Refresh the central Profile projection without blocking a read."""
        owner = str(principal or "").strip()
        if not owner or self.control_store is None or self.profile_cache is None:
            return
        with self._profile_refresh_lock:
            if owner in self._profile_refresh_inflight:
                return
            self._profile_refresh_inflight.add(owner)

        def refresh() -> None:
            try:
                self._flush_profile_cache(owner)
                rows = self.control_store.list_profiles(owner)
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    profile_id = str(row.get("profile_id") or "").strip()
                    if not profile_id:
                        continue
                    self.profile_cache.upsert(
                        owner, control_profile_projection(row, owner),
                    )
                    self.profile_cache.mark_synced(owner, profile_id)
            except (
                AttributeError, ConnectionError, ControlDatabaseError,
                OSError, RuntimeError, TypeError, ValueError,
            ):
                # The local cache remains the source for this request and a
                # later request will retry after the in-flight marker clears.
                pass
            finally:
                with self._profile_refresh_lock:
                    self._profile_refresh_inflight.discard(owner)

        threading.Thread(
            target=refresh,
            name="factor-tester-profile-refresh",
            daemon=True,
        ).start()

    @staticmethod
    def _profile_sync_receipt(
        principal: str,
        profile: dict[str, Any],
        *,
        synced: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": 1,
            "status": "synced" if synced else "pending",
            "synced": bool(synced),
            "pending": not synced,
            "principal_ref": principal,
            "profile": safe_profile_value(profile),
        }
        if reason:
            receipt["reason"] = reason
        return receipt

    def workspace(self, principal: str) -> dict[str, Any]:
        user_root = default_user_root(principal).resolve()
        factor_library = default_user_factor_library(principal).resolve()
        profiles = self.profiles(principal)
        return {
            "schema_version": 1,
            "principal_ref": principal,
            "client_root": str(self.client_root),
            "user_root": str(user_root),
            "personal_workspace": str(user_root / "personal-workspace"),
            "factor_library": self._git_projection(factor_library),
            "profiles_root": str(user_root / "profiles"),
            "profiles": [
                {
                    "profile_id": str(item.get("profile_id") or ""),
                    "display_name": str(item.get("display_name") or ""),
                    "workspace_root": str(item.get("workspace_root") or ""),
                    "expected_root": str(default_user_profile_root(
                        principal, str(item.get("profile_id") or ""),
                    )) if item.get("profile_id") else "",
                }
                for item in profiles
            ],
        }

    def local_research(self, principal: str) -> list[dict[str, Any]]:
        """Return owner-scoped local report branches without exposing paths."""
        result: list[dict[str, Any]] = []
        for profile in self.profiles(principal):
            workspace_root = Path(str(profile.get("workspace_root") or ""))
            research_root = workspace_root / "research"
            for record in profile.get("research_records") or []:
                record_id = str(record.get("record_id") or "").strip()
                if not record_id or not research_root.is_dir():
                    continue
                package_root = research_root / record_id
                for head in sorted(package_root.glob("branches/*/authoring/HEAD.json")):
                    branch_id = head.parent.parent.name
                    try:
                        head_value = json.loads(head.read_text(encoding="utf-8"))
                    except (OSError, ValueError, json.JSONDecodeError):
                        head_value = {}
                    result.append({
                        "local_ref": f"{record_id}:{branch_id}",
                        "record_id": record_id,
                        "branch_id": branch_id,
                        "report_id": str(head_value.get("report_id") or ""),
                        "profile_id": str(profile.get("profile_id") or ""),
                        "profile_name": str(profile.get("display_name") or ""),
                        "title": str(record.get("title") or record_id),
                        "updated_at": float(record.get("updated_at") or 0),
                        "status": str(record.get("status") or "active"),
                    })
        return sorted(
            result,
            key=lambda item: (-float(item.get("updated_at") or 0), str(item["local_ref"])),
        )

    def local_research_report(self, principal: str, local_ref: str) -> dict[str, Any]:
        """Build the same source-free projection used by shared reports."""
        snapshot = self._local_report_snapshot(principal, local_ref)
        from tools.cli.release.research_reporting.public_research.projection import build_upload_projection

        projection = build_upload_projection(
            snapshot,
            include_local_resource_bytes=False,
            include_asset_bytes=False,
        )
        projection["source"] = "local"
        projection["local_ref"] = local_ref
        projection["profile_id"] = snapshot.get("_local_profile_id") or ""
        return projection

    def local_research_index(self, principal: str, local_ref: str) -> dict[str, Any]:
        """Return local report metadata without sending every component to Web."""
        package_root, branch_id, profile_id = self._local_report_location(principal, local_ref)
        from tools.cli.release.research_reporting.authoring.tree_projection import load_report_index
        from tools.cli.release.research_reporting.public_research.projection import build_upload_index
        snapshot = load_report_index(package_root=package_root, branch_id=branch_id)
        value = build_upload_index(snapshot)
        value.update(source="local", local_ref=local_ref,
                     profile_id=profile_id)
        return value

    def local_research_chapter(
        self, principal: str, local_ref: str, chapter_id: str,
        *, include_content: bool = True,
    ) -> dict[str, Any]:
        """Return one local report chapter for on-demand rendering."""
        package_root, branch_id, profile_id = self._local_report_location(principal, local_ref)
        from tools.cli.release.research_reporting.authoring.tree_projection import load_chapter_snapshot
        from tools.cli.release.research_reporting.public_research.projection import (
            build_upload_projection, component_asset_references,
        )
        snapshot = load_chapter_snapshot(
            package_root=package_root, branch_id=branch_id, chapter_id=chapter_id,
        )
        projection = build_upload_projection(
            snapshot,
            asset_refs=component_asset_references(snapshot.get("components") or []),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
            include_component_content=include_content,
        )
        projection.update(source="local", local_ref=local_ref,
                          profile_id=profile_id)
        return projection

    def local_research_component(
        self, principal: str, local_ref: str, chapter_id: str, component_id: str,
    ) -> dict[str, Any]:
        """Return one report component for content-level Web lazy loading."""
        package_root, branch_id, profile_id = self._local_report_location(
            principal, local_ref,
        )
        from tools.cli.release.research_reporting.authoring.tree_projection import (
            load_component_snapshot,
        )
        from tools.cli.release.research_reporting.public_research.projection import (
            build_upload_projection, component_asset_references,
        )
        snapshot = load_component_snapshot(
            package_root=package_root, branch_id=branch_id,
            chapter_id=chapter_id, component_id=component_id,
        )
        projection = build_upload_projection(
            snapshot,
            asset_refs=component_asset_references(snapshot.get("components") or []),
            include_local_resource_bytes=False,
            include_asset_bytes=False,
        )
        projection.update(source="local", local_ref=local_ref, profile_id=profile_id)
        return projection

    def local_research_resource(
        self, principal: str, local_ref: str, resource_id: str,
    ) -> tuple[bytes, str, str]:
        """Read one owner-scoped report resource for a Swift-owned detail tab."""
        if not resource_id or any(
            character not in "0123456789abcdef" for character in resource_id.lower()
        ) or len(resource_id) != 24:
            raise ValueError("research local resource id is invalid")
        package_root, branch_id, _profile_id = self._local_report_location(
            principal, local_ref,
        )
        from tools.cli.release.research_reporting.authoring.tree_projection import (
            load_snapshot,
        )
        from tools.cli.release.research_reporting.public_research.projection import (
            read_local_resource,
        )

        value = read_local_resource(
            load_snapshot(package_root=package_root, branch_id=branch_id),
            resource_id,
        )
        if value is None:
            raise ValueError("research local resource is unavailable")
        raw, media_type, filename = value
        if not raw:
            raise ValueError("research local resource is empty")
        return raw, media_type, filename

    def local_research_asset(
        self, principal: str, local_ref: str, asset_id: str,
    ) -> tuple[bytes, str, str]:
        """Read one owner-scoped report asset for on-demand Web rendering."""
        if not asset_id or any(
            character not in "0123456789abcdef" for character in asset_id.lower()
        ) or len(asset_id) != 24:
            raise ValueError("research asset id is invalid")
        package_root, branch_id, _profile_id = self._local_report_location(
            principal, local_ref,
        )
        from tools.cli.release.research_reporting.authoring.tree_projection import (
            load_snapshot,
        )
        from tools.cli.release.research_reporting.public_research.projection import (
            read_local_asset,
        )

        value = read_local_asset(
            load_snapshot(package_root=package_root, branch_id=branch_id),
            asset_id,
        )
        if value is None:
            raise ValueError("research asset is unavailable")
        raw, media_type, filename = value
        if not raw:
            raise ValueError("research asset is empty")
        return raw, media_type, filename

    def _local_report_snapshot(self, principal: str, local_ref: str) -> dict[str, Any]:
        package_root, branch_id, profile_id = self._local_report_location(principal, local_ref)
        from tools.cli.release.research_reporting.authoring.tree_projection import load_snapshot
        snapshot = load_snapshot(package_root=package_root, branch_id=branch_id)
        snapshot["_local_profile_id"] = profile_id
        return snapshot

    def _local_report_location(
        self, principal: str, local_ref: str,
    ) -> tuple[Path, str, str]:
        parts = str(local_ref or "").split(":", 1)
        if len(parts) != 2 or not all(parts):
            raise ValueError("local research reference is invalid")
        record_id, branch_id = parts
        matches = [
            item for item in self.local_research(principal)
            if item["record_id"] == record_id and item["branch_id"] == branch_id
        ]
        if not matches:
            raise PermissionError("local research report is not available")
        profile = next(
            item for item in self.profiles(principal)
            if str(item.get("profile_id") or "") == matches[0]["profile_id"]
        )
        package_root = Path(str(profile["workspace_root"])).expanduser() / "research" / record_id
        return package_root, branch_id, matches[0]["profile_id"]


    @staticmethod
    def _git_projection(path: Path) -> dict[str, Any]:
        result: dict[str, Any] = {"path": str(path), "exists": path.is_dir()}
        if not (path / ".git").exists() and not path.is_dir():
            return result
        try:
            output = subprocess.run(
                ["git", "-C", str(path), "status", "--porcelain=v1"],
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout
            result.update({
                "branch": ClientStateService._git(path, "branch", "--show-current"),
                "head": ClientStateService._git(path, "rev-parse", "HEAD"),
                "dirty_file_count": len([line for line in output.splitlines() if line]),
            })
        except (OSError, subprocess.SubprocessError):
            result["git_unavailable"] = True
        return result

    @staticmethod
    def _git(path: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(path), *arguments], capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
