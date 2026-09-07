from server.modules.products import product_candidate_scope as scope


def test_mixed_group_and_manual_candidates_are_unioned_then_category_filtered(monkeypatch):
    monkeypatch.setattr(scope, "load_authoritative_product_groups", lambda owner: [
        {"id": "g", "paths": ["definition"], "category_ids": []},
    ])
    monkeypatch.setattr(scope, "resolve_product_scope_paths", lambda *a, **k: ["A", "B"])
    monkeypatch.setattr(scope, "category_tree", lambda *a: ["A", "C"])
    monkeypatch.setattr(scope, "_collect_products_from_node", lambda node: node)
    monkeypatch.setattr(scope, "classifier_object_path", lambda product: product)
    rows = [{"product_path": name} for name in "ABCD"]
    assert scope.constrain_product_records(
        rows, username="alice", category_ids=["category"],
        group_refs=["product-group:g"], product_paths=["C"],
    ) == [rows[0], rows[2]]


def test_explicit_products_cannot_introduce_invisible_catalog_rows():
    assert scope.constrain_product_records(
        [{"product_path": "A"}], username="alice", product_paths=["invisible"],
    ) == []
