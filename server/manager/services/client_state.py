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
from server.manager.services.profile_projection import (
    ProfileProjectionCache,
    control_profile_projection,
    safe_profile_value,
)
from server.manager.storage.control_db import ControlDatabaseError


def _catalog_exchange(product: object, name: str) -> str:
    """Read a stable exchange label without depending on a service port."""
    exchange = str(
        getattr(product, "exchange_id", "")
        or getattr(product, "exchange", "")
        or ""
    ).strip()
    if exchange:
        return exchange
    value = str(name or "")
    if "." in value:
        return value.split(".", 1)[1].split("@", 1)[0]
    parts = value.split("|")
    return parts[1] if len(parts) >= 3 else ""


class ClientStateService:
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

    def product_groups(self, principal: str) -> list[dict[str, Any]]:
        """Return account groups projected against the server catalog."""
        from tools.data.account_manage import load_product_groups
        from server.services.product_catalog_projection import catalog_product_records
        from server.manager.domain.product_groups import (
            project_account_product_groups,
        )

        profiles = self.profiles(principal)
        research = self.local_research(principal)
        groups = load_product_groups(principal)
        if self.account_domain_sync is not None:
            try:
                remote_groups = self.account_domain_sync.entities(
                    principal,
                    entity_type="product_group",
                    include_shared=False,
                    sync=False,
                )
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                remote_groups = []
            known = {
                str(item.get("id") or item.get("name") or "")
                for item in groups
                if isinstance(item, dict)
            }
            for row in remote_groups:
                payload = row.get("payload") if isinstance(row, dict) else None
                if not isinstance(payload, dict) or row.get("deleted"):
                    continue
                key = str(payload.get("id") or payload.get("name") or "")
                if key and key not in known:
                    groups.append(dict(payload))
                    known.add(key)
        projected = project_account_product_groups(
            groups=groups,
            principal=principal,
            profiles=profiles,
            research_records=research,
            product_records=[dict(item) for item in catalog_product_records()],
            origin="server",
        )
        categories = {
            str(item.get("id") or ""): item
            for item in self.product_categories(principal)
        }
        for group in projected:
            group["category_bindings"] = [
                categories[category_id]
                for category_id in group.get("category_ids") or []
                if category_id in categories
            ]
        return projected

    def product_group(
        self, principal: str, group_ref: str,
    ) -> dict[str, Any] | None:
        wanted = str(group_ref or "").strip()
        if not wanted:
            return None
        return next(
            (
                item for item in self.product_groups(principal)
                if str(item.get("group_ref") or "") == wanted
                or str(item.get("name") or "") == wanted
            ),
            None,
        )

    def create_product_group(
        self,
        principal: str,
        name: str,
        paths: list[str],
        category_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Create an account product group and return its catalog projection."""
        from server.modules.products.product_group_store import create_product_group

        created = create_product_group(
            principal, name, paths, category_ids=category_ids,
        )
        if created is None:
            return None
        return self.product_group(
            principal, f"product-group:{created['id']}",
        )

    def factor_library(self, principal: str) -> dict[str, Any]:
        """Return the Manager-owned, source-free factor catalog."""
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        from server.modules.custom_factors.factor_library_service import (
            build_factor_library_overview,
        )
        from server.manager.services.account_domain_projection import (
            factor_rows_from_sync,
        )

        owner_account = self._local_account(principal)
        payload = build_factor_library_overview(
            principal, include_subordinates=False,
            account=owner_account,
        )
        if self.account_domain_sync is not None:
            payload["factors"] = list(payload.get("factors") or []) + factor_rows_from_sync(
                self.account_domain_sync, principal,
                owner_account=owner_account,
            )
        return build_client_library_projection(payload, principal=principal)

    def factor_library_scopes(self, principal: str) -> dict[str, dict[str, Any]]:
        """Return the user's own and managed-user factor-family scopes.

        ``factor_library`` intentionally remains the small own-account API
        used by older callers.  This companion projection adds only accounts
        that the current account can manage; same-level peers are not treated
        as subordinates merely because they are visible in an older listing.
        """
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        from server.modules.custom_factors.factor_library_service import (
            build_factor_library_overview,
        )
        from tools.data.account_manage import visible_accounts_for

        owner_account = self._local_account(principal)
        payload = build_factor_library_overview(
            principal, include_subordinates=True,
            account=owner_account,
        )
        managed_usernames = {
            str(account.get("username") or "")
            for account in visible_accounts_for(
                principal, include_self=False,
            )
            if isinstance(account, dict) and str(account.get("username") or "")
        }
        subordinate_rows = []
        for item in payload.get("factors") or []:
            owner = str(item.get("owner_username") or "")
            if owner in managed_usernames:
                subordinate_rows.append(item)
        subordinate = build_client_library_projection({
            "factors": subordinate_rows,
            "errors": payload.get("errors") or [],
        }, principal=principal)
        return {
            "mine": self.factor_library(principal),
            "subordinates": subordinate,
        }

    def factor_sets(self, principal: str, query: str = "") -> list[dict[str, Any]]:
        """Return explicitly synchronized immutable factor sets."""
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_catalog,
        )

        values = factor_set_catalog(principal, query)
        if self.account_domain_sync is None:
            return values
        try:
            rows = self.account_domain_sync.entities(
                principal, entity_type="factor_set", include_shared=False,
                sync=False,
            )
        except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            rows = []
        known = {str(item.get("target_ref") or "") for item in values}
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict) or row.get("deleted"):
                continue
            target_ref = str(payload.get("target_ref") or "")
            if target_ref and target_ref not in known:
                values.append({
                    key: payload.get(key)
                    for key in (
                        "schema_version", "target_ref", "set_ref", "set_id",
                        "title_zh", "description_zh", "member_hash",
                        "member_count", "authority", "owner_username", "updated_at",
                    )
                })
                known.add(target_ref)
        return values

    def factor_set_detail(
        self,
        principal: str,
        target_ref: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        from server.modules.custom_factors.factor_set_registry import factor_set_detail

        value = factor_set_detail(
            principal, target_ref, offset=offset, limit=limit,
        )
        if value is not None or self.account_domain_sync is None:
            return value
        rows = self.account_domain_sync.entities(
            principal, entity_type="factor_set", include_shared=False,
            sync=False,
        )
        payload = next(
            (
                row.get("payload") for row in rows
                if isinstance(row, dict)
                and not row.get("deleted")
                and str(row.get("entity_id") or "") == str(target_ref)
                and isinstance(row.get("payload"), dict)
            ),
            None,
        )
        if not isinstance(payload, dict):
            return None
        members = list(payload.get("member_refs") or [])
        page = members[offset:offset + limit]
        return {
            **{key: payload.get(key) for key in (
                "schema_version", "target_ref", "set_ref", "set_id",
                "title_zh", "description_zh", "member_hash", "member_count",
                "authority", "owner_username", "updated_at",
            )},
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(page) < len(members),
            "next_offset": offset + len(page),
            "related_references": [
                {"relation": "集合成员", "kind": "factor", "target_ref": item,
                 "label": item}
                for item in page
            ],
        }

    def factor_set_descriptor(
        self,
        principal: str, target_ref: str,
    ) -> dict[str, Any] | None:
        """Return one server-registered immutable Factor Set descriptor."""
        from server.modules.custom_factors.factor_set_registry import factor_set_descriptor

        value = factor_set_descriptor(principal, target_ref)
        if value is not None or self.account_domain_sync is None:
            return value
        rows = self.account_domain_sync.entities(
            principal, entity_type="factor_set", include_shared=False,
            sync=False,
        )
        payload = next(
            (
                row.get("payload") for row in rows
                if isinstance(row, dict)
                and not row.get("deleted")
                and str(row.get("entity_id") or "") == str(target_ref)
                and isinstance(row.get("payload"), dict)
            ),
            None,
        )
        if not isinstance(payload, dict):
            return None
        return {
            "target_ref": payload.get("target_ref"),
            "manifest": {
                "schema_version": 1,
                "set_id": payload.get("set_id"),
                "set_ref": payload.get("set_ref"),
                "title_zh": payload.get("title_zh"),
                "description_zh": payload.get("description_zh") or "",
                "member_refs": list(payload.get("member_refs") or []),
                "member_hash": payload.get("member_hash"),
            },
        }

    def product_categories(self, principal: str = "") -> list[dict[str, Any]]:
        """Return source and account-owned product category definitions."""
        from server.modules.products.product_category_store import (
            list_product_categories,
        )
        from server.modules.shared.price_services import available_product_categories

        # Keep the old no-principal service contract for callers that only
        # need the built-in source dimensions.  An authenticated Manager
        # request gets the source definitions plus that account's categories.
        values = list_product_categories(principal) if principal else available_product_categories()
        if not principal or self.account_domain_sync is None:
            return values
        try:
            rows = self.account_domain_sync.entities(
                principal, entity_type="product_category", include_shared=False,
                sync=False,
            )
        except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            rows = []
        known = {str(item.get("id") or "") for item in values}
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else None
            category_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
            if category_id and category_id not in known and not row.get("deleted"):
                value = dict(payload)
                if not value.get("is_composite") and not value.get("source_ids"):
                    from server.modules.products.product_category_store import (
                        infer_category_source_ids,
                    )
                    value["source_ids"] = infer_category_source_ids(
                        value.get("items") or [],
                    )
                value.update({
                    "owner_ref": f"user:{principal}",
                    "source_managed": False,
                })
                values.append(value)
                known.add(category_id)
        return values

    @staticmethod
    def product_sources() -> list[dict[str, Any]]:
        """Return data-source bundles registered on this server."""
        from server.services.product_catalog_projection import product_source_descriptors

        return [dict(item) for item in product_source_descriptors()]

    @staticmethod
    def product_names(
        source_ids: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Return products visible in this server's catalog."""
        from server.services.product_catalog_projection import filter_product_records

        return [dict(item) for item in filter_product_records(source_ids)]

    @staticmethod
    def product_fields(name: str) -> dict[str, Any] | None:
        from server.modules.shared.price_services import (
            cached_products,
            find_product,
            product_public_fields,
        )
        from server.services.product_catalog_projection import catalog_product_records

        wanted = str(name or "")
        record = next(
            (
                dict(item) for item in catalog_product_records()
                if item.get("name") == wanted or item.get("code") == wanted
            ),
            None,
        )
        if record is None:
            return None
        product = find_product(cached_products(), str(record["name"]))
        if product is None:
            return None
        record["fields"] = product_public_fields(product)
        return record

    @staticmethod
    def product_contracts(
        name: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return term-structure contracts from the installation catalog."""
        from server.services.product_market_data import contract_listing

        return contract_listing(
            name,
            start_date=start_date,
            end_date=end_date,
        )

    @staticmethod
    def product_price_series(payload: dict[str, Any]) -> dict[str, Any]:
        """Read catalog market data without selecting a backtest service."""
        from server.services.product_market_data import price_series

        return price_series(payload)

    @staticmethod
    def product_tree(
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
        *,
        checkbox_default: bool = False,
    ) -> list[dict[str, Any]]:
        """Render a Manager-owned product tree without a service port."""
        from server.modules.products.product_category_views import (
            render_product_tree,
        )

        return render_product_tree(
            category_id, principal=principal, source_ids=source_ids,
            checkbox_default=checkbox_default,
        )

    @staticmethod
    def contract_tree(
        path: str | None = None,
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
    ) -> list[dict[str, Any]]:
        """Render lazy product or contract leaves from the catalog tree."""
        return ClientStateService.contract_tree_page(
            path, category_id, source_ids, principal, limit=None,
        )["nodes"]

    @staticmethod
    def contract_tree_page(
        path: str | None = None,
        category_id: str | list[str] | tuple[str, ...] | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
        principal: str = "",
        *,
        query: str = "",
        page: int = 1,
        limit: int | None = 25,
    ) -> dict[str, Any]:
        """Return one searchable, bounded page of lazy catalog leaves.

        The tree endpoint deliberately owns the paging boundary.  A browser
        or embedded client never needs to download every product merely to
        render one ``Product Lists`` folder.  ``contract_tree`` remains the
        compatibility list API for callers that do not need page metadata.
        """
        from server.modules.products.product_category_views import (
            category_products_for_path,
            tree_for_path,
        )
        from server.modules.shared.price_services import (
            available_sources_for_product, cached_contracts, contract_has_data,
        )
        from server.services.product_catalog_projection import (
            catalog_product_description,
            source_family_ids_for_member_ids,
        )
        from server.services.product_tree import find_node_by_path
        from tools.products.Futures import FuturesContract
        from tools.products.classifier_paths import classifier_object_path

        requested_page = max(1, int(page or 1))
        requested_limit = (
            10**9 if limit is None
            else min(100, max(1, int(limit or 25)))
        )
        search = str(query or "").strip().casefold()

        requested_path = str(path or "")
        node_path = requested_path
        if node_path.endswith("/_products"):
            node_path = node_path[:-10]
        tree, node_path = tree_for_path(
            node_path, category_id, principal=principal, source_ids=source_ids,
        )
        category_objects = category_products_for_path(
            node_path if "/ProductCategory/" in node_path else requested_path,
            category_id,
            principal=principal,
            source_ids=source_ids,
        )
        if category_objects is not None:
            objects = category_objects
        else:
            node = find_node_by_path(tree, node_path.split("/")) if node_path else None
            objects = (
                node.get("$OBJECTS$", [])
                if isinstance(node, dict)
                else ([] if node_path else list(cached_contracts()))
            )
        result = []
        for product in sorted(objects, key=lambda item: str(getattr(item, "name", item))):
            name = str(getattr(product, "name", product))
            is_contract = isinstance(product, FuturesContract)
            sources = available_sources_for_product(product)
            has_data = contract_has_data(name) if is_contract else bool(sources)
            description = catalog_product_description(product, name)
            value = {
                "title": name,
                "key": classifier_object_path(product),
                "checkbox": False,
                "folder": False,
                "lazy": False,
                "product_name": name,
                "product_code": str(getattr(product, "code", "") or name),
                "product_type": "contract" if is_contract else "product",
                "has_data": has_data,
                "desc": description,
                "description": description,
                "source_ids": [item["alias"] for item in sources],
                "source_family_ids": list(source_family_ids_for_member_ids(
                    item["alias"] for item in sources
                )),
                "exchange": _catalog_exchange(product, name),
                "product_path": classifier_object_path(product),
            }
            if is_contract:
                value["contract_uid"] = name
            searchable = " ".join(
                str(value.get(key) or "")
                for key in (
                    "title", "product_name", "product_code", "desc",
                    "exchange", "product_path", "source_ids",
                )
            ).casefold()
            if not search or search in searchable:
                result.append(value)
        total = len(result)
        total_pages = max(1, (total + requested_limit - 1) // requested_limit)
        offset = (requested_page - 1) * requested_limit
        return {
            "nodes": result[offset:offset + requested_limit],
            "page": requested_page,
            "limit": requested_limit,
            "total": total,
            "total_pages": total_pages,
            "has_more": requested_page < total_pages,
        }

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
