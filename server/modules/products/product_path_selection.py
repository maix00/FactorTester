"""Resolve product-group include and exclusion paths."""

from __future__ import annotations

from server.services.product_tree import find_node_by_path, get_minimal_paths


def canonicalize_selection_paths(raw_paths: list[str] | None) -> list[str]:
    """Return minimal positive paths followed by deduped negative paths."""
    positive_paths = []
    negative_paths = []
    for raw_path in raw_paths or []:
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        path = raw_path.strip()
        if path.startswith('-'):
            excluded_path = path[1:].strip()
            if excluded_path:
                negative_paths.append(excluded_path)
        else:
            positive_paths.append(path)

    included = get_minimal_paths(positive_paths)
    excluded = get_minimal_paths(negative_paths)
    return included + [f'-{path}' for path in excluded]


def _products_for_paths(paths: list[str], tree) -> list:
    products = []
    for path in paths:
        node = find_node_by_path(tree, path.split('/'))
        if isinstance(node, dict) and isinstance(node.get('$OBJECTS$'), list):
            products.extend(node['$OBJECTS$'])
        elif node is not None:
            products.append(node)
    return products


def resolve_selection_products(raw_paths: list[str] | None, tree) -> tuple[list[str], list]:
    """Resolve product objects for include paths minus negative exclusion paths."""
    selected_paths = canonicalize_selection_paths(raw_paths)
    included_paths = [path for path in selected_paths if not path.startswith('-')]
    excluded_paths = [path[1:] for path in selected_paths if path.startswith('-')]
    included_products = _products_for_paths(included_paths, tree)
    excluded_products = set(_products_for_paths(excluded_paths, tree))
    selected_products = {
        product for product in included_products
        if product is not None and product not in excluded_products
    }
    return selected_paths, sorted(selected_products, key=lambda product: getattr(product, 'name', str(product)))
