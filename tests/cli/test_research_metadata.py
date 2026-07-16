from __future__ import annotations

from math import isclose
from types import SimpleNamespace

from tools.cli.modules.backtest.controller import _save_backtest_research_result
from tools.cli.modules.ic_test.controller import _save_ic_research_result
from tools.cli.modules.research_metadata import attach_research_metadata, research_metadata_from_settings


class _Client:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def save_factor_research_run(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"run": payload}


def test_research_metadata_from_nested_and_flat_sources():
    meta = research_metadata_from_settings(
        {"research_meta": {"sample_role": "is", "grid_size": 12}},
        {"sample_role": "oos", "regime_label": "trend", "costed_pass": True},
    )

    assert meta == {
        "sample_role": "oos",
        "grid_size": 12,
        "regime_label": "trend",
        "costed_pass": True,
    }


def test_attach_research_metadata_adds_query_fields_and_audit_metrics():
    payload = {"config": {"settings": {}}, "metrics": {"ic_mean": 0.1}}

    attach_research_metadata(
        payload,
        settings={"sample_role": "oos", "regime_label": "low-vol"},
        extra={"research_meta": {"slice_name": "2026-q1", "test_count": 5}},
    )

    assert payload["sample_role"] == "oos"
    assert payload["regime_label"] == "low-vol"
    assert payload["slice_name"] == "2026-q1"
    assert payload["config"]["research_meta"]["test_count"] == 5
    assert payload["metrics"]["test_count"] == 5
    assert payload["metrics"]["ic_mean"] == 0.1


def test_ic_auto_save_attaches_research_metadata():
    client = _Client()
    state = SimpleNamespace(factor_family="SgCCS", page_settings={"factor_source": "custom"})
    item = {"factor": "SgCCS|N:2m", "product_group": "core8"}
    payload = {
        "settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "sample_role": "oos",
            "regime_label": "shock",
        },
        "grid_size": 3,
    }
    summary = {"mean": 0.02, "t_stat": 2.5}

    _save_ic_research_result(client, state, item, payload, {"factors": []}, summary)

    saved = client.payloads[0]
    assert saved["sample_role"] == "oos"
    assert saved["regime_label"] == "shock"
    assert saved["config"]["research_meta"]["grid_size"] == 3
    assert saved["metrics"]["grid_size"] == 3
    assert saved["metrics"]["ic_mean"] == 0.02


def test_backtest_auto_save_attaches_research_metadata():
    client = _Client()
    state = SimpleNamespace(factor_family="SgCCS", page_settings={"factor_source": "custom"})
    run_payload = {
        "local_settings": {
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "sample_role": "is",
            "slice_name": "jan",
        },
        "research_meta": {"costed_pass": False, "multi_product_group_pass": True},
        "groups": [
            {
                "factorAlias": "SgCCS|N:2m",
                "shortAlias": "A1",
                "product_path_selection": {"label": "core8"},
            }
        ],
    }
    result = {"groups": [{"name": "A1", "total_equity": [100.0, 110.0]}]}

    _save_backtest_research_result(client, state, run_payload, result)

    saved = client.payloads[0]
    assert saved["sample_role"] == "is"
    assert saved["slice_name"] == "jan"
    assert saved["config"]["research_meta"]["costed_pass"] is False
    assert saved["metrics"]["multi_product_group_pass"] is True
    assert isclose(saved["metrics"]["a1_return"], 0.1)
