from __future__ import annotations

from types import SimpleNamespace

from tools.factors.tester_calc.single_factor_test.group.research_run import settings
from tools.factors.formula_identity import freeze_factor_identity


def _factor(alias: str, *, owner: str) -> dict:
    return freeze_factor_identity(
        owner_ref=owner,
        family_alias=alias.split("|", 1)[0],
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={},
    )


def test_delegated_factor_alias_uses_frozen_source_owner(monkeypatch) -> None:
    selected = SimpleNamespace(selection_id="selection-1", products=())
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda *args, **kwargs: selected,
    )
    captured: list[tuple[str, str]] = []
    factor = object()

    def resolve(record, **kwargs):
        captured.append((record["alias"], kwargs["username"]))
        return factor

    monkeypatch.setattr(
        "server.modules.shared.factor_param_resolver.resolve_factor_param_value",
        resolve,
    )

    frozen = _factor(
        "CA|$F:1m", owner="GTHT@MaxJJW@392452984564",
    )
    settings.resolve_group_strategy_settings(
        {
            "id": "group-1",
            "product_path_selection_id": "selection-1",
            "factor_candidate_refs": [frozen["ref"]],
            "splitCount": 5,
            "groupIndex": 1,
        },
        resolved_backtest_settings={"group-1": {}},
        fallback_group_settings={},
        page_uuid="",
        data={
            "factors": [frozen],
        },
        page_factors_dict={},
        selection_cache={},
        username="GTHT@testA@545963541963",
    )

    assert captured == [("CA|$F:1m", "GTHT@MaxJJW@392452984564")]


def test_unowned_factor_alias_keeps_short_public_resolution(monkeypatch) -> None:
    selected = SimpleNamespace(selection_id="selection-1", products=())
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda *args, **kwargs: selected,
    )
    captured: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "server.modules.shared.factor_param_resolver.resolve_factor_param_value",
        lambda record, **kwargs: captured.append(
            (record["alias"], kwargs["username"]),
        ) or object(),
    )

    frozen = _factor("MmRet|P:CA|N:10d|$F:1d", owner="public")
    settings.resolve_group_strategy_settings(
        {
            "id": "group-1",
            "product_path_selection_id": "selection-1",
            "factor_candidate_refs": [frozen["ref"]],
            "splitCount": 5,
            "groupIndex": 1,
        },
        resolved_backtest_settings={"group-1": {}},
        fallback_group_settings={},
        page_uuid="",
        data={"factors": [frozen]},
        page_factors_dict={},
        selection_cache={},
        username="GTHT@testA@545963541963",
    )

    assert captured == [("MmRet|P:CA|N:10d|$F:1d", "public")]
