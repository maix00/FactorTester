"""Canonical reader-facing titles for research graph nodes."""

from __future__ import annotations


_NODE_TITLES_ZH = {
    "hypothesis_preregistration": "假设预注册",
    "capability_resolution": "研究能力确认",
    "data_contract": "数据契约",
    "factor_semantics": "因子语义",
    "validation_design": "验证设计",
    "trial_plan": "试验计划",
    "trial_execution": "试验执行",
    "capability_gap": "能力缺口",
    "job_evidence_ready": "任务证据就绪",
    "evidence_assessment": "证据评估",
    "factor_improvement": "因子改进",
    "result_audit": "结果审计",
    "research_decision": "研究决策",
    "completed": "研究完成",
}


def node_title_zh(node_id: str) -> str:
    """Return one stable Chinese title without inferring from report prose."""
    return _NODE_TITLES_ZH.get(node_id, node_id)
