"""Helpers for submission routes."""

from __future__ import annotations

from typing import Iterable, Sequence, Union

import server.services.runtime_state as runtime_state
from server.modules.products.product_path_selection import resolve_selection_products
from server.services.runtime_state import factor_testers_lock
from server.services.product_tree import tree


# ── 通用产品解析 ──────────────────────────────────────────────────


def resolve_products(
    source: Union[object, list[str], Iterable],
    *attrs: str,
) -> tuple[list[str], list[dict]]:
    """从多种来源解析产品并提取指定属性（与具体产品类别无关）.

    source 可以是:
      - tester 对象 (有 selected_paths 或 products 属性)
      - 路径列表 (如 ['Futures/IF', '-Futures/IF/IF2506'])
      - 产品对象迭代器

    正负路径: 通过 resolve_selection_products 处理, '-prefix' 路径会被排除.

    Returns:
      (canonical_paths, [{attr: val, ...}, ...])
    """
    paths, products_objs = _resolve_source(source)
    result = [product_attrs(p, *attrs) for p in products_objs]
    print(f"[DEBUG resolve_products] source_type={type(source).__name__}, paths={paths[:3] if len(paths)>3 else paths}, attrs={attrs}, product_count={len(result)}")
    if result:
        print(f"[DEBUG resolve_products] first={result[0]}")
    return paths, result


def _resolve_source(source) -> tuple[list[str], list]:
    """分发 source 类型, 返回 (paths, product_objects)."""
    # tester 对象: 优先 selected_paths, 其次 products
    paths = getattr(source, 'selected_paths', None)
    if paths:
        return resolve_selection_products(paths, tree)

    products = getattr(source, 'products', None)
    if products:
        return [], sorted(products, key=lambda p: getattr(p, 'name', str(p)))

    # 路径列表 (list of str)
    if isinstance(source, list) and source and isinstance(source[0], str):
        return resolve_selection_products(source, tree)

    # tester 有 selected_paths/ products 但都是空的 → 兜底空列表
    if paths is not None or products is not None:
        return [], []

    # 其他可迭代 → 视为产品对象序列
    try:
        prod_list = list(source)
        return [], sorted(prod_list, key=lambda p: getattr(p, 'name', str(p)))
    except TypeError:
        return [], []


def product_attrs(p, *attrs: str) -> dict:
    """从产品对象按需提取属性, 纯 getattr, 不绑定任何产品类别."""
    result = {}
    for a in attrs:
        val = getattr(p, a, '')
        result[a] = '' if val is None else val
    return result


# ── tester / submission 专用 ──────────────────────────────────────


def tester_to_dict(t):
    """Convert FactorTester to frontend payload."""
    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias

    selected_paths = getattr(t, 'selected_paths', None) or []
    has_products = bool(getattr(t, 'products', None))
    print(f"[DEBUG tester_to_dict] id={core_id}, name={t.name}, selected_paths_count={len(selected_paths)}, has_products={has_products}")
    if selected_paths:
        print(f"[DEBUG tester_to_dict] selected_paths[:3]={selected_paths[:3]}")
    _, products_list = resolve_products(t, 'name', 'desc')
    print(f"[DEBUG tester_to_dict] products_list_count={len(products_list)}")

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
