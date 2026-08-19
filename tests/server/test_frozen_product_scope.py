from server.services.frozen_product_scope import freeze_product_scope


def test_freeze_product_scope_moves_reusable_objects_to_shared() -> None:
    configuration = {
        "payload": {
            "schema_version": 1,
            "shared": {
                "factor_families": [],
                "factors": [],
                "temporary_objects": {
                    "product_categories": {
                        "inline:session": {
                            "id": "inline:session",
                            "title_zh": "日夜盘",
                            "source_ids": ["LocalMIN1"],
                            "items": [{"label": "日盘", "paths": ["Product/A"]}],
                        }
                    },
                    "data_source_declarations": {
                        "LocalMIN1": {
                            "id": "LocalMIN1",
                            "frequency": "MIN1",
                            "mapping_revision": "sha256:mapping",
                        }
                    },
                },
            },
            "analyses": {
                "backtest": {
                    "groups": [{
                        "id": "group-a",
                        "product_path_selection_id": "inline:selection",
                    }],
                    "product_selections": {
                        "inline:selection": {
                            "product_path_selection_id": "inline:selection",
                            "label": "日盘组合",
                            "paths": ["Product/A"],
                            "selected_paths": ["Product/A"],
                            "category_ids": ["inline:session"],
                            "origin": "inline",
                        }
                    },
                }
            },
            "ui": {"backtest": {"product_path_candidates": [{"id": "catalog"}]}},
        }
    }

    frozen = freeze_product_scope(configuration, owner="alice", analyses=["backtest"])
    payload = frozen["payload"]

    assert payload["shared"]["product_selections"] == {
        "inline:selection": {
            "id": "inline:selection",
            "label": "日盘组合",
            "paths": ["Product/A"],
            "category_ids": ["inline:session"],
            "origin": "inline",
        }
    }
    assert payload["shared"]["product_categories"]["inline:session"]["items"] == [
        {"label": "日盘", "paths": ["Product/A"]}
    ]
    assert payload["shared"]["data_source_declarations"] == {
        "LocalMIN1": {
            "id": "LocalMIN1",
            "frequency": "MIN1",
            "mapping_revision": "sha256:mapping",
        }
    }
    assert "product_selections" not in payload["analyses"]["backtest"]
    assert payload["analyses"]["backtest"]["groups"][0][
        "product_path_selection_id"
    ] == "inline:selection"
    assert "temporary_objects" not in payload["shared"]
    assert "product_path_candidates" not in payload["ui"]["backtest"]


def test_freeze_product_scope_removes_repeated_execution_projections() -> None:
    configuration = {
        "payload": {
            "schema_version": 1,
            "shared": {
                "factor_families": [{"alias": "Momentum"}],
                "factors": [{
                    "alias": "Momentum|N:20",
                    "factor_family_alias": "Momentum",
                    "factor_owner_ref": "alice",
                    "owner_ref": "alice",
                    "factor_family_ref": "Momentum",
                    "family_ref": "Momentum",
                    "factor_params": [{"alias": "N", "value": 20}],
                    "params": [{"alias": "N", "value": 20}],
                }],
            },
            "analyses": {"backtest": {
                "factor_mode": "auto",
                "local_settings": {"factor_mode": "auto"},
                "groups": [{
                    "id": "group-a",
                    "factorAlias": "Momentum|N:20",
                    "factorAliases": ["Momentum|N:20"],
                }],
            }},
            "ui": {"backtest": {
                "mounted_tabs": ["factor"],
                "settings": {"factor_mode": "auto"},
            }},
        }
    }

    payload = freeze_product_scope(
        configuration, owner="alice", analyses=["backtest"]
    )["payload"]

    assert "factor_mode" not in payload["analyses"]["backtest"]
    assert payload["analyses"]["backtest"]["local_settings"] == {
        "factor_mode": "auto"
    }
    assert "settings" not in payload["ui"]["backtest"]
    assert payload["ui"]["backtest"]["mounted_tabs"] == ["factor"]
    assert "factorAlias" not in payload["analyses"]["backtest"]["groups"][0]
    assert payload["shared"]["factors"][0] == {
        "alias": "Momentum|N:20",
        "factor_family_alias": "Momentum",
        "factor_owner_ref": "alice",
        "factor_family_ref": "Momentum",
        "factor_params": [{"alias": "N", "value": 20}],
    }


def test_freeze_product_scope_is_shared_by_ic_and_backtest() -> None:
    configuration = {
        "payload": {
            "schema_version": 1,
            "shared": {"factor_families": [], "factors": []},
            "analyses": {
                "ic": {
                    "product_path_selection_id": "scope-a",
                    "product_selections": {
                        "scope-a": {"paths": ["Product/A"]}
                    },
                },
                "backtest": {
                    "groups": [{"product_path_selection_id": "scope-a"}]
                },
            },
            "ui": {},
        }
    }

    payload = freeze_product_scope(
        configuration, owner="alice", analyses=["ic", "backtest"]
    )["payload"]

    assert payload["shared"]["product_selections"]["scope-a"]["paths"] == [
        "Product/A"
    ]
    assert "product_selections" not in payload["analyses"]["ic"]
    assert payload["analyses"]["ic"]["product_path_selection_id"] == "scope-a"
