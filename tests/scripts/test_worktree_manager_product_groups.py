from __future__ import annotations

from tools.cli.catalog import LocalCatalogStore

from server.manager.domain.product_groups import (
    project_account_product_groups,
    project_product_groups,
)


def _catalog(tmp_path):
    store = LocalCatalogStore(tmp_path / "client")
    store.upsert_source({
        "source_id": "source:local:tiger",
        "source_kind": "local",
        "class_path": "Product/Futures/JPFutures",
    })
    for ref, alias, title in (
        ("product:SI.GFE", "SI.GFE", "工业硅"),
        ("product:JNI.OSE", "JNI.OSE", "日经225小型期货"),
    ):
        store.upsert_product({
            "product_ref": ref,
            "source_id": "source:local:tiger",
            "class_path": "Product/Futures/JPFutures",
            "alias": alias,
            "display_name": title,
        })
    store.upsert_group({
        "group_ref": "product-group:maxa:cross-market",
        "owner_ref": "profile:maxa",
        "name": "跨市场候选",
        "definition": {
            "description": "研究用产品组",
            "research_refs": ["report-workspace:momentum"],
        },
    })
    store.replace_group_products(
        "product-group:maxa:cross-market",
        [
            {"product_ref": "product:SI.GFE"},
            {"product_ref": "product:JNI.OSE"},
        ],
    )
    store.replace_group_subjects(
        "product-group:maxa:cross-market",
        [
            {"subject_kind": "factor", "subject_ref": "factor:roc"},
            {"subject_kind": "factor_set", "subject_ref": "factor-set:momentum"},
        ],
    )
    return store


def _projection(store, origin, products):
    return project_product_groups(
        store=store,
        principal="18717974771",
        profiles=[{"profile_id": "maxa", "display_name": "MaxA"}],
        research_records=[{
            "record_id": "momentum",
            "local_ref": "momentum:main",
            "report_workspace_id": "momentum",
            "report_id": "report-momentum",
            "profile_id": "maxa",
            "title": "动量因子研究",
        }],
        product_records=products,
        origin=origin,
    )[0]


def test_group_projection_exposes_profile_research_and_subject_bindings(tmp_path):
    store = _catalog(tmp_path)
    group = _projection(store, "server", [{
        "product_ref": "product:SI.GFE",
        "name": "SI.GFE",
        "desc": "工业硅",
        "product_path": "Product/Futures/CNFutures/_products/SI.GFE",
    }])

    assert group["creator_kind"] == "profile"
    assert group["creator_ref"] == "profile:maxa"
    assert group["creator_title"] == "MaxA"
    assert group["profile_ref"] == "profile:maxa"
    assert group["created_for_research"] is True
    assert group["research_bindings"] == [{
        "research_ref": "report-workspace:momentum",
        "title": "动量因子研究",
        "profile_id": "maxa",
        "local_ref": "momentum:main",
    }]
    assert group["factor_refs"] == ["factor:roc"]
    assert group["factor_set_refs"] == ["factor-set:momentum"]


def test_server_projection_keeps_non_server_product_but_marks_it_unavailable(tmp_path):
    store = _catalog(tmp_path)
    group = _projection(store, "server", [{
        "product_ref": "product:SI.GFE", "name": "SI.GFE",
    }])
    products = {item["display_name"]: item for item in group["products"]}

    assert products["SI.GFE"]["available"] is True
    assert products["JNI.OSE"]["available"] is False
    assert products["JNI.OSE"]["unavailable_reason"] == (
        "非服务器提供，无法展示相关信息"
    )


def test_local_projection_resolves_products_from_the_local_catalog(tmp_path):
    store = _catalog(tmp_path)
    records = []
    for item in store.list_products():
        records.append({
            **item,
            "name": item["alias"],
            "product_path": (
                f"{item['class_path']}/_products/{item['alias']}"
            ),
        })
    group = _projection(store, "local", records)

    assert all(item["available"] for item in group["products"])
    assert {item["display_name"] for item in group["products"]} == {
        "SI.GFE", "JNI.OSE",
    }


def test_account_groups_remain_visible_without_a_service_port():
    group = project_account_product_groups(
        groups=[{
            "id": "pg-day",
            "name": "中国期货日盘",
            "product_names": ["AP.CZC", "JNI.OSE"],
            "creator_kind": "profile",
            "creator_ref": "profile:maxa",
            "research_refs": ["report-workspace:momentum"],
            "factor_refs": ["factor:roc"],
        }],
        principal="18717974771",
        profiles=[{"profile_id": "maxa", "display_name": "MaxA"}],
        research_records=[{
            "record_id": "momentum",
            "report_workspace_id": "momentum",
            "title": "动量因子研究",
            "profile_id": "maxa",
        }],
        product_records=[{
            "product_ref": "product:AP.CZC", "name": "AP.CZC",
        }],
        origin="server",
    )[0]

    assert group["group_ref"] == "product-group:pg-day"
    assert group["source"] == "server"
    assert group["creator_kind"] == "profile"
    assert group["created_for_research"] is True
    assert group["factor_refs"] == ["factor:roc"]
    assert [item["available"] for item in group["products"]] == [True, False]
