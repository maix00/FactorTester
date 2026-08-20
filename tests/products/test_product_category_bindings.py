from __future__ import annotations

import importlib

import settings as Settings
import pytest

from server.modules.products.product_category_paths import (
    canonicalize_product_paths,
    category_tree,
    infer_category_ids,
    regenerate_generated_others,
)
from server.services.product_catalog_projection import (
    source_ids_by_product_path,
    source_ids_for_product_paths,
)
from server.modules.products.product_category_definition import (
    normalize_composite_label_updates,
    source_category_items,
)
from server.modules.products.product_category_store import (
    create_product_category,
    create_product_category_composition,
    update_product_category,
)
from server.modules.products import product_group_store
from server.modules.shared import price_services
from server.modules.products import product_category_paths
from server.modules.products import product_category_store
from tools.data.sqlite.account_manager import ensure_account_manager_sqlite_store


DAY_NIGHT_ID = "cnfutures_day_night"
SECTOR_ID = "cnfutures_sector"
COMPOSITE_ID = "cnfutures_day_night×cnfutures_sector"


@pytest.fixture(autouse=True)
def clear_product_caches():
    # Other catalog tests intentionally reload the CN futures module. Rebuild
    # cached trees so these contract tests never retain old class identities.
    importlib.reload(price_services)
    for cache in (
        price_services.cached_products,
        price_services.cached_contracts,
        price_services.cached_product_tree,
        price_services.cached_product_tree_for_category,
        product_category_paths._source_category_tree,
    ):
        cache.cache_clear()
    yield
    for cache in (
        price_services.cached_products,
        price_services.cached_contracts,
        price_services.cached_product_tree,
        price_services.cached_product_tree_for_category,
        product_category_paths._source_category_tree,
    ):
        cache.cache_clear()


def test_category_paths_are_canonicalized_with_signed_exclusions() -> None:
    paths = canonicalize_product_paths(
        [
            "Product/Futures/CNFutures/日夜盘/日盘",
            "-Product/Futures/CNFutures/日夜盘/夜盘1",
        ],
        category_ids=[DAY_NIGHT_ID],
        infer_legacy_categories=False,
    )

    assert paths
    assert all("/日夜盘/" not in path for path in paths)
    assert any(path.startswith("-") for path in paths)


def test_new_group_rejects_category_path_without_an_explicit_binding() -> None:
    with pytest.raises(ValueError, match="绑定对应分类"):
        canonicalize_product_paths(
            ["Product/Futures/CNFutures/日夜盘/日盘"],
            infer_legacy_categories=False,
        )


def test_legacy_composite_category_paths_are_migratable() -> None:
    legacy_path = (
        "Product/FuturesContract/CNFuturesContract/"
        "日夜盘×行业/(日盘×农产品)"
    )

    assert infer_category_ids([legacy_path]) == [COMPOSITE_ID]
    canonical = canonicalize_product_paths([legacy_path])
    assert len(canonical) > 1
    assert all("日夜盘×行业" not in path for path in canonical)


def test_user_category_and_composite_are_persisted_and_resolvable(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()

    custom = create_product_category(
        "alice",
        "我的分类",
        [{
            "label": "硅",
            "paths": ["Product/Futures/CNFutures/_products/SI.GFE"],
        }],
    )
    composite = create_product_category_composition(
        "alice", [DAY_NIGHT_ID, custom["id"]],
    )

    assert custom["source_managed"] is False
    assert composite["is_composite"] is True
    assert set(composite["parent_category_ids"]) == {DAY_NIGHT_ID, custom["id"]}
    assert composite["id"] == "×".join(sorted([DAY_NIGHT_ID, custom["id"]]))
    assert all(
        item["label_id"].startswith(f"{composite['id']}_")
        for item in composite.get("items") or []
    )
    tree = category_tree(composite["id"], "alice")
    assert tree
    category_node = tree[next(iter(tree))][composite["title_zh"]]
    assert any(
        isinstance(value, dict) and value.get("$OBJECTS$")
        for value in category_node.values()
    )


def test_classifier_node_infers_the_server_data_source_bundle(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()

    assert source_ids_for_product_paths(["Product/Futures"]) == ()
    assert source_ids_for_product_paths(["Product/Futures/CNFutures"]) == ("Local",)
    assert source_ids_for_product_paths(
        ["Product/Futures/CNFutures"],
        [{"id": "user:bundle", "product_paths": ["Product/Futures/CNFutures"]}],
    ) == ("user:bundle",)
    category = create_product_category(
        "alice", "TestA", [{
            "label": "CNFutures",
            "paths": ["Product/Futures/CNFutures"],
        }],
    )

    assert category["source_ids"] == ["Local"]
    assert category["items"][0]["paths"] == ["Product/Futures/CNFutures"]
    assert product_category_store.get_product_category(
        "alice", category["id"],
    )["source_ids"] == ["Local"]


def test_classifier_nodes_share_one_batched_source_projection() -> None:
    descriptors = [
        {
            "id": "source-a",
            "product_paths": ["Product/Futures/CNFutures"],
        },
        {
            "id": "source-b",
            "product_paths": ["Product/Equity/CNEquity"],
        },
    ]

    assert source_ids_by_product_path([
        "Product/Futures/CNFutures/_products/CA.CZC",
        "Product/Equity/CNEquity/_products/000001.SZ",
        "Product/Options/CNOptions",
    ], descriptors) == {
        "Product/Futures/CNFutures/_products/CA.CZC": ("source-a",),
        "Product/Equity/CNEquity/_products/000001.SZ": ("source-b",),
        "Product/Options/CNOptions": (),
    }


def test_composite_paths_are_a_stored_snapshot_until_explicit_refresh(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    custom = create_product_category(
        "alice", "我的分类", [{"label": "硅", "paths": [
            "Product/Futures/CNFutures/_products/SI.GFE",
        ]}],
    )
    composite = create_product_category_composition(
        "alice", [DAY_NIGHT_ID, custom["id"]],
    )
    assert composite["parent_category_ids"] == sorted([DAY_NIGHT_ID, custom["id"]])
    assert composite["items"]
    original_paths = [item["paths"] for item in composite["items"]]

    update_product_category(
        "alice", custom["id"], "我的分类（已变更）", items=[{
            "label": "硅", "paths": [
                "Product/Futures/CNFutures/_products/SI.GFE",
            ],
        }],
    )
    stored = product_category_store.get_product_category("alice", composite["id"])
    assert [item["paths"] for item in stored["items"]] == original_paths

    refreshed = product_category_store.refresh_product_category_composition(
        "alice", composite["id"],
    )
    assert refreshed["parent_category_ids"] == composite["parent_category_ids"]
    assert refreshed["items"]


def test_user_source_composite_keeps_common_category_object_contract(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    composite = create_product_category_composition(
        "alice", [SECTOR_ID, DAY_NIGHT_ID],
    )
    assert composite["id"] == COMPOSITE_ID
    assert composite["source_managed"] is False
    assert composite["kind"] == "user"
    assert set(composite["parent_category_ids"]) == {DAY_NIGHT_ID, SECTOR_ID}
    assert composite["items"]
    with pytest.raises(ValueError, match="已存在"):
        create_product_category_composition(
            "alice", [DAY_NIGHT_ID, SECTOR_ID],
        )
    stored = product_category_store.get_product_category("alice", COMPOSITE_ID)
    assert stored["source_managed"] is False
    tree = category_tree(COMPOSITE_ID, "alice")
    assert tree


def test_source_and_user_categories_share_one_object_contract(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    custom = create_product_category(
        "alice", "我的分类", [{
            "label": "硅", "paths": [
                "Product/Futures/CNFutures/_products/SI.GFE",
            ],
        }],
    )
    categories = {
        item["id"]: item for item in product_category_store.list_product_categories("alice")
    }
    source = categories[DAY_NIGHT_ID]
    user = categories[custom["id"]]
    common = {
        "id", "alias", "title_zh", "dimensions", "source_ids", "items",
        "composable", "is_composite", "kind", "owner_ref", "source_managed",
        "path_sources",
    }
    assert common <= set(source)
    assert common <= set(user)
    assert source["source_managed"] is True
    assert user["source_managed"] is False
    assert user["id"].startswith("alice:")
    assert user["items"][0]["label_id"] == f"{user['id']}_1"
    assert user["path_sources"]
    assert all("source_ids" in item for item in user["path_sources"])

    with pytest.raises(ValueError, match="由服务器生成"):
        create_product_category(
            "alice", "非法 ID", [{"label": "硅", "paths": [
                "Product/Futures/CNFutures/_products/SI.GFE",
            ]}], category_id="client-chosen",
        )
    with pytest.raises(ValueError, match="Others"):
        create_product_category(
            "alice", "非法保留标签", [{"label": "Others", "paths": [
                "Product/Futures/CNFutures/_products/SI.GFE",
            ]}],
        )
    with pytest.raises(ValueError, match="不可修改"):
        update_product_category(
            "alice", user["id"], "新标题", new_category_id="new-id",
        )
    with pytest.raises(PermissionError):
        update_product_category("alice", DAY_NIGHT_ID, "非法标题")
    updated = update_product_category(
        "alice", DAY_NIGHT_ID, "中国期货日夜盘（自定义标题）",
        is_super_admin=True,
    )
    assert updated["id"] == DAY_NIGHT_ID
    assert updated["title_zh"] == "中国期货日夜盘（自定义标题）"


def test_source_categories_keep_fixed_ids_titles_and_label_ids(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    categories = {
        item["id"]: item
        for item in product_category_store.list_product_categories("alice")
    }
    day_night = categories[DAY_NIGHT_ID]
    sector = categories[SECTOR_ID]
    assert day_night["title_zh"] == "中国期货日夜盘"
    assert sector["title_zh"] == "中国期货行业"
    assert day_night["source_managed"] is True
    assert sector["source_managed"] is True
    assert [item["label_id"] for item in day_night["items"]] == [
        f"{DAY_NIGHT_ID}_{index}"
        for index in range(1, len(day_night["items"]) + 1)
    ]
    assert [item["label_id"] for item in sector["items"]] == [
        f"{SECTOR_ID}_{index}"
        for index in range(1, len(sector["items"]) + 1)
    ]


def test_source_category_items_store_concrete_positive_paths() -> None:
    for category_id in (DAY_NIGHT_ID, SECTOR_ID):
        items = source_category_items(category_id)
        assert items
        paths = [path for item in items for path in item["paths"]]
        assert paths
        assert all(path.startswith("Product/") for path in paths)
        assert all("/_products/" in path for path in paths)
        assert all(not path.startswith("-") for path in paths)
        assert all("ProductCategory/" not in path for path in paths)
        assert all("/日夜盘/" not in path and "/行业/" not in path for path in paths)


def test_product_category_rejects_signed_or_category_qualified_paths(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    with pytest.raises(ValueError, match="正产品路径"):
        create_product_category(
            "alice", "负路径分类", [{"label": "日盘", "paths": [
                "-Product/Futures/CNFutures/_products/SI.GFE",
            ]}],
        )
    with pytest.raises(ValueError, match="不能引用"):
        create_product_category(
            "alice", "引用分类", [{"label": "日盘", "paths": [
                f"ProductCategory/{DAY_NIGHT_ID}/Product/Futures/CNFutures/_products/SI.GFE",
            ]}],
        )


def test_generated_others_is_read_only_and_rebuilt_on_save() -> None:
    existing = [
        {"label": "显式标签", "paths": ["Product/Futures/CNFutures/_products/AP.CZC"]},
        {
            "label": "Others",
            "paths": ["stale-path"],
            "label_generated": True,
        },
    ]
    with pytest.raises(ValueError, match="Others"):
        normalize_composite_label_updates([
            existing[0],
            {"label": "改名", "paths": existing[1]["paths"]},
        ], existing)
    with pytest.raises(ValueError, match="产品路径"):
        normalize_composite_label_updates([
            existing[0],
            {"label": "Others", "paths": ["changed-path"]},
        ], existing)
    with pytest.raises(ValueError, match="保留标签"):
        normalize_composite_label_updates([
            {"label": "Others", "paths": existing[0]["paths"]},
            existing[1],
        ], existing)

    rebuilt = regenerate_generated_others(existing)
    assert rebuilt[-1]["label"] == "Others"
    assert rebuilt[-1]["label_generated"] is True
    assert rebuilt[-1]["paths"]
    assert "stale-path" not in rebuilt[-1]["paths"]
    assert "Product/Futures/CNFutures/_products/AP.CZC" not in rebuilt[-1]["paths"]


def test_product_group_persists_explicit_category_binding(monkeypatch) -> None:
    saved: list[dict] = []
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda _: [])
    monkeypatch.setattr(
        product_group_store,
        "_save_product_groups",
        lambda _username, groups: saved.extend(dict(item) for item in groups),
    )
    monkeypatch.setattr(product_group_store, "_resolve_group_products", lambda paths: [])

    group = product_group_store.create_product_group(
        "alice",
        "日盘组",
        ["Product/Futures/CNFutures/日夜盘/日盘"],
        category_ids=[DAY_NIGHT_ID],
    )

    assert group is not None
    assert group["category_ids"] == [DAY_NIGHT_ID]
    assert all("/日夜盘/" not in path for path in group["paths"])
    assert saved[0]["category_ids"] == [DAY_NIGHT_ID]


def test_category_qualified_path_uses_only_current_fixed_source_id() -> None:
    qualified = (
        f"ProductCategory/{DAY_NIGHT_ID}/"
        "Product/Futures/CNFutures/日夜盘/日盘"
    )
    paths = canonicalize_product_paths(
        [qualified], category_ids=[DAY_NIGHT_ID], infer_legacy_categories=False,
    )
    assert paths
    with pytest.raises(ValueError, match="已登记的产品分类 ID"):
        canonicalize_product_paths(
            [qualified.replace(DAY_NIGHT_ID, "day_night")],
            category_ids=[DAY_NIGHT_ID], infer_legacy_categories=False,
        )


def test_classifier_owned_category_view_path_expands_to_concrete_products() -> None:
    selected = (
        "Product/Futures/CNFutures/ProductCategory/"
        f"{SECTOR_ID}/有色金属"
    )
    paths = canonicalize_product_paths(
        [selected], category_ids=[SECTOR_ID], infer_legacy_categories=False,
    )
    assert paths
    assert all("ProductCategory/" not in path for path in paths)
    assert all(path.startswith("Product/") for path in paths)
