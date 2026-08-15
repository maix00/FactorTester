from __future__ import annotations

import importlib

import settings as Settings
import pytest

from server.modules.products.product_category_paths import (
    canonicalize_product_paths,
    category_tree,
    infer_category_ids,
)
from server.modules.products.product_category_store import (
    create_product_category,
    create_product_category_composition,
)
from server.modules.products import product_group_store
from server.modules.shared import price_services
from server.modules.products import product_category_paths
from tools.data.sqlite.account_manager import ensure_account_manager_sqlite_store


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
        category_ids=["day_night"],
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

    assert infer_category_ids([legacy_path]) == ["day_night_x_sector"]
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
        "alice", ["day_night", custom["id"]],
    )

    assert custom["source_managed"] is False
    assert composite["is_composite"] is True
    assert set(composite["parent_category_ids"]) == {"day_night", custom["id"]}
    tree = category_tree(composite["id"], "alice")
    assert tree
    category_node = tree[next(iter(tree))][composite["title_zh"]]
    assert any(
        isinstance(value, dict) and value.get("$OBJECTS$")
        for value in category_node.values()
    )


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
        category_ids=["day_night"],
    )

    assert group is not None
    assert group["category_ids"] == ["day_night"]
    assert all("/日夜盘/" not in path for path in group["paths"])
    assert saved[0]["category_ids"] == ["day_night"]
