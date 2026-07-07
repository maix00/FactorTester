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
        }
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
        "费用、成交量容量、margin mode、fee mode 显式写入配置。",
        "无未来函数：信号使用 close 时只能在下一可见 open 或更晚成交。",
        "发现 CLI/API/后端能力缺口时先记录 gap，修复代码并验证后再继续研究。",
        "最终结论标注 exploratory / in-sample / out-of-sample。",
    ]
