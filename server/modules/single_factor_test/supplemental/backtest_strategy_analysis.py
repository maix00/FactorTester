"""Lazy backtest strategy-analysis Adapter."""

from __future__ import annotations

import re
from typing import Any

from server.jobs.artifacts import load_json_artifact
from server.jobs.supplemental.registry import SupplementalAdapter, register
from tools.factors.tester_calc.single_factor_test.group.strategy_analysis import (
    build_strategy_analysis_tab,
)


KIND = "backtest_strategy_analysis"
TABS = frozenset({
    "overview", "returns", "membership", "distribution", "rolling",
    "capacity", "tradability", "calendar", "holding", "explanations",
    "products", "daily", "robustness", "periods", "positive_runs",
    "intraday", "ranking",
})


def _token(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-")[:96]


def prepare(repository, parent, params: dict[str, Any]) -> dict[str, Any]:
    tab = str(params.get("analysis_tab") or "overview").strip()
    if tab not in TABS:
        raise ValueError(f"unsupported strategy-analysis tab: {tab}")
    source = repository.load_artifact(
        job_id=parent.job_id, name="strategy_analysis_source", owner=parent.owner,
    )
    if not source or source.get("state") != "active":
        raise LookupError(
            "该任务未保存当前版本的策略分析基础生成物，请重新运行回测"
        )
    strategy_id = str(params.get("strategy_id") or params.get("group_id") or "")
    configuration_id = str(params.get("strategy_configuration_id") or "")
    product_selection_id = str(params.get("product_path_selection_id") or "")
    if tab == "ranking":
        if not configuration_id or not product_selection_id:
            raise ValueError("排序诊断需要策略配置和产品范围身份")
        selector = f"configuration-{_token(configuration_id)}"
    else:
        if not strategy_id:
            raise ValueError("策略分析需要 strategy_id")
        selector = f"strategy-{_token(strategy_id)}"
    artifact_name = f"strategy-analysis--{selector}--{_token(tab)}"
    identity = {
        "version": 1,
        "tab": tab,
        "strategy_id": strategy_id if tab != "ranking" else "",
        "strategy_configuration_id": configuration_id,
        "product_path_selection_id": product_selection_id,
    }
    return {
        "identity": identity,
        "source_artifact_hash": str(source["content_hash"]),
        "artifact_name": artifact_name,
        "cache_keys": [f"strategy-analysis:{source['content_hash']}"],
        "payload": {
            **identity,
            "analysis_tab": tab,
            "source_relative_path": str(source["relative_path"]),
            "source_artifact_hash": str(source["content_hash"]),
            "artifact_name": artifact_name,
        },
    }


def execute(payload: dict[str, Any], sink, cancel_event) -> None:
    if cancel_event.is_set():
        sink.emit_error("cancelled", cancelled=True)
        return
    source = load_json_artifact(
        str(payload["source_relative_path"]),
        str(payload["source_artifact_hash"]),
    )
    if not isinstance(source, dict) or source.get("artifact_version") != 1:
        raise ValueError("策略分析基础生成物版本不兼容")
    sink.emit_progress(1, 3, phase="post_replay", message="已验证策略分析基础生成物")
    detail = build_strategy_analysis_tab(source, payload)
    if cancel_event.is_set():
        sink.emit_error("cancelled", cancelled=True)
        return
    sink.emit_progress(2, 3, phase="post_replay", message="已完成策略分析")
    sink.emit_core_artifact(str(payload["artifact_name"]), detail)
    sink.emit_progress(3, 3, phase="post_replay", message="已保存策略分析结果")
    sink.emit_result({
        "success": True,
        "artifact_name": str(payload["artifact_name"]),
        "analysis_tab": str(payload["analysis_tab"]),
    })


register(SupplementalAdapter(
    kind=KIND,
    parent_kinds=frozenset({"backtest"}),
    prepare=prepare,
    execute=execute,
))
