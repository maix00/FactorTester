from __future__ import annotations

from types import SimpleNamespace

from server.modules.single_factor_test.group import _resolve_group_strategy_settings


def test_group_run_resolves_frozen_external_factor_before_registry(monkeypatch) -> None:
    factor = SimpleNamespace(alias="external_momentum")
    selection = SimpleNamespace(selection_id="selection-1", products=())
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda *args, **kwargs: selection,
    )
    monkeypatch.setattr(
        "server.services.external_factor_artifacts.factor_by_alias",
        lambda raw, alias: factor if alias == factor.alias else None,
    )
    monkeypatch.setattr(
        "server.services.factor_registry.factor_from_alias",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("registry must not resolve an attached external factor")
        ),
    )

    settings = _resolve_group_strategy_settings(
        {
            "id": "group-1",
            "name": "external",
            "splitCount": 5,
            "groupIndex": 1,
            "factor_candidate_refs": ["external_momentum"],
            "product_path_selection_id": "selection-1",
        },
        resolved_backtest_settings={"group-1": {}},
        fallback_group_settings={},
        page_uuid="",
            data={
                "factors": [{
                    "factor_ref": "external_momentum",
                    "alias": "external_momentum",
                }],
                "external_factor_artifacts": [{"artifact_id": "external_momentum:abc"}],
            },
        page_factors_dict={},
        selection_cache={},
        username="alice",
    )

    assert settings["factor"] is factor
    assert settings["product_path_selection"] is selection
