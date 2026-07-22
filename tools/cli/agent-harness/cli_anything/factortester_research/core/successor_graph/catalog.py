"""Versioned verification-requirement catalog for the successor Graph."""

from __future__ import annotations

from typing import Any


CATEGORY_SPECS = {
    "hypothesis_validity": (
        "假设有效性",
        "经济或行为机制是否完整、可观察、可证伪并具有明确边界。",
        "hypothesis_preregistration",
    ),
    "data": (
        "数据",
        "数据是否真实可得、可合法使用、时点正确并覆盖当前试验。",
        "data_contract",
    ),
    "factor_semantics": (
        "因子语义",
        "因子表达式实际计算什么、何时可见以及版本之间如何比较。",
        "factor_semantics",
    ),
    "trial_design_validity": (
        "试验设计有效性",
        "比较、控制、信息分区和递进试验是否足以回答目标义务。",
        "validation_design",
    ),
    "statistical_validity": (
        "统计有效性",
        "估计目标、依赖结构、不确定性和选择过程是否支持推断。",
        "validation_design",
    ),
    "strategy_design": (
        "策略设计",
        "研究者可改变的信号到交易规则是否清楚并得到受控比较。",
        "validation_design",
    ),
    "market_execution_accounting": (
        "市场执行与会计",
        "外生交易规则、成交约束和资金会计是否被正确建模。",
        "trial_execution",
    ),
    "other": (
        "其他待分类问题",
        "会改变研究决定但尚无适当正式分类的问题。",
        "result_audit",
    ),
}


REQUIREMENT_QUESTIONS = {
    "hypothesis_validity": {
        "mechanism_chain": "从市场事实或参与者行为到价格、收益的作用链是什么？",
        "observable_proxy": "表达式和参数真实代理了机制中的哪一环，何时失真？",
        "falsifiable_predictions": "除回测好之外，什么事实会削弱或证伪该机制？",
        "alternative_explanations": "结果是否可能来自已知暴露、伪影或选择偏差？",
        "boundary_conditions": "机制预期在哪些产品、环境和期限成立或失效？",
        "derived_incremental_mechanism": "派生家族增加了什么机制并如何与父家族比较？",
        "participant_incentives": "哪些参与者因何种激励或约束产生该交易需求？",
        "behavioral_channel": "依赖什么行为偏差，它产生哪些可观察预测？",
        "risk_transfer_and_compensation": "收益是否补偿风险转移、资金或承接约束？",
        "information_diffusion": "信息为何不会立即被价格吸收，如何跨市场传播？",
        "liquidity_inventory_and_impact": "流动性、库存或冲击如何产生延续或反转？",
        "fundamental_supply_demand_and_carry": "供需、库存、季节性和 carry 如何作用？",
        "institutional_and_contract_rules": "制度或合约规则如何形成约束或结构断点？",
    },
    "data": {
        "product_source_availability": "有没有数据源提供目标产品或合约？",
        "realtime_l2_availability": "目标产品有没有可用的实时 L2 数据？",
        "delayed_l2_availability": "是否有延迟口径明确的 L2 数据？",
        "realtime_l1_availability": "目标产品有没有可用的实时 L1 数据？",
        "historical_l1_availability": "目标产品有没有历史 L1 数据？",
        "historical_l2_availability": "目标产品有没有历史 L2 数据？",
        "trial_window_coverage": "数据范围和缺口是否覆盖当前 TrialPlan？",
        "field_history_coverage": "保证金、手续费和规则历史是否覆盖试验？",
        "point_in_time_integrity": "数据当时何时可见，是否有未来或修订泄漏？",
        "permission_and_use": "账户和许可是否允许研究、保存、回放或实盘使用？",
    },
    "factor_semantics": {
        "observable_meaning_and_direction": "原式计算的可观察含义、方向和尺度是什么？",
        "expression_validity": "表达式树、算子类型和执行身份是否一致有效？",
        "numerical_domain_and_units": "数值域、缺失值、单位和尺度变化是否合理？",
        "causal_timing": "输入可见时点、窗口和最终信号对齐是否因果正确？",
        "expression_parameterization": "哪些表达式节点值得参数化且保持父式为特例？",
        "derived_comparability": "父子家族差异和旧证据适用范围是否明确？",
        "conditional_factor_role": "条件化属于 raw expression 还是策略层门控？",
    },
    "trial_design_validity": {
        "target_contrast": "本 Trial 比较什么、改变什么并回答哪项义务？",
        "baseline_relevance": "基线是否匹配问题而非事后选择的有利对照？",
        "controlled_variable_isolation": "除目标变量外的差异是否固定或明确建模？",
        "population_and_universe": "产品、合约、时间和排除规则是否代表目标范围？",
        "information_partition": "构造、选择、调参与评估的信息是否隔离？",
        "sequential_holdout": "递进样本和最新 holdout 是否保持只向前的信息边界？",
        "regime_control_and_coverage": "市场环境被如何控制、分层或用于外推检查？",
        "instrument_control_and_coverage": "标的差异如何控制且是否造成选择偏差？",
        "temporal_overlap_and_gap": "窗口重叠是否需要 purge、gap 或 embargo？",
        "replication_structure": "哪些时间块、标的或市场构成有效重复？",
        "adaptation_and_ledger": "参数、家族、样本、方法和策略尝试是否完整登记？",
        "stop_and_reopen_rule": "停止、继续、开放 holdout 和重开条件是否事前明确？",
    },
    "statistical_validity": {
        "estimand_and_metric": "估计量、指标、方向、单位和聚合口径是什么？",
        "dependence_structure": "时间、横截面、合约和市场依赖如何处理？",
        "uncertainty_and_effect_size": "效应大小、不确定性和可辨识范围是什么？",
        "selection_and_multiplicity": "多次选择如何进入 ledger 并限制推断？",
        "method_assumptions": "所选方法的样本、分布和稳定性前提是否成立？",
        "sensitivity_and_falsification": "结论对合理替代口径和反证是否稳健？",
    },
    "strategy_design": {
        "signal_schedule": "信号计算、生效和可交易时点如何对应？",
        "strategy_conditioning": "辅助信号如何控制交易、仓位或再平衡？",
        "position_and_rebalance": "信号如何映射为仓位、调仓、退出和风险约束？",
        "session_policy": "跨 session、收盘前跳过等策略选择如何控制？",
    },
    "market_execution_accounting": {
        "session_calendar": "交易日、夜盘、节假日和开收盘规则是否正确？",
        "contract_lifecycle": "上市、到期、交割、选约和换月规则是否正确？",
        "order_and_fill": "订单、撮合、滑点、流动性和容量假设是否合理？",
        "cost_margin_and_settlement": "手续费、保证金、利息和结算会计是否正确？",
        "backtest_live_consistency": "历史、仿真、延迟流和实盘语义是否一致？",
    },
    "other": {
        "unclassified_material_question": "是否存在目录外但会改变 Trial 或 Claim 的问题？",
    },
}


def build_requirement_catalog() -> dict[str, Any]:
    categories = [
        {
            "category_id": category_id,
            "title_zh": title,
            "description_zh": description,
            "home_node": home_node,
        }
        for category_id, (title, description, home_node) in CATEGORY_SPECS.items()
    ]
    requirements = []
    for category_id, questions in REQUIREMENT_QUESTIONS.items():
        capability_id = f"research-obligation.{category_id}.resolve"
        for short_id, question in questions.items():
            requirement_id = f"{category_id}.{short_id}"
            requirements.append({
                "requirement_id": requirement_id,
                "category_id": category_id,
                "revision": 1,
                "gate_policy": _gate_policy(category_id, short_id),
                "title_zh": question.rstrip("？"),
                "question_zh": question,
                "select_when_zh": "当前研究范围、目标节点或候选试验涉及该问题时。",
                "evidence_expected_zh": [
                    "与当前 subject 和 scope 匹配的事实 receipt 或 Trial Evidence",
                    "Research Agent 基于证据给出的逐项裁决及适用边界",
                ],
                "not_sufficient_zh": [
                    "只有能力名称、配置存在或无引用的自然语言断言",
                    "只凭单次有利回测结果直接宣告满足",
                ],
                "industry_principle_zh": (
                    "先明确问题、证据身份与反证边界，再决定义务是否缩小、"
                    "扩大、保持未知或需要新试验。"
                ),
                "industry_basis_refs": _basis_refs(category_id),
                "resolver_capability_ids": [capability_id],
                "cli_invocation_templates": [
                    "factortester research obligations resolve "
                    f"--requirement {requirement_id} --branch <id> --json"
                ],
                "resolver_output_schema": {
                    "type": "object",
                    "required": ["status", "evidence_refs", "limitations"],
                },
                "fallback_route": "capability_gap",
                "report_requirement_refs": [f"report.requirement.{requirement_id}"],
            })
    return {
        "catalog_revision": 1,
        "categories": categories,
        "requirements": requirements,
    }


def resolver_capability_descriptors() -> dict[str, dict[str, str]]:
    return {
        f"research-obligation.{category_id}.resolve": {
            "capability_description": (
                f"Resolve provider-neutral {category_id} facts and return "
                "bounded evidence references without deciding the research claim."
            ),
            "descriptor_hash": _stable_hash(
                f"research-obligation.{category_id}.resolve@1"
            ),
        }
        for category_id in CATEGORY_SPECS
    }


def _gate_policy(category_id: str, short_id: str) -> str:
    if category_id in {
        "trial_design_validity",
        "statistical_validity",
        "market_execution_accounting",
    }:
        return "resolve_before_exit"
    if category_id == "other":
        return "discover_before_exit"
    return "plan_before_exit"


def _basis_refs(category_id: str) -> list[str]:
    common = ["S-FIRST-PRINCIPLES", "S-W3C-PROV"]
    specialized = {
        "data": ["S-DATA-PROVENANCE-PIT"],
        "trial_design_validity": ["S-NIST-DOE", "S-ICH-E9R1"],
        "statistical_validity": ["S-BAILEY-BACKTEST-OVERFITTING"],
        "hypothesis_validity": ["S-MECHANISM-FALSIFIABILITY"],
        "market_execution_accounting": ["S-MARKET-RULES-PIT"],
    }
    return [*common, *specialized.get(category_id, [])]


def _stable_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()
