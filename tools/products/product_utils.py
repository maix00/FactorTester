"""
产品展示名工具

提供 product_display_name(p) → {'name': str, 'desc': str}，
统一所有需要在前端展示产品名的地方。
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from tools.products.Product import Product
from tools.products.AdjustableTermStructure import (
    AdjustableContractMixin,
    AdjustableProductMixin,
    lookup_contract_product,
)


def product_display_name(product: Any) -> Dict[str, str]:
    """
    返回产品的展示名和中文描述。

    返回格式：{'name': str, 'desc': str}
    - name: 产品唯一标识（如 'IF.CFE' 或 'IF2412.CFE'）
    - desc: 中文描述（如 '沪深300指数期货'）

    对于 AdjustableContractMixin 合约，若自身无 desc 则通过
    AdjustableTermStructure 的工具函数查找父品种的 desc。
    """
    name = getattr(product, 'name', str(product))
    desc = getattr(product, 'desc', '')

    # 如果自身没有 desc，尝试从父品种获取
    if not desc:
        desc = _try_inherit_desc_from_term_structure(product)

    return {'name': name, 'desc': desc or name}


def _try_inherit_desc_from_term_structure(product: Any) -> str:
    """
    对 AdjustableContractMixin 合约，通过 term structure store 查找父品种的 desc。

    流程：
    1. 确认对象是 AdjustableContractMixin（is_term_contract() == True）
    2. 收集所有 AdjustableProductMixin 实例的 term_structure_path
    3. 用 lookup_contract_product() 查 contract_uid → product_name
    4. 用 Product.get(product_name) 获取品种实例的 desc
    """
    # 只有 AdjustableContractMixin 合约才需要继承
    is_contract = getattr(product, 'is_term_contract', None)
    if callable(is_contract):
        is_contract = is_contract()
    if not is_contract or not isinstance(product, AdjustableContractMixin):
        return ''

    contract_uid = getattr(product, 'name', str(product))
    if not contract_uid:
        return ''

    # 收集所有已知的 term_structure_path
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
