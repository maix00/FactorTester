"""Concise Chinese display titles for versioned obligation requirements."""

from __future__ import annotations


REQUIREMENT_TITLES_ZH = {
    "hypothesis_validity": {
        "mechanism_chain": "机制作用链",
        "observable_proxy": "可观察代理",
        "falsifiable_predictions": "可证伪预测",
        "alternative_explanations": "替代解释",
        "boundary_conditions": "机制边界条件",
        "derived_incremental_mechanism": "派生增量机制",
        "participant_incentives": "参与者激励",
        "behavioral_channel": "行为机制通道",
        "risk_transfer_and_compensation": "风险转移与补偿",
        "information_diffusion": "信息扩散",
        "liquidity_inventory_and_impact": "流动性、库存与冲击",
        "fundamental_supply_demand_and_carry": "基本面供需与 Carry",
        "institutional_and_contract_rules": "制度与合约规则",
    },
    "data": {
        "source_availability": "数据源可用性",
        "temporal_coverage": "时间覆盖",
        "granularity_and_depth": "数据粒度与深度",
        "required_fields": "必需字段",
        "temporal_alignment": "时间对齐",
        "quality_and_continuity": "数据质量与连续性",
        "provenance_permission_version": "来源、许可与版本",
    },
    "factor_semantics": {
        "expression_identity": "表达式身份",
        "observable_meaning_direction_units": "可观察含义、方向与单位",
        "timing_and_causality": "时间与因果",
        "risk_transfer_and_fundamentals": "风险转移与基本面",
        "behavioral_mechanism": "行为机制",
        "participant_ecology": "参与者生态",
        "microstructure_channel": "微观结构通道",
        "alternatives_and_falsifiers": "替代解释与证伪",
        "boundary_conditions": "因子边界条件",
        "parameterization_and_derivation": "参数化与派生",
        "derived_comparability": "派生可比性",
        "conditioning_semantics": "条件化语义",
    },
    "trial_design_validity": {
        "target_contrast": "目标与对照",
        "baseline_relevance": "基线相关性",
        "controlled_variable_isolation": "受控变量隔离",
        "population_and_universe": "目标总体与产品范围",
        "information_partition": "信息分区",
        "sequential_holdout": "递进验证与留出集",
        "regime_control_and_coverage": "市场环境控制与覆盖",
        "instrument_control_and_coverage": "标的控制与覆盖",
        "temporal_overlap_and_gap": "时间重叠与间隔",
        "replication_structure": "重复验证结构",
        "adaptation_and_ledger": "适配与试验账本",
        "stop_and_reopen_rule": "停止与重开规则",
    },
    "statistical_validity": {
        "estimand_and_metric": "估计目标与指标",
        "dependence_structure": "依赖结构",
        "uncertainty_and_effect_size": "不确定性与效应大小",
        "selection_and_multiplicity": "选择与多重检验",
        "method_assumptions": "方法前提",
        "sensitivity_and_falsification": "敏感性与证伪",
    },
    "strategy_design": {
        "signal_schedule": "信号调度",
        "strategy_conditioning": "策略条件化",
        "position_and_rebalance": "仓位与调仓",
        "session_policy": "交易时段政策",
    },
    "market_execution_accounting": {
        "session_calendar": "交易时段与日历",
        "contract_lifecycle": "合约生命周期",
        "order_and_fill": "订单与成交",
        "cost_margin_and_settlement": "费用、保证金与结算",
        "backtest_live_consistency": "回测与实盘一致性",
    },
    "other": {
        "unclassified_material_question": "未分类的重要问题",
    },
}


REQUIREMENT_TITLE_MAP_ZH = {
    f"{category_id}.{short_id}": title
    for category_id, titles in REQUIREMENT_TITLES_ZH.items()
    for short_id, title in titles.items()
}
