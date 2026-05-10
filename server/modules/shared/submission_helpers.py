"""Helpers for submission routes."""

from __future__ import annotations

from server.services.product_tree import find_node_by_path, get_minimal_paths, tree


def tester_to_dict(t):
    """Convert FactorTester to frontend payload."""
    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias
    return {
        'id':                   core_id,
        'name':                 t.name,
        'product_count':        len(t.products) if hasattr(t, 'products') and t.products else 0,
        'selected_paths':       getattr(t, 'selected_paths', []) or [],
        'factor_tester_name':   t.name,
        'factor_tester_serial': f"#{core_id}" if core_id.isdigit() else t.alias,
    }


def resolve_products_from_paths(raw_paths: list[str]):
    """Return (minimal_paths, deduped_sorted_products) from selected tree paths."""
    selected_paths = get_minimal_paths(raw_paths or [])
    selected_products = []
    for path in selected_paths:
        node = find_node_by_path(tree, path.split('/'))
        if isinstance(node, dict) and '$OBJECTS$' in node and isinstance(node['$OBJECTS$'], list):
            selected_products.extend(node['$OBJECTS$'])
        else:
            selected_products.append(node)
    selected_products = sorted(list(set(selected_products)))
    return selected_paths, selected_products
