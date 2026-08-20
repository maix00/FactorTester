"""Data-source Category listing for the Category management tab.

Exposes the Category groupings a data source has already defined (e.g.
LocalCNFutures' 行业 / 日夜盘 / 行业×日夜盘), so the frontend Category list can
seed itself with source="数据库" entries before the user adds 自定义 / 现场 ones.
"""
from __future__ import annotations

from typing import Any

from flask import jsonify

from server.services.http_auth import login_required
from . import sft_bp

# 这些数据源 Category 应用到的产品路径（中国期货品种 + 合约）。
_CN_FUTURES_PRODUCT_PATHS = ["CNFutures", "CNFuturesContract"]


def _category_payload(cat: Any, product_paths: list[str]) -> dict[str, Any]:
    from server.services.product_catalog_projection import source_ids_by_product_path
    raw = [str(c) for c in (getattr(cat, "categories", []) or [])]
    names = [c for c in raw if c != "Others"]
    # 组外产品归入"其他"。
    if "Others" in raw and "其他" not in names:
        names.append("其他")
    path_sources = source_ids_by_product_path(product_paths)
    return {
        "name": str(getattr(cat, "alias", "") or ""),
        "source": "数据库",
        "product_paths": list(product_paths),
        "categories": names,
        "enabled": True,
        "source_ids": sorted({
            source_id for values in path_sources.values() for source_id in values
        }),
        "path_sources": [
            {"path": path, "source_ids": list(path_sources.get(path, ()))}
            for path in product_paths
        ],
    }


def list_data_source_categories() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        from sources.LocalCNFutures.CNFutures import (
            CNFuturesDayNightTimeCategory,
            CNFuturesSectorCategory,
            CNFuturesSectorNightTimeCategory,
        )
        for cat in (
            CNFuturesSectorCategory,
            CNFuturesDayNightTimeCategory,
            CNFuturesSectorNightTimeCategory,
        ):
            out.append(_category_payload(cat, _CN_FUTURES_PRODUCT_PATHS))
    except Exception:
        pass
    return out


@sft_bp.route("/api/data_source_categories", methods=["GET"])
@login_required
def api_data_source_categories():
    return jsonify({"success": True, "categories": list_data_source_categories()})
