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

        projection = build_upload_projection(snapshot)
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
    ) -> dict[str, Any]:
        """Return one local report chapter for on-demand rendering."""
        package_root, branch_id, profile_id = self._local_report_location(principal, local_ref)
        from tools.cli.release.research_reporting.authoring.tree_projection import load_chapter_snapshot
        from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
        snapshot = load_chapter_snapshot(
            package_root=package_root, branch_id=branch_id, chapter_id=chapter_id,
        )
        projection = build_upload_projection(snapshot)
        projection.update(source="local", local_ref=local_ref,
                          profile_id=profile_id)
        return projection

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
    def product_source_descriptor() -> dict[str, Any]:
        """Return the local catalog descriptor used by the embedded client."""
        from server.modules.shared.price_services import product_catalog_source_descriptor

        return product_catalog_source_descriptor("local")

    @staticmethod
    def local_product_names() -> list[dict[str, Any]]:
        """Return products from the client-side Python/data bundle."""
        from server.modules.shared.price_services import (
            cached_products,
            product_public_fields,
        )

        result = []
        for product in cached_products():
            if product is None:
                continue
            name = str(getattr(product, "name", None) or getattr(product, "alias", None) or product)
            result.append({
                "name": name,
                "desc": getattr(product, "desc", None) or name,
                "code": getattr(product, "code", None) or (name.split(".")[0] if "." in name else name),
                "exchange": name.split(".")[1].split("@")[0] if "." in name else "",
                "product_type": "product",
                "fields": product_public_fields(product),
            })
        return result

    @staticmethod
    def local_product_fields(name: str) -> dict[str, Any] | None:
        wanted = str(name or "")
        for item in ClientStateService.local_product_names():
            if item.get("name") == wanted or item.get("code") == wanted:
                return item
        return None

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
        """Render a lazy contract node from the local category tree."""
        from server.modules.shared.price_services import (
            cached_contracts,
            cached_product_tree,
            cached_product_tree_for_category,
            contract_has_data,
            normalize_product_category_id,
            product_public_fields,
        )
        from server.services.product_tree import find_node_by_path

        tree = (
            cached_product_tree()
            if not str(category_id or "").strip()
            else cached_product_tree_for_category(normalize_product_category_id(category_id))
        ).tree
        node_path = str(path or "")
        if node_path.endswith("/_products"):
            node_path = node_path[:-10]
        node = find_node_by_path(tree, node_path.split("/")) if node_path else None
        contracts = node.get("$OBJECTS$", []) if isinstance(node, dict) else list(cached_contracts())
        result = []
        for contract in sorted(contracts, key=lambda item: str(getattr(item, "name", item))):
            name = str(getattr(contract, "name", contract))
            has_data = contract_has_data(name)
            result.append({
                "title": name,
                "key": f"CNFuturesContract/{name}",
                "checkbox": False,
                "folder": False,
                "lazy": False,
                "product_name": name,
                "product_code": name,
                "product_type": "contract",
                "contract_uid": name,
                "has_data": has_data,
                "desc": "合约" if has_data else "暂无价格数据",
                "fields": product_public_fields(contract),
            })
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
