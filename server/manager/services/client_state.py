"""Principal-owned FTClient state exposed through Manager 7998."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
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


class ClientStateService:
    """Project and update principal-owned state without invoking a service port."""

    def __init__(
        self,
        client_root: Path | None = None,
        *,
        control_store: object | None = None,
        profile_cache_root: Path | None = None,
    ) -> None:
        self.client_root = (client_root or default_client_root()).resolve()
        self.control_store = control_store
        self.profile_cache = (
            ProfileProjectionCache(profile_cache_root)
            if profile_cache_root is not None else None
        )

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

        # A deployed public Manager does not mount a user's device-local
        # Client root.  PostgreSQL therefore supplies the safe Profile
        # identity projection when it has been migrated.  Local files remain
        # the fallback for development and for richer owner-side state.
        if self.control_store is not None:
            self._flush_profile_cache(principal)
            try:
                rows = self.control_store.list_profiles(principal)
            except (
                AttributeError, ConnectionError, ControlDatabaseError,
                OSError, RuntimeError, TypeError, ValueError,
            ):
                rows = []
            indexed = {
                str(item.get("profile_id") or ""): item
                for item in result
                if str(item.get("profile_id") or "")
            }
            for row in rows:
                if not isinstance(row, dict):
                    continue
                profile_id = str(row.get("profile_id") or "").strip()
                if not profile_id:
                    continue
                value = control_profile_projection(row, principal)
                if profile_id in indexed:
                    merged = dict(value)
                    merged.update(indexed[profile_id])
                    indexed[profile_id] = merged
                else:
                    indexed[profile_id] = value
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
        return project_account_product_groups(
            groups=load_product_groups(principal),
            principal=principal,
            profiles=profiles,
            research_records=research,
            product_records=[dict(item) for item in catalog_product_records()],
            origin="server",
        )

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
        self, principal: str, name: str, paths: list[str],
    ) -> dict[str, Any] | None:
        """Create an account product group and return its catalog projection."""
        from server.modules.products.product_group_store import create_product_group

        created = create_product_group(principal, name, paths)
        if created is None:
            return None
        return self.product_group(
            principal, f"product-group:{created['id']}",
        )

    @staticmethod
    def factor_library(principal: str) -> dict[str, Any]:
        """Return the Manager-owned, source-free factor catalog."""
        from server.modules.custom_factors.client_library import (
            build_client_library_projection,
        )
        from server.modules.custom_factors.factor_library_service import (
            build_factor_library_overview,
        )

        payload = build_factor_library_overview(
            principal, include_subordinates=False,
        )
        return build_client_library_projection(payload, principal=principal)

    @staticmethod
    def factor_sets(principal: str, query: str = "") -> list[dict[str, Any]]:
        """Return explicitly synchronized immutable factor sets."""
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_catalog,
        )

        return factor_set_catalog(principal, query)

    @staticmethod
    def factor_set_detail(
        principal: str,
        target_ref: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_detail,
        )

        return factor_set_detail(
            principal, target_ref, offset=offset, limit=limit,
        )

    @staticmethod
    def factor_set_descriptor(
        principal: str, target_ref: str,
    ) -> dict[str, Any] | None:
        """Return one server-registered immutable Factor Set descriptor."""
        from server.modules.custom_factors.factor_set_registry import (
            factor_set_descriptor,
        )

        return factor_set_descriptor(principal, target_ref)

    @staticmethod
    def product_categories() -> list[dict[str, Any]]:
        """Return the same explicit category contract used by service ports."""
        from server.modules.shared.price_services import available_product_categories

        return available_product_categories()

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
        category_id: str | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Render a Manager-owned product tree without a service port."""
        from server.modules.shared.price_services import (
            cached_product_tree,
            cached_product_tree_for_category,
            normalize_product_category_id,
        )
        from server.services.product_catalog_projection import filter_product_tree
        from server.services.product_tree import convert_to_fancytree

        tree = cached_product_tree() if not str(category_id or "").strip() else cached_product_tree_for_category(
            normalize_product_category_id(category_id)
        )
        return convert_to_fancytree(
            filter_product_tree(tree.tree, source_ids),
            checkbox_default=False,
        )

    @staticmethod
    def contract_tree(
        path: str | None = None,
        category_id: str | None = None,
        source_ids: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Render lazy product or contract leaves from the catalog tree."""
        from server.modules.shared.price_services import (
            available_sources_for_product,
            cached_contracts,
            cached_product_tree,
            cached_product_tree_for_category,
            contract_has_data,
            normalize_product_category_id,
        )
        from server.services.product_catalog_projection import filter_product_tree
        from server.services.product_tree import find_node_by_path
        from tools.products.Futures import FuturesContract
        from tools.products.classifier_paths import classifier_object_path

        tree = (
            cached_product_tree()
            if not str(category_id or "").strip()
            else cached_product_tree_for_category(normalize_product_category_id(category_id))
        ).tree
        tree = filter_product_tree(tree, source_ids)
        node_path = str(path or "")
        if node_path.endswith("/_products"):
            node_path = node_path[:-10]
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
                "desc": str(
                    getattr(product, "desc", "")
                    or ("合约" if is_contract else "产品")
                ),
                "source_ids": [item["alias"] for item in sources],
            }
            if is_contract:
                value["contract_uid"] = name
            result.append(value)
        return result

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
