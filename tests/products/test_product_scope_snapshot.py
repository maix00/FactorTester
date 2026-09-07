"""Definitions stay dynamic; submitted product identities do not."""

import settings as Settings

from server.modules.products.product_category_store import create_product_category, update_product_category
from server.modules.products.product_group_store import create_product_group, load_product_groups
from server.services.frozen_product_scope import freeze_product_scope
from tools.data.sqlite.account_manager.product_group import load_product_groups as stored_groups


def test_category_drift_changes_next_submission_not_stored_group_or_old_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    first = "Product/Futures/CNFutures/_products/AP.CZC"
    second = "Product/Futures/CNFutures/_products/SI.GFE"
    category = create_product_category("alice", "Scope drift", [
        {"label": "members", "paths": [first]},
    ])
    label = category["items"][0]["label_id"]
    path = f"Product/Futures/CNFutures/ProductCategory/{category['id']}/{label}"
    group = create_product_group("alice", "Dynamic scope", [path], category_ids=[category["id"]])
    ref = f"product-group:{group['id']}"
    configuration = {"payload": {"shared": {}, "analyses": {
        "ic": {"configuration_groups": [{"product_scope_ref": ref}]},
    }}}
    old = freeze_product_scope(configuration, owner="alice", analyses=["ic"])
    assert old["payload"]["shared"]["product_selections"][ref]["paths"] == [first]
    update_product_category("alice", category["id"], "Scope drift", [
        {"label": "members", "label_id": label, "paths": [first, second]},
    ])
    new = freeze_product_scope(configuration, owner="alice", analyses=["ic"])
    assert new["payload"]["shared"]["product_selections"][ref]["paths"] == [first, second]
    assert old["payload"]["shared"]["product_selections"][ref]["paths"] == [first]
    assert stored_groups("alice")[0]["paths"] == [path]
    assert "product_names" not in stored_groups("alice")[0]
    assert load_product_groups("alice")[0]["paths"] == [path]


def test_signed_category_rules_resolve_to_exact_leaves(monkeypatch, tmp_path):
    from server.modules.products.product_category_paths import resolve_product_scope_paths
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    first = "Product/Futures/CNFutures/_products/AP.CZC"
    second = "Product/Futures/CNFutures/_products/SI.GFE"
    category = create_product_category("alice", "Signed scope", [
        {"label": "include", "paths": [first, second]},
        {"label": "exclude", "paths": [second]},
    ])
    labels = {item["label"]: item["label_id"] for item in category["items"]}
    prefix = f"Product/Futures/CNFutures/ProductCategory/{category['id']}/"
    paths = [prefix + labels["include"], "-" + prefix + labels["exclude"]]
    group = create_product_group("alice", "Signed", paths, category_ids=[category["id"]])
    assert group["paths"] == paths
    assert resolve_product_scope_paths(paths, username="alice", category_ids=[category["id"]]) == [first]


def test_definition_rejects_unbound_category_without_expanding_members(monkeypatch, tmp_path):
    import pytest
    from server.modules.products import product_category_paths
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    category = create_product_category("alice", "Unbound", [
        {"label": "members", "paths": ["Product/Futures/CNFutures/_products/AP.CZC"]},
    ])
    path = f"Product/Futures/CNFutures/ProductCategory/{category['id']}/{category['items'][0]['label_id']}"
    def reject_expansion(*args, **kwargs):
        raise AssertionError("Saving a category reference must not expand its members")
    monkeypatch.setattr(product_category_paths, "_category_members", reject_expansion)
    for sign in ("", "-"):
        with pytest.raises(ValueError, match="未绑定到当前定义"):
            create_product_group("alice", "Invalid", [sign + path], category_ids=["cnfutures_day_night"])
    assert stored_groups("alice") == []


def test_submission_resolves_inline_category_without_registering_it(monkeypatch, tmp_path):
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "account.sqlite")
    first = "Product/Futures/CNFutures/_products/AP.CZC"
    second = "Product/Futures/CNFutures/_products/SI.GFE"
    category = {"id": "inline:category", "title_zh": "Inline", "items": [
        {"label_id": "members", "label": "Members", "paths": [first, second]},
        {"label_id": "excluded", "label": "Excluded", "paths": [second]},
    ]}
    prefix = "Product/Futures/CNFutures/ProductCategory/inline:category/"
    configuration = {"payload": {"shared": {
        "temporary_objects": {"product_categories": {category["id"]: category}},
        "product_selections": {"inline:selection": {
            "id": "inline:selection", "origin": "inline",
            "category_ids": [category["id"]],
            "paths": [prefix + "members", "-" + prefix + "excluded"],
        }},
    }, "analyses": {"ic": {"configuration_groups": [
        {"product_scope_ref": "inline:selection"},
    ]}}}}
    frozen = freeze_product_scope(configuration, owner="alice", analyses=["ic"])
    shared = frozen["payload"]["shared"]
    assert shared["product_selections"]["inline:selection"]["paths"] == [first]
    assert shared["product_categories"][category["id"]]["items"] == category["items"]
    assert stored_groups("alice") == []
