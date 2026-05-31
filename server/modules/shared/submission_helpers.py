"""Helpers for submission routes."""

from __future__ import annotations

from typing import Sequence

import server.services.runtime_state as runtime_state
from server.modules.products.product_path_selection import resolve_selection_products
from server.services.runtime_state import factor_testers_lock
from server.services.product_tree import tree
from tools.products.product_utils import get_contract_desc


def _product_name_desc(p) -> dict:
    """Return {name, desc} for a product object."""
    name = getattr(p, 'name', str(p))
    desc = getattr(p, 'desc', '') or ''
    if not desc:
        desc = get_contract_desc(name) or ''
    return {'name': name, 'desc': desc}


def products_with_desc(products: Sequence) -> list[dict]:
    """Convert a sequence of product objects to [{name, desc}, ...] with inherited descriptions."""
    return [_product_name_desc(p) for p in products]


def tester_to_dict(t):
    """Convert FactorTester to frontend payload."""
    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias

    # 优先从 selected_paths 解析完整产品列表（含正向/负向路径）
    selected_paths = getattr(t, 'selected_paths', None) or []
    if selected_paths:
        _, resolved = resolve_selection_products(selected_paths, tree)
        products_list = products_with_desc(resolved)
    elif hasattr(t, 'products') and t.products:
        products_list = products_with_desc(t.products)
    else:
        products_list = []

    return {
        'id':                   core_id,
        'name':                 t.name,
        'product_count':        len(products_list),
        'selected_paths':       selected_paths,
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
    """Return active testers that still hold products (via paths or direct products)."""
    with factor_testers_lock:
        testers = [
            t for t in runtime_state.factor_testers
            if (getattr(t, 'selected_paths', None) and len(t.selected_paths) > 0)
            or (t.products and len(t.products) > 0)
        ]
        if page_uuid:
            testers = [t for t in testers if getattr(t, '_page_uuid', None) == page_uuid]
        return testers


def submissions_payload(page_uuid=None):
    """Standard submissions list payload for frontend sync."""
    return [tester_to_dict(t) for t in valid_testers(page_uuid)]
