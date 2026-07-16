from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools.cli.modules.single_factor_analysis_shared import (
    factor_grid_items,
    grid_param_combinations,
    parse_factor_grid_options,
)


class DummyClient:
    def __init__(self) -> None:
        self.added: list[dict] = []

    def list_candidates(self, key: str):
        assert key == "product_path_candidates"
        return [
            {
                "id": "pg-test",
                "product_path_selection_id": "pg-test",
                "name": "core",
                "label": "core",
                "paths": ["Product/Futures/CNFutures/日夜盘/日盘/_products/AP.CZC"],
            }
        ]

    def add_candidate(self, key: str, payload: dict):
        assert key == "factor"
        self.added.append(payload)
        params = payload["params"]
        ordered = [key for key in ("C", "M", "N", "W", "$F", "$Rev") if key in params]
        return {"factor_alias": payload["factor_family_alias"] + "|" + "|".join(
            key if key == "$Rev" and str(params[key]) == "1" else f"{key}:{params[key]}"
            for key in ordered
        )}


def _state():
    return SimpleNamespace(
        page_uuid="page-1",
        page_settings={},
        backtest_groups=[],
        backtest_local_settings={"start_date": "2025-01-02", "end_date": "2025-01-10"},
        ic_test_local_settings={"start_date": "2024-01-02", "end_date": "2025-12-31"},
        factor_type_analysis_local_settings={},
        factor_evaluation_local_settings={"start_date": "2025-03-01", "end_date": "2025-03-31"},
    )


def test_parse_factor_grid_options_supports_generic_factor_params():
    options = parse_factor_grid_options(
        (
            "--factor-family",
            "TrCCSBlend",
            "--product-group",
            "core",
            "--param",
            "M=1d",
            "--param",
            "M=3d",
            "--param",
            "C=30m",
            "--f",
            "1d",
            "--no-rev",
        )
    )

    assert options["factor_family"] == "TrCCSBlend"
    assert options["product_group"] == ["core"]
    assert options["params"] == {"M": ["1d", "3d"], "C": ["30m"], "$F": ["1d"]}
    assert options["rev"] == [False]


def test_parse_factor_grid_options_rejects_private_param_shortcuts():
    with pytest.raises(Exception, match="无法识别 grid 参数"):
        parse_factor_grid_options(
            ("--factor-family", "TrCCSBlend", "--product-group", "core", "--m", "1d")
        )


def test_parse_factor_grid_options_rejects_n_shortcut():
    with pytest.raises(Exception, match="无法识别 grid 参数"):
        parse_factor_grid_options(
            ("--factor-family", "SgCCS", "--product-group", "core", "--n", "2m")
        )


def test_parse_factor_grid_options_supports_param_assignments():
    options = parse_factor_grid_options(("--factor-family", "TrCCSSmooth", "--param", "W=0.25", "--param", "C=30m", "--f", "1d"))

    assert options["params"] == {"W": ["0.25"], "C": ["30m"], "$F": ["1d"]}


def test_parse_factor_grid_options_defaults_only_factor_frequency():
    options = parse_factor_grid_options(("--factor-family", "NoParamFactor", "--product-group", "core"))

    assert options["params"] == {"$F": ["1m"]}


def test_grid_param_combinations_preserves_param_keys():
    assert grid_param_combinations({"M": ["1d", "3d"], "C": ["30m"], "$F": ["1d"]}) == [
        {"M": "1d", "C": "30m", "$F": "1d"},
        {"M": "3d", "C": "30m", "$F": "1d"},
    ]


def test_factor_grid_items_current_settings_override_shared_time_sources():
    state = _state()
    client = DummyClient()
    options = parse_factor_grid_options(
        ("--factor-family", "TrCCSBlend", "--product-group", "core", "--param", "M=1d", "--param", "C=30m", "--f", "1d")
    )

    items = factor_grid_items(
        state,
        options=options,
        settings=state.ic_test_local_settings,
        client=client,
    )

    assert [item["factor"] for item in items] == ["TrCCSBlend|C:30m|M:1d|$F:1d|$Rev"]
    assert items[0]["settings"]["start_date"] == "2024-01-02"
    assert items[0]["settings"]["end_date"] == "2025-12-31"
    assert items[0]["settings"]["factor_selections"] == [
        {
            "factor_alias": "TrCCSBlend|C:30m|M:1d|$F:1d|$Rev",
            "alias": "TrCCSBlend|C:30m|M:1d|$F:1d|$Rev",
            "params": {"C": "30m", "M": "1d", "$F": "1d", "$Rev": "1"},
        }
    ]
    assert client.added[0]["params"] == {"M": "1d", "C": "30m", "$F": "1d", "$Rev": "1"}
