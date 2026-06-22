"""Helpers for submission routes."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable, Sequence, Union

import server.services.page_runtime as runtime_state
from server.modules.products.product_path_selection import resolve_selection_products
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
    return paths, [product_attrs(p, *attrs) for p in products_objs]


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
        if a == 'desc' and (not val or val == getattr(p, 'name', '')):
            val = _openctp_product_desc(getattr(p, 'name', str(p))) or val
        result[a] = '' if val is None else val
    return result


_EXCHANGE_SHORT_TO_OPENCTP = {
    "CFE": "CFFEX",
    "CFFEX": "CFFEX",
    "CZC": "CZCE",
    "CZCE": "CZCE",
    "DCE": "DCE",
    "GFE": "GFEX",
    "GFEX": "GFEX",
    "INE": "INE",
    "SHF": "SHFE",
    "SHFE": "SHFE",
}


@lru_cache(maxsize=512)
def _openctp_product_desc(product_name: str) -> str:
    """Return product Chinese name from OpenCTP SQLite cache; no sectors.csv fallback."""
    if not product_name:
        return ""
    code, _, exchange_short = str(product_name).partition(".")
    product_id = code.upper()
    exchange_id = _EXCHANGE_SHORT_TO_OPENCTP.get(exchange_short.upper())
    try:
        from sources.OpenCTP.products import load_products_list

        rows = load_products_list()
    except Exception:
        return ""
    if exchange_id:
        for row in rows:
            if str(row.get("ExchangeID", "")).upper() == exchange_id and str(row.get("ProductID", "")).upper() == product_id:
                return str(row.get("ProductName") or "")
    for row in rows:
        if str(row.get("ProductID", "")).upper() == product_id:
            return str(row.get("ProductName") or "")
    return ""


# ── tester / submission 专用 ──────────────────────────────────────


def tester_to_dict(t):
    """Convert ProductPathSelection or legacy FactorTester to frontend payload."""
    if hasattr(t, "to_submission_dict") and hasattr(t, "products"):
        base = t.to_submission_dict()
        _, products_list = resolve_products(t.products, 'name', 'desc')
        base.update({
            'name': base.get('id', ''),
            'product_count': len(products_list),
            'products': products_list,
            'factor_tester_name': '',
            'factor_tester_serial': f"#{base.get('id', '')}",
        })
        return base

    core_id = t.alias.split(':', 1)[-1] if ':' in t.alias else t.alias

    selected_paths = getattr(t, 'selected_paths', None) or []
    _, products_list = resolve_products(t, 'name', 'desc')

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
        'source_type':          getattr(t, 'selection_source_type', '') or 'legacy_factor_tester',
        'source_key':           getattr(t, 'selection_source_key', '') or '',
    }


def resolve_products_from_paths(raw_paths: list[str]):
    """Return canonical paths and included products after explicit exclusions."""
    return resolve_selection_products(raw_paths, tree)


def valid_testers(page_uuid=None):
    """Return active submissions, preferring product selections over legacy testers."""
    selections = runtime_state.iter_product_selections(page_uuid)
    if selections:
        return [
            selection for selection in selections
            if getattr(selection, 'selected_paths', None)
            or getattr(selection, 'products', None)
        ]
    testers = runtime_state.iter_factor_testers(page_uuid)
    return [
        t for t in testers
        if (getattr(t, 'selected_paths', None) and len(t.selected_paths) > 0)
        or (t.products and len(t.products) > 0)
    ]


def submissions_payload(page_uuid=None):
    """Standard submissions list payload for frontend sync."""
    return [tester_to_dict(t) for t in valid_testers(page_uuid)]
