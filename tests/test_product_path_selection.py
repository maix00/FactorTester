from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types


class _Product:
    def __init__(self, name):
        self.name = name


def _load_selection_module(monkeypatch):
    product_tree = types.ModuleType("server.services.product_tree")

    def find_node_by_path(tree, parts):
        current = tree
        if len(parts) >= 2 and parts[-2] == "_products":
            node = current[parts[0]]
            return next((product for product in node["$OBJECTS$"] if product.name == parts[-1]), None)
        for part in parts:
            current = current[part]
        return current

    def get_minimal_paths(paths):
        result = []
        for path in sorted(paths, key=len):
            if not any(path == current or path.startswith(current + "/") for current in result):
                result.append(path)
        return result

    product_tree.find_node_by_path = find_node_by_path
    product_tree.get_minimal_paths = get_minimal_paths
    monkeypatch.setitem(sys.modules, "server.services.product_tree", product_tree)
    module_path = Path(__file__).parents[1] / "server/modules/products/product_path_selection.py"
    spec = importlib.util.spec_from_file_location("_product_path_selection_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_negative_product_path_excludes_leaf_while_parent_path_is_retained(monkeypatch):
    selection = _load_selection_module(monkeypatch)
    rb = _Product("RB.SHF")
    hc = _Product("HC.SHF")
    tree = {"Metals": {"$OBJECTS$": [rb, hc]}}

    paths, products = selection.resolve_selection_products(
        ["Metals", "-Metals/_products/RB.SHF"],
        tree,
    )

    assert paths == ["Metals", "-Metals/_products/RB.SHF"]
    assert [product.name for product in products] == ["HC.SHF"]


def test_duplicate_or_redundant_selection_paths_are_canonicalized(monkeypatch):
    selection = _load_selection_module(monkeypatch)

    paths = selection.canonicalize_selection_paths([
        "Metals",
        "Metals/_products/RB.SHF",
        "-Metals/_products/RB.SHF",
        "-Metals/_products/RB.SHF",
    ])

    assert paths == ["Metals", "-Metals/_products/RB.SHF"]
