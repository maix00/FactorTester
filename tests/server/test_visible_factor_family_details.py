from server.modules.custom_factors import catalog


def test_visible_subordinate_family_keeps_formula_and_read_only_source(monkeypatch):
    monkeypatch.setattr(
        catalog, "get_account", lambda username: {"username": username},
    )
    monkeypatch.setattr(
        catalog,
        "direct_subordinate_accounts_for",
        lambda username: [{"username": "child"}] if username == "parent" else [],
    )
    monkeypatch.setattr(catalog, "account_display_name", lambda value: value["username"])
    monkeypatch.setattr(catalog, "list_custom_factors", lambda username: [{
        "id": "Momentum",
        "name": "Momentum",
        "math_expr": r"P_t / P_{t-1} - 1",
        "source_code": "class Momentum(FactorFamily):\n    pass\n",
    }] if username == "child" else [])

    [value] = catalog.list_visible_custom_factors("parent")

    assert value["math_expr"] == r"P_t / P_{t-1} - 1"
    assert "class Momentum" in value["source_code"]
    assert value["source_access"] is True
    assert value["can_edit"] is False
