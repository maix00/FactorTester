from __future__ import annotations

import shlex
from typing import Any


ANALYSES = ("ic", "factor_evaluation", "factor_type_analysis", "backtest")


def build_factor_research_plan(
    *,
    factor_families: list[str],
    factors: list[str] | None = None,
    configuration_file: str,
    analyses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a research plan around one durable workspace/run/job contract."""
    families = [item.strip() for item in factor_families if item.strip()]
    if not families:
        raise ValueError("at least one factor family is required")
    family_args = " ".join(f"--factor-family {shlex.quote(item)}" for item in families)
    factor_args = " ".join(f"--factor {shlex.quote(item)}" for item in (factors or []))
    configuration = shlex.quote(configuration_file)
    selected = analyses or list(ANALYSES)
    analysis_args = " ".join(f"--analysis {shlex.quote(item)}" for item in selected)
    return [
        {
            "phase": "inspect_factor_expr_dsl",
            "purpose": "确认 FactorExpr 算子、输入窗口和无未来函数约束。",
            "command": "factortester custom_factors operators",
        },
        {
            "phase": "prepare_factor_workspace",
            "purpose": "同步并检查因子源码。",
            "command": "cli-anything-factortester-research workspace prepare --build --sync",
        },
        {
            "phase": "understand_factor_source",
            "purpose": "阅读因子实现，记录 rolling/shift、数据列和可见时间。",
            "command": " && ".join(
                f"cli-anything-factortester-research workspace inspect --factor-family {shlex.quote(item)}"
                for item in families
            ),
        },
        {
            "phase": "build_validation_slices",
            "purpose": "冻结样本内、滚动和 OOS 标注切片。",
            "command": "cli-anything-factortester-research slice-plan --json",
        },
        {
            "phase": "create_research_workspace",
            "purpose": "创建用户拥有的持久研究工作区。",
            "command": f"factortester workspace create {family_args} {factor_args}".rstrip(),
        },
        {
            "phase": "freeze_configuration",
            "purpose": "将因子家族、具体因子、产品域、日期、成本、容量和 step 设置写入活动配置。",
            "command": f"factortester workspace update --file {configuration}",
            "required_outputs": ["workspace_id", "configuration_revision", "configuration fingerprint"],
        },
        {
            "phase": "submit_run",
            "purpose": "一次冻结 RunSpec，并为各分析创建同一 run 下的独立 job。",
            "command": f"factortester run submit {analysis_args}",
            "required_outputs": ["run_id", "job_id", "kind", "status"],
        },
        {
            "phase": "observe_jobs",
            "purpose": "按 job_id 恢复进度；页面和 harness 都不成为任务 owner。",
            "command": "factortester job list && factortester job watch <job_id>",
        },
        {
            "phase": "control_jobs",
            "purpose": "显式取消、失败重试或从 paused checkpoint 创建后续 attempt。",
            "command": "factortester job cancel|retry|continue <job_id>",
        },
        {
            "phase": "audit_results",
            "purpose": "按 job_id 查询 terminal result、错误堆栈和 artifacts。",
            "command": "factortester job status <job_id> && factortester job artifact <job_id> <name>",
        },
        {
            "phase": "platform_gap_loop",
            "purpose": "平台缺口必须在所属 issue branch/worktree 修复并测试；harness 只记录证据。",
            "command": "记录 gap -> issue worktree 修复 -> tests -> commit -> 人工授权 merge",
        },
    ]


def validation_checklist() -> list[str]:
    return [
        "RunSpec 必须冻结因子 aliases、产品 ranking universe/product mask、时间范围与全部设置。",
        "IC/IR/t-stat/sample_count 与回测成本后指标必须来自同一冻结 RunSpec。",
        "参数网格记录 hypotheses_tested，并解释多重检验风险。",
        "信号可见时间、下一 open 成交和 forward-return 窗口必须无未来函数。",
        "费用、成交量容量、margin mode、fee mode 显式写入配置。",
        "ResearchSlice/ValidationPlan 区分 selection、validation 和 OOS annotation。",
        "job 的 queued/running/paused/succeeded/failed/cancelled/expired 状态可按 job_id 查询。",
        "失败保留 error traceback；取消保留 cancel_reason；完成结果与 artifact 保留到 TTL。",
        "重试或 step continue 创建新 job_id，并通过 retry_of 关联旧 attempt。",
        "harness 不调用分析专属提交 API，也不依赖 page_uuid。",
    ]
