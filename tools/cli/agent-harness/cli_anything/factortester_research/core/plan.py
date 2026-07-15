from __future__ import annotations

import shlex
from typing import Any


def build_factor_research_plan(
    *,
    factor_family: str,
    template: str = "",
    product_groups: list[str] | None = None,
    n_values: list[str] | None = None,
    f_values: list[str] | None = None,
    include_rev: bool = True,
    top: int = 12,
) -> list[dict[str, Any]]:
    product_groups = product_groups or []
    n_values = n_values or []
    f_values = f_values or []
    grid_args = ["--factor-family", shlex.quote(factor_family)]
    for group in product_groups:
        grid_args.extend(["--product-group", shlex.quote(group)])
    for value in n_values:
        grid_args.extend(["--n", shlex.quote(value)])
    for value in f_values:
        grid_args.extend(["--f", shlex.quote(value)])
    grid_args.append("--rev" if include_rev else "--no-rev")
    grid_args.extend(["--top", str(top)])
    grid = " ".join(grid_args)
    plan: list[dict[str, Any]] = [
        {
            "phase": "setup",
            "skill_basis": ["longbridge-quant:factor-research", "quantitative-research:patterns"],
            "purpose": "绑定因子家族、模板和候选产品组。",
            "command": f"factortester single_factor_test --factor-family {shlex.quote(factor_family)}",
        },
        {
            "phase": "inspect_factor_expr_dsl",
            "skill_basis": ["longbridge-quant:factor-research"],
            "purpose": "在阅读或改写因子源码前，先从后端注册表查看 FactorExpr 支持的数据列、时序、截面、期限结构等算子，并判断当前研究需要的算子是否覆盖完整。",
            "command": "factortester custom_factors operators",
            "required_outputs": ["operator_groups", "operator_keys", "operator_descriptions"],
        },
        {
            "phase": "operator_coverage_gate",
            "skill_basis": ["longbridge-quant:factor-research", "cli-anything:refine"],
            "purpose": "如果因子研究需要的算子不全，必须先记录缺失算子的语义、输入输出签名、无未来函数约束、预期测试，再进入所属平台 worktree 补全算子。",
            "command": "若缺算子: cli-anything-factortester-research gap add 'missing FactorExpr operator' '<semantic/signature/tests>'",
            "required_outputs": ["missing_operator_semantics", "expected_signature", "validation_tests"],
        },
        {
            "phase": "prepare_factor_workspace",
            "skill_basis": ["longbridge-quant:factor-research"],
            "purpose": "研究开始前先搭建/同步因子工作区；没有本地因子工作区时必须先 build，再从数据库 sync。",
            "command": "cli-anything-factortester-research workspace prepare --build --sync",
            "required_outputs": ["workspace_root", "git_status"],
        },
        {
            "phase": "understand_factor_source",
            "skill_basis": ["longbridge-quant:factor-research"],
            "purpose": "测试前必须阅读因子工作区源码，确认因子在计算什么、是否存在明显未来函数或过拟合参数。",
            "command": f"cli-anything-factortester-research workspace inspect --factor-family {shlex.quote(factor_family)}",
            "required_outputs": ["source_files", "tree_repr", "source_checks", "rolling_shift_windows", "data_columns"],
        },
        {
            "phase": "build_validation_slices",
            "skill_basis": ["quantitative-research:walk-forward", "quantitative-research:regime-detection"],
            "purpose": "生成并记录 calendar、rolling 和数据驱动 regime 切片；2026 只能作为 OOS 标注，不能用于选参。",
            "command": "cli-anything-factortester-research slice-plan --json",
            "required_outputs": ["calendar_quarterly", "rolling_63d_step21d", "oos_annotation", "selection_policy"],
        },
    ]
    if template:
        plan.extend(
            [
                {
                    "phase": "setup",
                    "purpose": "加载单因子测试模板到 single_factor_test 上下文。",
                    "command": f"factortester single_factor_test --factor-family {shlex.quote(factor_family)} template load {shlex.quote(template)}",
                },
                {
                    "phase": "setup",
                    "purpose": "复制模板到独立 backtest 草稿，避免污染 single_factor_test 状态。",
                    "command": f"factortester backtest template --from-module-template single_factor_test load {shlex.quote(template)}",
                },
            ]
        )
    plan.extend(
        [
            {
                "phase": "diagnose_ic",
                "skill_basis": ["longbridge-quant:factor-research"],
                "purpose": "先用 IC/IR、t-stat、hit rate、decay 预筛选，避免直接过拟合回测。",
                "command": f"factortester ic_test grid {grid}",
                "required_outputs": ["mean_ic", "ir", "t_stat", "hit_rate", "decay", "sample_count"],
            },
            {
                "phase": "diagnose_type",
                "skill_basis": ["longbridge-quant:correlation", "quantitative-research:regime-blindness"],
                "purpose": "检查因子风格暴露和相似参照因子，防止只是伪装 beta 或趋势/波动率暴露。",
                "command": f"factortester factor_type_analysis grid {grid}",
            },
            {
                "phase": "cost_capacity_screen",
                "skill_basis": ["longbridge-quant:execution-model"],
                "purpose": "用费用、成交量容量和产品组覆盖情况筛掉平均收益无法覆盖有效费率的组合。",
                "command": f"factortester backtest compare factor-grid {grid} --volume-capacity-mode volume_participation",
            },
            {
                "phase": "factor_improvement_loop",
                "skill_basis": ["quantitative-research:validations"],
                "purpose": "若 IC/类型/成本/回测表现不好，进入因子工作区修改源码或候选参数，commit、push 入库，然后回到诊断阶段。",
                "command": "cli-anything-factortester-research decision poor-result --reason '<why>' && factortester custom_factors workspace git diff",
            },
            {
                "phase": "platform_gap_loop",
                "skill_basis": ["cli-anything:refine"],
                "purpose": "若发现 FactorTester 平台缺口，包括因子算子缺失、算子语义错误、因子计算错误、测试/回测 API 缺口，先确认所属 issue/task 范围；source_owner 必须在该任务 branch/worktree 修复、充分测试、提交，再 merge 到 CLI worktree，随后经 7998 管理端口重启；client_only 只能记录 gap 并交给维护者。",
                "command": "记录 gap -> 在所属 issue worktree 修复因子算子/语义/计算/API 并充分验证 -> commit -> merge 到 CLI worktree -> cli-anything-factortester-research service restart --target-port 8123",
            },
            {
                "phase": "backtest",
                "skill_basis": ["quantitative-research:proper-backtest-framework"],
                "purpose": "只在诊断通过后运行分组回测；必须带费用、容量、明确 margin mode 和足够订单样本。",
                "command": "factortester backtest --run --verbose",
            },
            {
                "phase": "audit_results",
                "skill_basis": ["quantitative-research:validations"],
                "purpose": "导出策略、ledger、order-flow、snapshot，检查成本、换手、成交容量和无未来函数。",
                "command": "factortester backtest results summary && factortester backtest results order-flow --output order_flow.csv",
            },
        ]
    )
    return plan


def validation_checklist() -> list[str]:
    return [
        "IC/IR/t-stat/sample_count 已报告，且不是只看单次收益曲线。",
        "参数网格记录 hypotheses_tested，解释多重检验风险。",
        "开始改写因子前，必须先查看后端 FactorExpr 算子表；若算子不全，先补全算子和测试，再继续研究。",
        "开始任何 IC/类型/回测前，必须先 workspace prepare --build --sync，并 inspect 因子源码。",
        "必须生成 ResearchSlice/ValidationPlan；不能只用 H1/H2，至少要有季度、滚动窗口和数据驱动 regime 说明。",
        "2026 样本只能作为 OOS 风险标注，不能用于选择因子、产品组、参数或策略 policy。",
        "费用、成交量容量、margin mode、fee mode 显式写入配置。",
        "无未来函数：信号使用 close 时只能在下一可见 open 或更晚成交。",
        "发现 CLI/API/后端能力缺口时先记录 gap，修复代码并验证后再继续研究。",
        "发现因子算子缺失、算子语义错误或计算结果错误时，必须进入平台代码修复流程，不能把错误结果当作因子结论。",
        "只有 source_owner 可以修 FactorTester 服务代码；client_only 用户只能提交 gap 证据，不能假装能修改服务器源码。",
        "source_owner 修平台代码前必须确认所属 issue/task 范围，并在对应 branch/worktree 修改；CLI worktree 只能接收 merge 后的平台改动。",
        "平台代码修复后必须通过 7998 管理端口重启目标服务，再重新运行失败步骤。",
        "表现不好时先回到因子工作区理解并修改因子源码或参数，再重新跑 IC/类型/回测诊断。",
        "最终结论标注 exploratory / in-sample / out-of-sample。",
    ]
