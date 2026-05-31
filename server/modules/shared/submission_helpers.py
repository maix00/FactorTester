"""Helpers for submission routes."""

from __future__ import annotations

import server.services.runtime_state as runtime_state
from server.modules.products.product_path_selection import resolve_selection_products
from server.services.runtime_state import factor_testers_lock
from server.services.product_tree import tree


def tester_to_dict(t):
    """Convert FactorTester to frontend payload."""
    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias
    products_list = []
    if hasattr(t, 'products') and t.products:
        for p in t.products:
            products_list.append({
                'name': getattr(p, 'name', str(p)),
                'desc': getattr(p, 'desc', '') or '',
            })
    return {
        'id':                   core_id,
        'name':                 t.name,
        'product_count':        len(t.products) if hasattr(t, 'products') and t.products else 0,
        'selected_paths':       getattr(t, 'selected_paths', []) or [],
        'products':             products_list,
        'factor_tester_name':   t.name,
        'factor_tester_serial': f"#{core_id}" if core_id.isdigit() else t.alias,
        'label':                getattr(t, 'label', '') or '',
        'product_group':        getattr(t, 'product_group', '') or '',
    }


def resolve_products_from_paths(raw_paths: list[str]):
    """Return canonical paths and included products after explicit exclusions."""
    return resolve_selection_products(raw_paths, tree)


def valid_testers(page_uuid=None):
    """Return active testers that still hold products."""
    with factor_testers_lock:
        testers = [t for t in runtime_state.factor_testers if t.products and len(t.products) > 0]
        if page_uuid:
            testers = [t for t in testers if getattr(t, '_page_uuid', None) == page_uuid]
        return testers


def submissions_payload(page_uuid=None):
    """Standard submissions list payload for frontend sync."""
    return [tester_to_dict(t) for t in valid_testers(page_uuid)]
