"""Deterministic Chinese report projection for Graph continuation."""

from __future__ import annotations

from typing import Any

from ..report_link_kinds import report_link_kind_for_ref


def continuation_narrative(carrier: dict[str, Any]) -> dict[str, Any]:
    """Describe one same-node Graph re-entry without inventing research facts."""
    transition = carrier["latest_transition"]
    references = _references(carrier)
    links = [
        {
            "link_id": f"continuation-{index}",
            "kind": kind,
            "target_ref": target,
            "label": _label(kind, target),
        }
        for index, (kind, target) in enumerate(references)
    ]
    link_ids = [item["link_id"] for item in links]
    return {
        "schema_version": 2,
        "language": "zh-Hans",
        "title": f"研究图切换：{carrier['graph_ref']}",
        "sections": [{
            "section_id": "graph-continuation-reentry",
            "title": "研究图切换与当前节点重新进入",
            "chapter_ref": f"node:{carrier['current_node']}",
            "section_role": "upgrade_reentry",
            "blocks": [
                {
                    "kind": "paragraph",
                    "text": (
                        f"研究已显式切换到 `{carrier['graph_ref']}`，切换前后"
                        f"均停留在 `{carrier['current_node']}` 节点。本步骤只记录"
                        "当前节点的重新进入，不重放历史节点、数据检查、因子语义"
                        "或既有试验，也不改变已有研究结论。"
                    ),
                },
                {
                    "kind": "list",
                    "rows": [{
                        "text": (
                            "既有主张、义务和证据按稳定引用保留；新增的进入要求"
                            "由 Research Agent 后续逐项判断是否已被覆盖，只有真实"
                            "缺口才会新建或重开具体义务。"
                        ),
                        "link_ids": link_ids,
                    }],
                },
            ],
            "links": links,
        }],
    }


def _references(carrier: dict[str, Any]) -> list[tuple[str, str]]:
    transition = carrier["latest_transition"]
    values: list[tuple[str, str]] = []
    values.extend(
        (report_link_kind_for_ref(item), item)
        for item in transition["evidence_refs"]
    )
    values.extend(
        ("trial_plan", item) for item in transition["trial_plan_refs"]
    )
    values.extend(
        ("obligation", item) for item in transition["obligation_refs"]
    )
    values.extend(("claim", item) for item in transition["claim_refs"])
    values.extend(("job", item) for item in transition["job_refs"])
    values.extend(("run", item) for item in transition["run_refs"])
    values.extend(("delta", item) for item in transition["delta_refs"])
    values.extend(
        ("obligation", f"obligation:{item['obligation_id']}")
        for item in transition["obligation_changes"]
    )
    values.extend(
        ("claim", f"claim:{item['claim_id']}")
        for item in transition["claim_changes"]
    )
    return list(dict.fromkeys(values))


def _label(kind: str, target: str) -> str:
    labels = {
        "evidence": "沿用证据",
        "trial_plan": "既有试验计划",
        "obligation": "研究义务",
        "claim": "研究主张",
        "job": "计算任务",
        "run": "试验运行",
        "delta": "状态变化",
        "graph_reference": "报告记录",
    }
    suffix = target.split(":", 1)[-1]
    return f"{labels.get(kind, '研究记录')}：{suffix[:72]}"
