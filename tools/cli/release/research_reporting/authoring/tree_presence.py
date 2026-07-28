"""Point lookups against one stable report-tree HEAD generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .binding_index import binding_exists, ensure_binding_index
from .tree_locators import locator_exists
from .tree_navigation import node_path
from .tree_paths import report_tree_paths
from .tree_store import load_head, load_node, tree_lock


@dataclass(frozen=True)
class ReportTreePresence:
    paths: dict[str, Path]
    head: dict[str, Any]
    root: dict[str, Any]

    @classmethod
    def load(cls, *, package_root: Path, branch_id: str) -> "ReportTreePresence":
        paths = report_tree_paths(package_root, branch_id)
        with tree_lock(paths):
            head = load_head(paths)
            root = load_node(paths, head["root_ref"])
            ensure_binding_index(paths, root, head["generation"])
        return cls(paths=paths, head=head, root=root)

    def component_exists(self, component_id: str) -> bool:
        if component_id == "root":
            return True
        if locator_exists(self.paths, component_id, self.head["generation"]):
            return True
        if self.head["locator_generation"] == self.head["generation"]:
            return False
        try:
            node_path(self.paths, self.root, component_id, self.head["generation"])
        except ValueError:
            return False
        return True

    def binding_exists(self, binding_id: str) -> bool:
        return binding_exists(self.paths, binding_id, self.head["generation"])

    def asset_exists(self, asset_ref: str) -> bool:
        return any(item["asset_ref"] == asset_ref for item in self.head["assets"])

    def bindings_for(self, component_id: str) -> list[dict[str, Any]]:
        nodes, _ = node_path(
            self.paths, self.root, component_id, self.head["generation"],
        )
        return list(nodes[-1]["bindings"])
