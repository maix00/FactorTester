from __future__ import annotations

from pathlib import Path

import settings as Settings
import pytest

from server.modules.products import product_category_store, product_group_store
from server.modules.products.product_category_definition import source_category_items
from server.modules.products.product_category_paths import (
    normalize_category_selection_paths,
)
from tools.data.sqlite.account_manager import ensure_account_manager_sqlite_store


DAY_NIGHT_ID = "cnfutures_day_night"


def test_category_title_and_label_title_are_stored_as_ids(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    ensure_account_manager_sqlite_store()
    monkeypatch.setattr(product_group_store, "_resolve_group_products", lambda _: [])

    day_night = next(
        item for item in source_category_items(DAY_NIGHT_ID)
        if item["label"] == "日盘"
    )
    title_path = (
        "Product/Futures/CNFutures/ProductCategory/"
        "中国期货日夜盘/日盘"
    )
    normalized = normalize_category_selection_paths([title_path])
    assert normalized == [
        f"Product/Futures/CNFutures/ProductCategory/{DAY_NIGHT_ID}/"
        f"{day_night['label_id']}"
    ]
    group = product_group_store.create_product_group(
        "alice", "日盘组", [title_path], category_ids=[DAY_NIGHT_ID],
    )
    assert group["selection_paths"] == normalized
    assert group["path_bindings"] == [
        {"id": "positive", "label": "正路径", "paths": normalized},
        {"id": "negative", "label": "负路径", "paths": []},
    ]


def test_category_delete_rejects_product_group_reference(monkeypatch) -> None:
    category_id = "alice:category_1"
    monkeypatch.setattr(
        product_category_store,
        "get_product_category",
        lambda _username, _category_id: {
            "id": category_id, "source_managed": False,
        },
    )
    monkeypatch.setattr(
        product_category_store,
        "load_product_categories",
        lambda _username: [{"id": category_id}],
    )
    monkeypatch.setattr(
        product_group_store,
        "_load_product_groups",
        lambda _username: [{
            "id": "pg_1", "name": "引用组", "paths": [],
            "category_ids": [category_id],
        }],
    )
    monkeypatch.setattr(product_group_store, "_save_product_groups", lambda *_: None)

    with pytest.raises(product_category_store.ProductCategoryInUseError) as captured:
        product_category_store.delete_product_category("alice", category_id)

    assert captured.value.status == 409
    assert captured.value.references == [{"id": "pg_1", "name": "引用组"}]


def test_category_delete_succeeds_without_product_group_reference(monkeypatch) -> None:
    category_id = "alice:category_1"
    saved: list[list[dict]] = []
    monkeypatch.setattr(
        product_category_store,
        "get_product_category",
        lambda _username, _category_id: {
            "id": category_id, "source_managed": False,
        },
    )
    monkeypatch.setattr(
        product_category_store,
        "load_product_categories",
        lambda _username: [{"id": category_id}],
    )
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda _: [])
    monkeypatch.setattr(
        product_category_store,
        "save_product_categories",
        lambda _username, values: saved.append(values),
    )

    assert product_category_store.delete_product_category("alice", category_id)
    assert saved == [[]]


def test_product_group_update_renames_and_keeps_two_path_rows(monkeypatch) -> None:
    groups = [{
        "id": "pg_1", "name": "旧组", "paths": ["Product/Futures"],
        "category_ids": [DAY_NIGHT_ID], "product_names": [],
    }]
    saved: list[list[dict]] = []
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda _: groups)
    monkeypatch.setattr(
        product_group_store,
        "_save_product_groups",
        lambda _username, values: saved.append([dict(item) for item in values]),
    )
    monkeypatch.setattr(product_group_store, "_resolve_group_products", lambda _: [])

    updated = product_group_store.update_product_group(
        "alice", "旧组", ["Product/Futures", "-Product/FuturesContract"],
        [DAY_NIGHT_ID], new_name="新组",
    )

    assert updated["name"] == "新组"
    assert [item["id"] for item in updated["path_bindings"]] == [
        "positive", "negative",
    ]
    assert updated["path_bindings"][1]["paths"] == ["Product/FuturesContract"]
    assert saved
