from server.modules.shared.factor_tester_runtime import (
    selection_for_product_path_selection,
    selection_from_request,
)
from server.modules.single_factor_test.research_jobs import _execution_payload
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
    assert "data_source_declarations" not in payload["shared"]
    assert "product_selections" not in payload["analyses"]["backtest"]
    assert payload["analyses"]["backtest"]["groups"][0][
        "product_path_selection_id"
    ] == "inline:selection"
    assert "temporary_objects" not in payload["shared"]
    assert "product_path_candidates" not in payload["ui"]["backtest"]


def test_freeze_product_scope_accepts_assisted_group_reference_shape(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "server.modules.products.product_group_store."
        "load_authoritative_product_groups",
        lambda _owner: [{
            "id": "product-group:day", "name": "Day", "paths": ["Product/A"],
        }],
    )
    configuration = {
        "payload": {
            "shared": {"product_selections": {
                "product-group:day": {"paths": ["Product/A"]},
            }},
            "analyses": {"backtest": {"groups": [{
                "id": "group-a",
                "product_path_selection": {"group_ref": "product-group:day"},
            }]}},
            "ui": {},
        },
    }

    frozen = freeze_product_scope(
        configuration, owner="alice", analyses=["backtest"],
    )

    group = frozen["payload"]["analyses"]["backtest"]["groups"][0]
    assert group["product_path_selection_id"] == "product-group:day"
    assert group["product_path_selection"][
        "product_path_selection_id"
    ] == "product-group:day"
    assert group["product_path_selection"]["group_ref"] == "product-group:day"
    assert frozen["payload"]["shared"]["product_selections"][
        "product-group:day"
    ]["paths"] == ["Product/A"]


def test_embedded_product_scope_does_not_reopen_mutable_catalog(monkeypatch) -> None:
    configuration = {
        "payload": {
            "shared": {},
            "analyses": {"ic": {
                "product_path_selection_id": "frozen-a",
                "product_selections": {
                    "frozen-a": {"paths": ["Product/A"]},
                },
            }},
            "ui": {},
        },
    }
    monkeypatch.setattr(
        "server.services.frozen_product_scope._product_group_index",
        lambda _owner: (_ for _ in ()).throw(AssertionError("catalog reopened")),
    )

    frozen = freeze_product_scope(configuration, owner="alice", analyses=["ic"])

    assert frozen["payload"]["shared"]["product_selections"]["frozen-a"][
        "paths"
    ] == ["Product/A"]


def test_catalog_product_group_is_resolved_authoritatively_by_owner(monkeypatch) -> None:
    configuration = {
        "payload": {
            "shared": {},
            "analyses": {"ic": {
                "product_path_selection_id": "product-group:pg-day",
                "product_selections": {
                    "product-group:pg-day": {
                        "product_path_selection_id": "product-group:pg-day",
                        "product_group_template_id": "product-group:pg-day",
                        "source_type": "user_product_group_template",
                        "paths": ["Product/StaleClientPath"],
                    },
                },
            }},
            "ui": {},
        },
    }
    monkeypatch.setattr(
        "server.services.frozen_product_scope._product_group_index",
        lambda owner: {
            "product-group:pg-day": {
                "id": "pg-day",
                "name": "CNFuturesDay",
                "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
                "category_ids": ["cnfutures_day_night"],
            },
        },
    )
    monkeypatch.setattr(
        "server.services.frozen_product_scope._freeze_categories",
        lambda **_kwargs: {},
    )

    frozen = freeze_product_scope(configuration, owner="alice", analyses=["ic"])

    selection = frozen["payload"]["shared"]["product_selections"][
        "product-group:pg-day"
    ]
    assert selection["paths"] == [
        "Product/Futures/CNFutures/_products/AP.CZC",
    ]
    assert selection["label"] == "CNFuturesDay"
    assert selection["origin"] == "catalog"


def test_product_group_index_includes_authoritative_domain_mirror(
    monkeypatch,
) -> None:
    legacy = {
        "id": "pg-day",
        "name": "Stale legacy day group",
        "paths": ["Product/Stale"],
    }
    authoritative = {
        "id": "pg-day",
        "name": "CNFuturesDay",
        "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
    }
    monkeypatch.setattr(
        "server.modules.products.product_group_store.load_product_groups",
        lambda owner: [legacy],
    )

    class _Store:
        def __init__(self, path) -> None:
            pass

        def list_entities(self, **kwargs):
            return [{
                "entity_id": "pg-day",
                "payload": authoritative,
                "deleted": False,
            }]

    monkeypatch.setattr(
        "server.manager.storage.account_domain.local.LocalAccountDomainStore",
        _Store,
    )

    groups = __import__(
        "server.services.frozen_product_scope", fromlist=["_product_group_index"]
    )._product_group_index("alice")

    assert groups["product-group:pg-day"] == authoritative


def test_load_account_domain_product_groups_excludes_tombstones(
    monkeypatch, tmp_path,
) -> None:
    import settings as Settings
    from server.manager.storage.account_domain.local import LocalAccountDomainStore
    from server.modules.products import product_group_store

    database = tmp_path / "account-domain.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", database)
    store = LocalAccountDomainStore(database)
    store.upsert_local(
        principal="alice",
        entity_type="product_group",
        entity_id="pg-live",
        payload={"id": "pg-live", "paths": ["Product/A"]},
        manager_id="test",
    )
    store.upsert_local(
        principal="alice",
        entity_type="product_group",
        entity_id="pg-deleted",
        payload={"id": "pg-deleted", "paths": ["Product/Deleted"]},
        manager_id="test",
        deleted=True,
    )
    store.upsert_local(
        principal="bob",
        entity_type="product_group",
        entity_id="pg-other-owner",
        payload={"id": "pg-other-owner", "paths": ["Product/B"]},
        manager_id="test",
    )

    assert product_group_store.load_account_domain_product_groups("alice") == [
        {"id": "pg-live", "paths": ["Product/A"]},
    ]
    monkeypatch.setattr(
        product_group_store, "load_product_groups", lambda owner: [
            {"id": "pg-deleted", "paths": ["Product/StaleLegacy"]},
            {"id": "pg-live", "paths": ["Product/StaleLive"]},
        ],
    )
    assert product_group_store.load_authoritative_product_groups("alice") == [
        {"id": "pg-live", "paths": ["Product/A"]},
    ]


def test_grouped_ic_scope_is_resolved_to_shared_owner_authority(monkeypatch) -> None:
    configuration = {
        "payload": {
            "shared": {},
            "analyses": {"ic": {
                "schema_version": 2,
                "configuration_groups": [{
                    "config_group_id": "icg-day",
                    "batch_id": "icb-day",
                    "factor_ref": "factor:v1:owner:path:roc:commit:blob",
                    "product_scope_ref": "product-group:pg-day",
                    "entry_delay_bars": 0,
                    "horizon": {"sampling": "scale_aware"},
                    "methods": ["rank"],
                    "return_price_basis": "next_open_to_open_adjusted",
                }],
                "product_selections": {
                    "product-group:pg-day": {
                        "product_path_selection_id": "product-group:pg-day",
                        "paths": ["Product/ForgedClientPath"],
                    },
                },
                "execution": {"settings": {}},
            }},
            "ui": {},
        },
    }
    monkeypatch.setattr(
        "server.services.frozen_product_scope._product_group_index",
        lambda owner: {
            "product-group:pg-day": {
                "id": "pg-day",
                "name": "CNFuturesDay",
                "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
            },
        },
    )

    frozen = freeze_product_scope(configuration, owner="alice", analyses=["ic"])
    payload = frozen["payload"]

    assert payload["analyses"]["ic"]["configuration_groups"][0][
        "product_scope_ref"
    ] == "product-group:pg-day"
    assert "product_selections" not in payload["analyses"]["ic"]
    assert payload["shared"]["product_selections"] == {
        "product-group:pg-day": {
            "id": "product-group:pg-day",
            "label": "CNFuturesDay",
            "paths": ["Product/Futures/CNFutures/_products/AP.CZC"],
            "origin": "catalog",
            "product_group_template_id": "pg-day",
        },
    }


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
                "execution": {"settings": {"factor_mode": "auto"}},
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
    assert payload["analyses"]["backtest"]["execution"]["settings"] == {
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
            "family_ref": "Momentum",
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


def test_ic_frozen_scope_and_settings_have_one_runspec_source(monkeypatch) -> None:
    configuration = {
        "configuration_id": "config-ic",
        "revision": 3,
        "fingerprint": "sha256:config-ic",
        "payload": {
            "schema_version": 1,
            "shared": {"factors": []},
            "analyses": {"ic": {
                "product_path_selection_id": "scope-a",
                "product_selections": {"scope-a": {"paths": ["Product/A"]}},
                "start_date": "2026-01-01",
                "execution": {"settings": {
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-31",
                }},
            }},
            "ui": {"ic": {"settings": {"start_date": "2026-01-01"}}},
        },
    }
    frozen = freeze_product_scope(configuration, owner="alice", analyses=["ic"])
    analysis = frozen["payload"]["analyses"]["ic"]
    assert analysis == {
        "product_path_selection_id": "scope-a",
        "execution": {"settings": {
            "start_date": "2026-01-01", "end_date": "2026-01-31",
        }},
    }
    assert "settings" not in frozen["payload"]["ui"]["ic"]

    execution = _execution_payload(frozen, "ic")
    assert execution["start_date"] == "2026-01-01"
    assert execution["end_date"] == "2026-01-31"
    product = object()
    monkeypatch.setattr(
        "tools.products.product_path_selection.resolve_products_from_paths",
        lambda paths: (paths, [product]),
    )
    selection = selection_from_request(execution, page_uuid="")
    assert selection.selected_paths == ["Product/A"]
    assert selection.products == [product]


def test_frozen_shared_selection_reaches_backtest_runtime(monkeypatch) -> None:
    configuration = {
        "configuration_id": "config-a",
        "revision": 2,
        "fingerprint": "sha256:config-a",
        "payload": {
            "schema_version": 1,
            "shared": {"factor_families": [], "factors": []},
                "analyses": {"backtest": {
                    "execution": {"settings": {}},
                    "groups": [{"product_path_selection_id": "scope-a"}],
                "product_selections": {
                    "scope-a": {"paths": ["Product/A"]}
                },
            }},
            "ui": {},
        },
    }
    frozen = freeze_product_scope(
        configuration, owner="alice", analyses=["backtest"]
    )
    execution = _execution_payload(frozen, "backtest")
    product = object()
    monkeypatch.setattr(
        "tools.products.product_path_selection.resolve_products_from_paths",
        lambda paths: (paths, [product]),
    )

    selection = selection_for_product_path_selection(
        execution, "scope-a", page_uuid=""
    )

    assert selection.selected_paths == ["Product/A"]
    assert selection.products == [product]


def test_execution_excludes_unselected_incomplete_temporary_factor():
    from tools.factors.formula_identity import freeze_factor_identity
    def factor(name, params=None):
        return freeze_factor_identity(
            owner_ref='principal:alice', family_alias=name, factor_alias=name,
            family_formula_fingerprint='a' * 64,
            self_formula_fingerprint=('b' if name == 'Parent' else 'c') * 64,
            params=params or {},
        )
    child = {**factor('Child'), 'temporary': True, 'source_kind': 'transient',
             'source_code': 'class Child: pass'}
    parent = factor('Parent', {'P': child['ref']})
    unused = {**factor('Unused'), 'ref': 'factor:v2:unused',
              'temporary': True, 'source_kind': 'transient'}
    configuration = {'payload': {'shared': {
        'factors': [parent], 'temporary_objects': {'factors': [unused, child]},
    }, 'analyses': {'ic': {}}, 'ui': {}}}
    frozen = freeze_product_scope(configuration, owner='alice', analyses=['ic'])
    records = frozen['payload']['shared']['factors']
    assert {record['ref'] for record in records} == {parent['ref'], child['ref']}
    assert next(item for item in records if item['ref'] == child['ref'])['source_code']
    assert len(configuration['payload']['shared']['temporary_objects']['factors']) == 2

    # Missing source on a dependency is still an error, never silently skipped.
    import pytest
    child.pop('source_code')
    with pytest.raises(ValueError, match='缺少冻结源码'):
        freeze_product_scope(configuration, owner='alice', analyses=['ic'])
