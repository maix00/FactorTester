"""
产品展示名工具

提供:
- product_display_name(p) → {'name': str, 'desc': str}
- get_contract_desc(contract_uid) → str
- get_product_contracts(product, start_date, end_date) → list[dict]
统一所有需要在前端展示产品名的地方。
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from tools.products.Product import Product
from tools.products.AdjustableTermStructure import (
    AdjustableProductMixin,
    lookup_contract_product,
    resolve_term_structure_product,
)


def product_display_name(product: Any) -> Dict[str, str]:
    """
    返回产品的展示名和中文描述。

    返回格式：{'name': str, 'desc': str}
    - name: 产品唯一标识（如 'IF.CFE' 或 'IF2412.CFE'）
    - desc: 中文描述（如 '沪深300指数期货'）

    对于 AdjustableContractMixin 合约，若自身无 desc 则通过
    term structure 查找父品种的 desc。
    """
    name = getattr(product, 'name', str(product))
    desc = getattr(product, 'desc', '')

    # 如果自身没有 desc，尝试从父品种获取
    if not desc:
        parent = None
        try:
            parent = getattr(product, 'parent_product', None)
            if callable(parent):
                parent = parent()
        except Exception:
            parent = None
        if parent is None:
            parent = resolve_term_structure_product(product)
        if parent is not None:
            desc = getattr(parent, 'desc', '') or ''
        if not desc:
            contract_uid = getattr(product, 'name', str(product))
            if contract_uid:
                desc = get_contract_desc(contract_uid)

    return {'name': name, 'desc': desc or name}


def get_contract_desc(contract_uid: str) -> str:
    """
    根据合约 UID 查找父品种的中文描述。

    适用场景：
    - product_display_name：合约自身无 desc 时继承父品种 desc
    - get_product_contracts：为合约列表补充 desc

    返回 '' 如果找不到或对应品种无 desc。
    """
    if not contract_uid:
        return ''

    paths = _get_term_structure_paths()
    if not paths:
        return ''

    product_name = lookup_contract_product(contract_uid, paths)
    if not product_name:
        return ''

    parent = Product.get(product_name)
    if parent is not None:
        desc = getattr(parent, 'desc', '')
        if desc:
            return desc

    return ''


def get_product_contracts(
    product: Any,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    返回产品在日期范围内的合约列表。

    委托给 product.get_contract_list()（AdjustableProductMixin 默认实现
    基于 term structure 聚合；Futures 子类覆写为 roller_info），
    然后为每个元素补充 `desc` 字段。

    返回：
        [{contract, uid, start, end, start_ts, end_ts, desc}, ...]
    """
    contracts = product.get_contract_list(start_date=start_date, end_date=end_date)
    for c in contracts:
        c['desc'] = get_contract_desc(c['uid'])
    return contracts


# ---------------------------------------------------------------------------
# 内部 helpers
# ---------------------------------------------------------------------------

# 缓存已收集的 term_structure_path 列表
_term_structure_paths_cache: Optional[list] = None


def _get_term_structure_paths() -> list:
    """收集所有 AdjustableProductMixin 实例的 term_structure_path 列表（带缓存）。"""
    global _term_structure_paths_cache
    if _term_structure_paths_cache is not None:
        return _term_structure_paths_cache

    paths = []
    for (_key, inst) in Product.get_all():
        if not isinstance(inst, AdjustableProductMixin):
            continue
        path = inst.get_term_structure_path()
        if path and path not in paths:
            paths.append(path)

    _term_structure_paths_cache = paths
    return paths
