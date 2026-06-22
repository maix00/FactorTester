from server.modules.single_factor_test.group import _groups_with_parent_fallback


def test_derived_group_inherits_missing_parent_settings_for_run_view():
    groups = _groups_with_parent_fallback([
        {
            "id": "parent",
            "testerId": "sel-parent",
            "factorAlias": "FactorA",
            "splitCount": 5,
            "groupIndex": 1,
            "product_path_selection": {
                "product_path_selection_id": "sel-parent",
                "paths": ["Futures/Metals"],
            },
        },
        {
            "id": "child",
            "parentId": "parent",
            "groupIndex": 2,
        },
    ])

    child = groups[1]
    assert child["id"] == "child"
    assert child["parentId"] == "parent"
    assert child["testerId"] == "sel-parent"
    assert child["factorAlias"] == "FactorA"
    assert child["splitCount"] == 5
    assert child["groupIndex"] == 2
    assert child["product_path_selection"]["paths"] == ["Futures/Metals"]
