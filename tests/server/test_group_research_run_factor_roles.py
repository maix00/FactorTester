from __future__ import annotations

from types import SimpleNamespace

from tools.factors.tester_calc.single_factor_test.group.research_run import settings


def test_delegated_factor_alias_uses_frozen_source_owner(monkeypatch) -> None:
    selected = SimpleNamespace(selection_id="selection-1", products=())
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda *args, **kwargs: selected,
    )
    captured: list[str] = []
    factor = object()

    def resolve(alias, **kwargs):
        captured.append(alias)
        return factor

    monkeypatch.setattr("server.services.factor_registry.factor_from_alias", resolve)

    settings.resolve_group_strategy_settings(
        {
            "id": "group-1",
            "product_path_selection_id": "selection-1",
            "factor_candidate_refs": ["factor:v1:ca"],
            "splitCount": 5,
            "groupIndex": 1,
        },
        resolved_backtest_settings={"group-1": {}},
        fallback_group_settings={},
        page_uuid="",
        data={
            "factors": [{
                "alias": "CA|$F:1m",
                "factor_ref": "factor:v1:ca",
                "factor_family_alias": "CA",
                "factor_family_ref": "CA",
                "factor_owner_ref": "GTHT@MaxJJW@392452984564",
            }],
        },
        page_factors_dict={},
        selection_cache={},
        username="GTHT@testA@545963541963",
    )

    assert captured == ["GTHT@MaxJJW@392452984564:CA|$F:1m"]


def test_unowned_factor_alias_keeps_short_public_resolution(monkeypatch) -> None:
    selected = SimpleNamespace(selection_id="selection-1", products=())
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda *args, **kwargs: selected,
    )
    captured: list[str] = []

    monkeypatch.setattr(
        "server.services.factor_registry.factor_from_alias",
        lambda alias, **kwargs: captured.append(alias) or object(),
    )

    settings.resolve_group_strategy_settings(
        {
            "id": "group-1",
            "product_path_selection_id": "selection-1",
            "factor_candidate_refs": ["factor:v1:mmret"],
            "splitCount": 5,
            "groupIndex": 1,
        },
        resolved_backtest_settings={"group-1": {}},
        fallback_group_settings={},
        page_uuid="",
        data={"factors": [{
                "alias": "MmRet|P:CA|N:10d|$F:1d",
                "factor_ref": "factor:v1:mmret",
            "factor_family_alias": "MmRet",
        }]},
        page_factors_dict={},
        selection_cache={},
        username="GTHT@testA@545963541963",
    )

    assert captured == ["MmRet|P:CA|N:10d|$F:1d"]
