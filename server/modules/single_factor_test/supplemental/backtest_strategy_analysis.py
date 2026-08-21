"""Lazy backtest strategy-analysis Adapter."""

from __future__ import annotations

import re
from typing import Any

from server.jobs.artifacts import load_json_artifact
from server.jobs.supplemental.registry import SupplementalAdapter, register
from tools.factors.tester_calc.single_factor_test.group.strategy_analysis import (
    STRATEGY_ANALYSIS_TABS,
    build_strategy_analysis_bundle,
    build_strategy_analysis_tab,
)

KIND = "backtest_strategy_analysis"
TABS = frozenset({*STRATEGY_ANALYSIS_TABS, "ranking"})


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
    if tab == "ranking":
        bundle_tabs = ("ranking",)
    else:
        bundle_tabs = tuple(sorted(STRATEGY_ANALYSIS_TABS))
    artifact_states = {}
    for item_tab in bundle_tabs:
        item = repository.load_artifact(
            job_id=parent.job_id,
            name=f"strategy-analysis--{selector}--{_token(item_tab)}",
            owner=parent.owner,
        )
        artifact_states[item_tab] = {
            "state": str(item.get("state") or "") if item else "absent",
            "content_hash": str(item.get("content_hash") or "") if item else "",
            "deleted_at": item.get("deleted_at") if item else None,
        }
    identity = {
        "version": 1,
        "scope": "ranking" if tab == "ranking" else "strategy_bundle",
        "strategy_id": strategy_id if tab != "ranking" else "",
        "strategy_configuration_id": configuration_id,
        "product_path_selection_id": product_selection_id,
        "artifact_states": artifact_states,
    }
    return {
        "identity": identity,
        "source_artifact_hash": str(source["content_hash"]),
        "artifact_name": artifact_name,
        "cache_keys": [f"strategy-analysis:{source['content_hash']}"],
        "payload": {
            **identity,
            "analysis_tab": tab,
            "selector": selector,
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
    requested_tab = str(payload["analysis_tab"])
    if requested_tab == "ranking":
        details = {"ranking": build_strategy_analysis_tab(source, payload)}
    else:
        details = build_strategy_analysis_bundle(source, payload)
    if cancel_event.is_set():
        sink.emit_error("cancelled", cancelled=True)
        return
    sink.emit_progress(2, 3, phase="post_replay", message="已完成策略分析")
    selector = str(payload["selector"])
    artifact_names = {}
    for tab, detail in details.items():
        name = f"strategy-analysis--{selector}--{_token(tab)}"
        sink.emit_core_artifact(name, detail)
        artifact_names[tab] = name
    sink.emit_progress(3, 3, phase="post_replay", message="已保存策略分析结果")
    sink.emit_plan({
        "success": True,
        "artifact_name": artifact_names[requested_tab],
        "artifact_names": artifact_names,
        "analysis_tab": requested_tab,
    })


register(SupplementalAdapter(
    kind=KIND,
    parent_kinds=frozenset({"backtest"}),
    prepare=prepare,
    execute=execute,
))
