from __future__ import annotations

import pytest

from server.jobs.run_input_dependencies import (
    dependency_input_bytes,
    source_free_manifest,
    validate_entries,
)


def test_run_input_dependencies_are_bounded_text_files() -> None:
    values = validate_entries([
        {
            "path": "strategy-configs/dynamic-hold.yaml",
            "content": "target_leverage: 0.4\n",
            "title_zh": "动态持仓参数",
            "purpose": "strategy_configuration",
            "analyses": ["backtest"],
        },
        {
            "path": "mappings/session.csv",
            "content": "product,session\nSI.GFE,day\n",
            "purpose": "data_mapping",
            "analyses": ["backtest", "ic"],
        },
    ], analyses=["backtest", "ic"])

    assert values[0]["content_type"] == "application/yaml"
    assert values[0]["source_bytes"] == len(
        values[0]["content"].encode("utf-8")
    )
    assert values[1]["analyses"] == ["backtest", "ic"]
    assert dependency_input_bytes(values, analysis="backtest") > 0
    assert dependency_input_bytes(values, analysis="ic") == len(
        values[1]["content"].encode("utf-8")
    )
    manifest = source_free_manifest(values)
    assert all("content" not in item for item in manifest)
    assert manifest[0]["source_sha256"] == values[0]["source_sha256"]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"path": "../secret.txt", "content": "x"}, "relative"),
        ({"path": "/tmp/secret.txt", "content": "x"}, "relative"),
        ({"path": "config.exe", "content": "x"}, "supported text"),
        ({"path": "config.json", "content": ""}, "empty"),
        (
            {
                "path": "config.json",
                "content": "{}",
                "analyses": ["unknown"],
            },
            "analysis",
        ),
    ],
)
def test_run_input_dependencies_reject_unsafe_entries(
    entry: dict[str, object], message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_entries([entry], analyses=["backtest"])
