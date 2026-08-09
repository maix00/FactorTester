"""Read-only local FTClient state exposed through Manager 7998."""

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


class ClientStateService:
    """Project principal-owned local state without invoking the bundled CLI."""

    def __init__(self, client_root: Path | None = None) -> None:
        self.client_root = (client_root or default_client_root()).resolve()

    def profiles(self, principal: str) -> list[dict[str, Any]]:
        root = self.client_root / "profiles"
        result: list[dict[str, Any]] = []
        if not root.is_dir():
            return result
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
            owner = str(binding.get("principal_ref") or "") if isinstance(binding, dict) else ""
            if owner != principal:
                continue
            result.append(value)
        return result

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

    def local_product_groups(self, principal: str) -> list[dict[str, Any]]:
        """Return product groups registered in this client's local catalog.

        The catalog is installation-local, unlike ``/api/product-groups``
        which is owned by the selected service port.  We still include the
        owner reference in every row so the UI can explain where a group came
        from without guessing whether it is a server object.
        """
        from tools.cli.catalog import LocalCatalogStore

        store = LocalCatalogStore(self.client_root)
        groups = store.list_groups()
        profiles = {
            str(item.get("profile_id") or "")
            for item in self.profiles(principal)
            if str(item.get("profile_id") or "")
        }
        visible: list[dict[str, Any]] = []
        for group in groups:
            owner = str(group.get("owner_ref") or "")
            # A local catalog belongs to this OS user.  Restrict rows that
            # carry an explicit owner to this principal or one of its local
            # profiles; unowned rows are retained for migration visibility.
            if owner and owner not in {principal, f"user:{principal}"} and owner not in profiles:
                continue
            value = dict(group)
            definition = value.pop("definition_json", "")
            try:
                parsed = json.loads(definition) if definition else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {}
            if isinstance(parsed, dict):
                value["definition"] = parsed
                for key in ("paths", "product_names", "description", "research_refs"):
                    if key in parsed and key not in value:
                        value[key] = parsed[key]
            try:
                value["products"] = store.list_group_products(
                    str(value.get("group_ref") or "")
                )
            except (OSError, ValueError):
                value["products"] = []
            value["source"] = "local"
            visible.append(value)
        return sorted(
            visible,
            key=lambda item: (
                str(item.get("name") or "").casefold(),
                str(item.get("group_ref") or ""),
            ),
        )

    def local_product_group(self, principal: str, group_ref: str) -> dict[str, Any] | None:
        wanted = str(group_ref or "").strip()
        if not wanted:
            return None
        return next(
            (
                item for item in self.local_product_groups(principal)
                if str(item.get("group_ref") or "") == wanted
                or str(item.get("name") or "") == wanted
            ),
            None,
        )

    @staticmethod
    def product_categories() -> list[dict[str, Any]]:
        """Return the same explicit category contract used by service ports."""
        from server.modules.shared.price_services import available_product_categories

        return available_product_categories()

    @staticmethod
    def product_sources(origin: str = "local") -> list[dict[str, Any]]:
        """Return actual registered data-source bundles for one catalog origin."""
        from server.services.product_catalog_projection import product_source_descriptors

        return [dict(item) for item in product_source_descriptors(origin)]

    @staticmethod
    def local_product_names() -> list[dict[str, Any]]:
        """Return products from the client-side Python/data bundle."""
        from server.services.product_catalog_projection import catalog_product_records

        return [dict(item) for item in catalog_product_records()]

    @staticmethod
    def local_product_fields(name: str) -> dict[str, Any] | None:
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
    def local_product_tree(category_id: str | None = None) -> list[dict[str, Any]]:
        """Render the installation-local product tree without a service port."""
        from server.modules.shared.price_services import (
            cached_product_tree,
            cached_product_tree_for_category,
            normalize_product_category_id,
        )
        from server.services.product_tree import convert_to_fancytree

        tree = cached_product_tree() if not str(category_id or "").strip() else cached_product_tree_for_category(
            normalize_product_category_id(category_id)
        )
        return convert_to_fancytree(
            tree.tree,
            checkbox_default=False,
        )

    @staticmethod
    def local_contract_tree(path: str | None = None, category_id: str | None = None) -> list[dict[str, Any]]:
        """Render lazy product or contract leaves from the catalog tree."""
        from server.modules.shared.price_services import (
            available_sources_for_product,
            cached_contracts,
            cached_product_tree,
            cached_product_tree_for_category,
            contract_has_data,
            normalize_product_category_id,
        )
        from server.services.product_tree import find_node_by_path
        from tools.products.Futures import FuturesContract
        from tools.products.classifier_paths import classifier_object_path

        tree = (
            cached_product_tree()
            if not str(category_id or "").strip()
            else cached_product_tree_for_category(normalize_product_category_id(category_id))
        ).tree
        node_path = str(path or "")
        if node_path.endswith("/_products"):
            node_path = node_path[:-10]
        node = find_node_by_path(tree, node_path.split("/")) if node_path else None
        objects = node.get("$OBJECTS$", []) if isinstance(node, dict) else list(cached_contracts())
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
