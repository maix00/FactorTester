"""Smoke-tests for group.py helpers that are still live after the
issue-114 GroupRunResult deletion. The old GroupRunResult-based
/get_group_snapshot tests were deleted along with GroupRunResult itself
(the fallback branch in /get_group_snapshot now returns 400 when no
event_execution is present, so those tests were already exercising dead code).
"""

from __future__ import annotations

import pandas as pd

from server.modules.single_factor_test import group as group_routes


def test_snapshot_product_display_falls_back_to_openctp_product_name(monkeypatch):
    from sources.LocalCNFutures import product_catalog
    from sources.OpenCTP import products as openctp_products

    monkeypatch.setattr(
        product_catalog,
        "load_product_catalog",
        lambda **_: pd.DataFrame(columns=["_product_name", "品种代码", "交易所代码", "合约标的", "简称", "类别"]),
    )
    monkeypatch.setattr(
        openctp_products,
        "load_products_list",
        lambda: [
            {"ExchangeID": "CZCE", "ProductID": "AP", "ProductName": "苹果", "ProductClass": "1"},
        ],
    )

    assert group_routes._snapshot_product_display("AP.CZC")["desc"] == "苹果"
