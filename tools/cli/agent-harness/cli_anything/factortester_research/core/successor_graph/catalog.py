"""Versioned, product-neutral obligation prompts for successor Graph v10."""

from __future__ import annotations

import hashlib
from typing import Any

from .resolvers import resolver_binding_ref
from .requirement_titles import REQUIREMENT_TITLES_ZH

CATEGORY_SPECS = {
    "hypothesis_validity": (
        "假设有效性",
        "经济机制是否完整、可证伪，并能把可观察代理与预期方向、期限和边界联系起来。",
        "hypothesis_preregistration",
    ),
    "data": (
        "数据",
        "所需事实是否存在、可取得、可合法使用并在正确时点可得。",
        "data_contract",
    ),
    "factor_semantics": (
        "因子语义与经济机制",
        "表达式计算什么，代表何种风险、行为或市场机制，以及何时失效。",
        "factor_semantics",
    ),
    "trial_design_validity": (
        "试验设计有效性",
        "事前怎样冻结比较、控制变量、信息分区、搜索范围和停止条件。",
        "validation_design",
    ),
    "statistical_validity": (
        "统计有效性",
        "事后证据能支持多强的结论，以及依赖、多重检验和不确定性如何限制推断。",
        "result_audit",
    ),
    "strategy_design": (
        "策略设计",
        "研究者可改变的信号时点、条件化、仓位、调仓和 session policy 如何受控。",
        "validation_design",
    ),
    "market_execution_accounting": (
        "市场执行与会计",
        "目标市场真实允许什么，以及交易日、合约、费用、保证金和结算如何记账。",
        "trial_execution",
    ),
    "other": (
        "其他待分类问题",
        "会实质改变 Trial 或 Claim、但当前目录尚未覆盖的问题。",
        "research_decision",
    ),
}


REQUIREMENT_QUESTIONS = {
    "hypothesis_validity": {
        "mechanism_chain": "从市场事实和参与者行为到价格或收益的作用链、方向与期限是什么？",
        "observable_proxy": "因子表达式、ColumnRef 和参数真实代理机制中的哪一环，何时失真？",
        "falsifiable_predictions": "除回测表现外，机制还有哪些可观察预测，什么事实会削弱或证伪？",
        "alternative_explanations": "beta、carry、趋势、流动性、执行伪影或选择偏差能否替代解释？",
        "boundary_conditions": "机制预期在哪些产品、时段、环境、流动性和参与者结构下失效？",
        "derived_incremental_mechanism": "派生家族改变机制的哪一环，父家族是否仍为特例，如何比较？",
        "participant_incentives": "哪些参与者因风险、信息、库存、资金、授权或监管约束产生交易需求？",
        "behavioral_channel": "注意力、锚定、处置、羊群或反应偏差是否给出可观察预测？",
        "risk_transfer_and_compensation": "谁转移何种风险，谁承接风险，预期收益是否为约束补偿？",
        "information_diffusion": "信息怎样跨参与者、市场、合约和时间扩散，为什么不会即时吸收？",
        "liquidity_inventory_and_impact": "流动性需求、做市库存、订单失衡或冲击如何影响价格？",
        "fundamental_supply_demand_and_carry": "库存、产消、季节、仓储、融资和便利收益如何作用？",
        "institutional_and_contract_rules": "制度、保证金、交割、限仓、时段或政策如何形成约束和断点？",
    },
    "data": {
        "source_availability": "是否有数据源覆盖目标产品、合约和市场？",
        "temporal_coverage": "起止时间、连续缺口和最新可用时间是否覆盖 Trial？",
        "granularity_and_depth": "频率与 L1、L2、MBP、MBO 等深度是否分别满足 Trial？",
        "required_fields": "表达式、策略和会计要求的字段是否真实存在？",
        "temporal_alignment": "每个输入的事件或发布时间如何与信号及下一可成交时点对齐？",
        "quality_and_continuity": "缺失、重复、异常值、陈旧价和合约断层是否可接受？",
        "provenance_permission_version": "来源、许可、快照版本、hash 和派生链是否可审计？",
    },
    "factor_semantics": {
        "expression_identity": "原公式、LaTeX、算子树、参数、ColumnRef 和版本是什么？",
        "observable_meaning_direction_units": "表达式的可观察含义、方向、单位和数值域是什么？",
        "timing_and_causality": "每项输入何时可知，信号预测何种 horizon，是否含未来信息？",
        "risk_transfer_and_fundamentals": "风险转移、库存、供需、carry 或套保压力能否解释该因子？",
        "behavioral_mechanism": "注意力、锚定、羊群、过度或不足反应等机制有何可证伪预测？",
        "participant_ecology": "生产商、套保者、资管、游资、做市商或散户的激励如何作用？",
        "microstructure_channel": "订单流、价差、深度、库存风险或撮合规则是否构成机制？",
        "alternatives_and_falsifiers": "哪些替代解释也会产生该结果，什么证据会削弱原解释？",
        "boundary_conditions": "机制预期在哪些产品、地区、环境和期限成立或失效？",
        "parameterization_and_derivation": "哪些表达式子树值得参数化或派生，且父家族是否仍为特例？",
        "derived_comparability": "父子因子家族改变了什么，旧证据在哪些参数下仍适用？",
        "conditioning_semantics": "辅助因子属于 raw expression 增强还是策略层门控？",
    },
    "trial_design_validity": {
        "target_contrast": "本 Trial 的主要义务、estimand、outcome、目标与对照关系是什么？",
        "baseline_relevance": "基线为何能回答当前问题，仍有哪些不可比较差异？",
        "controlled_variable_isolation": "RunSpec 只改变了获准维度吗，是否隔离了目标改动？",
        "population_and_universe": "目标总体、产品范围、纳入排除和外推边界是什么？",
        "information_partition": "哪些信息用于构造、选择或调参，哪些信息仍被冻结？",
        "sequential_holdout": "递进验证与最新 sealed holdout 怎样排序，何时才可打开？",
        "regime_control_and_coverage": "市场环境如何定义、控制、分层并限定跨环境推断？",
        "instrument_control_and_coverage": "标的如何分层、比较并限定跨标的推断？",
        "temporal_overlap_and_gap": "lookback、持有期、标签、purge、embargo 和 session 是否泄漏？",
        "replication_structure": "独立重复、seed、period 或 venue replication 如何定义？",
        "adaptation_and_ledger": "参数、派生家族、方法、市场、时段和 holdout 访问是否完整登记？",
        "stop_and_reopen_rule": "停止与资源边界是什么，哪些新证据或变化允许重新开启？",
    },
    "statistical_validity": {
        "estimand_and_metric": "要估计的量是什么，指标为何能回答当前义务，方向和口径是什么？",
        "dependence_structure": "横截面、时间、合约和市场依赖是否被推断方法处理？",
        "uncertainty_and_effect_size": "效应方向、大小、区间与不确定性最多支持多强结论？",
        "selection_and_multiplicity": "多次选择、参数搜索和派生因子造成多大选择偏差？",
        "method_assumptions": "样本量、平稳性、分布、缺失和方法前提是否足够？",
        "sensitivity_and_falsification": "替代口径、反例、失败和冲突是否会推翻当前解释？",
    },
    "strategy_design": {
        "signal_schedule": "因子何时计算、发信号和生效，$F 与 session policy 如何控制？",
        "strategy_conditioning": "辅助信号怎样控制交易、仓位、再平衡或退出？",
        "position_and_rebalance": "信号怎样映射方向、仓位、调仓、退出和风险规则？",
        "session_policy": "信号在 session 边界如何跳过、延后或保留，是否作为受控变量？",
    },
    "market_execution_accounting": {
        "session_calendar": "开闭市、夜盘、节假日、跨午夜交易日和临时变更如何定义？",
        "contract_lifecycle": "合约规格、上市到期、交割、选约和换月在当时如何生效？",
        "order_and_fill": "订单类型、价格限制、撮合、延迟、成交和容量如何建模？",
        "cost_margin_and_settlement": "费用、税费、融资、保证金、盯市和结算如何记账？",
        "backtest_live_consistency": "历史、仿真、延迟流和实盘在哪些语义维度真正可比？",
    },
    "other": {
        "unclassified_material_question": "是否存在目录外但会实质改变 Trial 或 Claim 的问题？",
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
        titles = REQUIREMENT_TITLES_ZH.get(category_id) or {}
        if set(titles) != set(questions):
            raise ValueError(
                f"requirement title catalog mismatch: {category_id}"
            )
        capability_id = f"research-obligation.{category_id}.resolve"
        for short_id, question in questions.items():
            requirement_id = f"{category_id}.{short_id}"
            requirements.append({
                "requirement_id": requirement_id,
                "category_id": category_id,
                "revision": 2,
                "gate_policy": _gate_policy(category_id),
                "title_zh": titles[short_id],
                "question_zh": question,
                "select_when_zh": "当前 scope、目标节点或候选 Trial 涉及该方面时。",
                "evidence_expected_zh": [
                    "与 subject、scope、时间和版本匹配的 Evidence 引用",
                    "Research Agent 对是否建立具体义务、理由及首个 Trial 的逐项回答",
                ],
                "not_sufficient_zh": [
                    "只因目录列出该小类就机械创建义务",
                    "只凭单次有利回测、跨市场类比或无引用断言宣告满足",
                ],
                "industry_principle_zh": _industry_principle(category_id),
                "industry_basis_refs": _basis_refs(category_id),
                "resolver_capability_ids": [capability_id],
                "resolver_binding_ref": resolver_binding_ref(requirement_id),
                "fallback_route": "capability_gap",
                "report_requirement_refs": [
                    f"report.requirement.{requirement_id}"
                ],
            })
    return {
        "catalog_revision": 4,
        "categories": categories,
        "requirements": requirements,
    }


def resolver_capability_descriptors() -> dict[str, dict[str, str]]:
    return {
        f"research-obligation.{category_id}.resolve": {
            "capability_description": (
                f"Resolve provider-neutral {category_id} facts, ask whether a "
                "concrete obligation is material, and return bounded Evidence "
                "references without deciding the final research Claim."
            ),
            "descriptor_hash": _stable_hash(
                f"research-obligation.{category_id}.resolve@2"
            ),
        }
        for category_id in CATEGORY_SPECS
    }


def _gate_policy(category_id: str) -> str:
    if category_id in {"trial_design_validity", "statistical_validity"}:
        return "resolve_before_exit"
    if category_id == "other":
        return "discover_before_exit"
    return "plan_before_exit"


def _industry_principle(category_id: str) -> str:
    principles = {
        "hypothesis_validity": "从事实、参与者、约束和价格形成建立可证伪机制，不能用回测好代替机制。",
        "data": "先确认事实是否存在且在当时可知；频率与市场深度必须正交描述。",
        "factor_semantics": "从表达式和市场事实提出可证伪机制，同时保留替代解释。",
        "trial_design_validity": "比较和信息边界必须事前冻结，最新未见区间留给最终 OOS。",
        "statistical_validity": "结果是带范围和不确定性的证据，不是由单阈值产生的真理。",
        "strategy_design": "研究者可选择的交易规则必须作为受控变量而非因子公式暗含事实。",
        "market_execution_accounting": "外生规则必须按市场、地区和生效日期解析，不得跨市场代替验证。",
        "other": "只保留会改变 Trial 或 Claim 的物质问题，并提出可验证路径或有边界未知项。",
    }
    return principles[category_id]


def _basis_refs(category_id: str) -> list[str]:
    specialized = {
        "hypothesis_validity": ["S-FIRST-PRINCIPLES", "S-MECHANISM-FALSIFIABILITY", "S-MARKET-MICROSTRUCTURE"],
        "data": ["S-W3C-PROV", "S-DATA-PROVENANCE-PIT"],
        "factor_semantics": ["S-FIRST-PRINCIPLES", "S-MECHANISM-FALSIFIABILITY"],
        "trial_design_validity": ["S-NIST-DOE", "S-ICH-E9R1", "S-ROLLING-ORIGIN"],
        "statistical_validity": ["S-ASA-PVALUE", "S-WHITE-REALITY-CHECK", "S-BAILEY-BACKTEST-OVERFITTING"],
        "strategy_design": ["S-NIST-DOE", "S-MARKET-MICROSTRUCTURE"],
        "market_execution_accounting": ["S-MARKET-RULES-PIT", "S-PFMI"],
        "other": ["S-FIRST-PRINCIPLES"],
    }
    return specialized[category_id]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
