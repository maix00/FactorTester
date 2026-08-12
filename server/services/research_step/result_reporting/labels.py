"""Bounded Chinese labels for result-report protocol values."""

from __future__ import annotations

from typing import Any


def obligation_alias(value: Any, *, presentation=None) -> str:
    presented = str((presentation or {}).get("alias_zh") or "").strip()
    if presented:
        return presented
    return {
        "predictive-validity": "预测有效性义务",
        "cost-survival": "交易成本后存活义务",
        "out-of-sample": "样本外有效性义务",
        "data-availability": "数据可用性义务",
    }.get(str(value or ""), "已登记研究义务")


def disposition_alias(value: Any) -> str:
    return {
        "accepted": "已接受",
        "rejected": "已拒绝",
        "revision_requested": "要求修订",
    }.get(str(value or ""), "已完成裁决")


def route_alias(value: Any) -> str:
    return {
        "advance_trial_stage": "进入下一试验阶段",
        "continue_execution": "继续当前试验阶段",
        "research_decision": "进入研究决策",
        "revise_factor": "修订因子",
    }.get(str(value or ""), "按裁决继续")


def obligation_state_alias(value: Any) -> str:
    return {
        "absent": "尚未建立",
        "bounded": "已限定",
        "discharged": "已解除",
        "open": "待处理",
        "rejected": "已否决",
        "reopened": "已重开",
        "serviced": "本轮已处理",
    }.get(str(value or ""), "状态已更新")


def criterion_alias(value: Any) -> str:
    text = str(value or "").removeprefix("criterion:")
    for source, target in (
        ("cross-sectional-ic", "截面 IC"),
        ("day-night", "日盘与夜盘"),
        ("reviewed", "结果已审阅"),
        ("support", "结果已审阅"),
    ):
        text = text.replace(source, target)
    words = []
    for token in text.split("-"):
        if token.isdigit() and len(token) == 4:
            words.append(f"{token} 年")
        elif any("\u4e00" <= char <= "\u9fff" for char in token):
            words.append(token)
    return "".join(words).replace("IC结果", "IC 结果") or "已登记的判定标准"


def action_alias(value: Any) -> str:
    text = str(value or "").lower()
    if "ic" in text:
        return "样本内 IC 检验"
    if any(key in text for key in ("historical-fee", "fee-aware", "net")):
        return "历史手续费回测"
    if any(key in text for key in ("gross", "no-fee", "fee-free")):
        return "无手续费回测"
    if "backtest" in text:
        return "回测检验"
    return "当前证据检验"


def analysis_alias(value: Any) -> str:
    return {
        "ic": "截面 IC 检验",
        "backtest": "策略回测",
        "factor_evaluation": "因子评价",
        "robustness": "稳健性检验",
    }.get(str(value or ""), "研究检验")


def role_alias(value: Any) -> str:
    return {
        "candidate": "候选方案",
        "baseline": "基准方案",
        "control": "对照方案",
        "primary": "主要方案",
    }.get(str(value or ""), "试验方案")


def status_alias(value: Any) -> str:
    return {
        "succeeded": "已成功",
        "failed": "失败",
        "cancelled": "已取消",
        "running": "运行中",
    }.get(str(value or ""), "状态已记录")


def scope_alias(row: dict[str, Any]) -> str:
    alias = str(row.get("run_spec_alias_zh") or "")
    if "夜盘" in alias:
        return "夜盘"
    if "日盘" in alias:
        return "日盘"
    return "既定产品范围"
