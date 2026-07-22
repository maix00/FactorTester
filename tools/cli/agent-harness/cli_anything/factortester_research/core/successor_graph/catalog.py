"""Versioned, product-neutral obligation prompts for successor Graph v9."""

from __future__ import annotations

import hashlib
from typing import Any


CATEGORY_SPECS = {
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
    "trial_design": (
        "试验设计",
        "事前怎样冻结比较、控制变量、信息分区、搜索范围和停止条件。",
        "validation_design",
    ),
    "statistical_validity": (
        "统计有效性",
        "事后证据能支持多强的结论，以及依赖、多重检验和不确定性如何限制推断。",
        "result_audit",
    ),
    "trading_strategy": (
        "交易策略",
        "研究者可改变的信号时点、条件化、仓位、调仓和执行选择如何受控。",
        "validation_design",
    ),
    "market_rules_accounting": (
        "市场规则与会计",
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
    "data": {
        "source_availability": "是否有数据源覆盖目标产品、合约和市场？",
        "temporal_coverage": "起止时间、连续缺口和最新可用时间是否覆盖 Trial？",
        "granularity_and_depth": "频率与 L1、L2、MBP、MBO 等深度是否分别满足 Trial？",
        "required_fields": "表达式、策略和会计要求的字段是否真实存在？",
        "point_in_time_semantics": "时间戳、发布时间、修订和成分信息在当时是否可知？",
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
    "trial_design": {
        "objective_and_estimand": "本 Trial 要改变哪项义务，处理对象、指标、horizon 和范围是什么？",
        "baseline_control_ablation": "基线、对照、控制变量和 ablation 能否隔离目标改动？",
        "temporal_validation": "构造、选择、递进验证和最新 sealed OOS 是否保持时间顺序？",
        "market_instrument_blocks": "标的、地区和市场环境如何分块并限定外推范围？",
        "leakage_purge_embargo": "重叠标签、全样本变换和相邻窗口泄漏如何隔离？",
        "search_ledger_stopping": "参数、派生家族、图表观察和失败尝试是否登记并冻结停止规则？",
        "sample_support": "样本、交易数和有效独立信息量是否足以回答义务？",
        "strategy_freeze": "信号、成本、roll、仓位和执行假设中哪些固定、哪些是处理变量？",
    },
    "statistical_validity": {
        "effect_and_uncertainty": "效应量、方向、区间与不确定性支持多强结论？",
        "dependence_robustness": "时间、横截面、合约依赖、异方差和重尾如何处理？",
        "multiple_testing": "试验次数、参数搜索和派生因子选择造成多大选择偏差？",
        "distribution_and_tail": "偏度、峰度、尾部损失、回撤和少数交易集中是否可靠？",
        "parameter_stability": "参数邻域、时间切片、标的和环境下是否稳定？",
        "external_oos_consistency": "递进 OOS、最新未见区间和跨市场环境结果是否一致？",
        "conflicts_and_negative_results": "冲突、失败、缺失窗口和无法复现是否完整保留？",
    },
    "trading_strategy": {
        "signal_schedule": "因子何时计算、发信号和生效，$F 与 session policy 如何控制？",
        "position_and_risk": "信号怎样映射方向、仓位、杠杆、限仓、退出和风险预算？",
        "conditional_gating": "辅助信号怎样控制交易、仓位、再平衡或退出？",
        "execution_choice": "市价、限价、延迟、排队、成交概率和部分成交如何建模？",
        "cost_and_capacity": "价差、冲击、换手与容量假设如何作为策略变量比较？",
        "contract_selection_and_roll": "期货选约、换月和交割前退出采用什么策略？",
        "live_parity": "历史、仿真、延迟流和实盘是否使用同一信号与策略配置？",
    },
    "market_rules_accounting": {
        "sessions_and_trade_date": "开闭市、夜盘、节假日和跨午夜交易日如何定义？",
        "contract_specification": "tick、lot、multiplier、币种、到期和交割规则何时有效？",
        "price_and_order_constraints": "涨跌停、熔断、价格笼子、订单类型和撮合优先级是什么？",
        "settlement_and_corporate_actions": "结算、分红拆股、退市和最终交割如何影响结果？",
        "margin_mark_to_market": "历史保证金、每日盯市、组合抵扣和现金占用如何记账？",
        "fees_taxes_financing": "手续费、税费、借券和融资成本的历史口径是什么？",
        "position_access_limits": "持仓限额、套保资格、账户聚合和做空限制是什么？",
        "rule_versioning": "规则在目标日期是否有效，变化后哪些义务必须重开？",
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
        capability_id = f"research-obligation.{category_id}.resolve"
        for short_id, question in questions.items():
            requirement_id = f"{category_id}.{short_id}"
            requirements.append({
                "requirement_id": requirement_id,
                "category_id": category_id,
                "revision": 1,
                "gate_policy": _gate_policy(category_id),
                "title_zh": question.rstrip("？"),
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
                "cli_invocation_templates": [
                    "factortester research-graph requirement-detail "
                    f"<instance> <branch> {requirement_id}",
                ],
                "resolver_output_schema": {
                    "type": "object",
                    "required": [
                        "applicability", "decision", "rationale",
                        "evidence_refs", "limitations", "first_trial_ref",
                    ],
                },
                "fallback_route": "capability_gap",
                "report_requirement_refs": [
                    f"report.requirement.{requirement_id}"
                ],
            })
    return {
        "catalog_revision": 2,
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
    if category_id in {"trial_design", "statistical_validity"}:
        return "resolve_before_exit"
    if category_id == "other":
        return "discover_before_exit"
    return "plan_before_exit"


def _industry_principle(category_id: str) -> str:
    principles = {
        "data": "先确认事实是否存在且在当时可知；频率与市场深度必须正交描述。",
        "factor_semantics": "从表达式和市场事实提出可证伪机制，同时保留替代解释。",
        "trial_design": "比较和信息边界必须事前冻结，最新未见区间留给最终 OOS。",
        "statistical_validity": "结果是带范围和不确定性的证据，不是由单阈值产生的真理。",
        "trading_strategy": "研究者可选择的交易规则必须作为受控变量而非因子公式暗含事实。",
        "market_rules_accounting": "外生规则必须按市场、地区和生效日期解析，不得跨市场代替验证。",
        "other": "只保留会改变 Trial 或 Claim 的物质问题，并提出可验证路径或有边界未知项。",
    }
    return principles[category_id]


def _basis_refs(category_id: str) -> list[str]:
    specialized = {
        "data": ["S-W3C-PROV", "S-DATA-PROVENANCE-PIT"],
        "factor_semantics": ["S-FIRST-PRINCIPLES", "S-MECHANISM-FALSIFIABILITY"],
        "trial_design": ["S-NIST-DOE", "S-ICH-E9R1", "S-ROLLING-ORIGIN"],
        "statistical_validity": ["S-ASA-PVALUE", "S-WHITE-REALITY-CHECK", "S-BAILEY-BACKTEST-OVERFITTING"],
        "trading_strategy": ["S-NIST-DOE", "S-MARKET-MICROSTRUCTURE"],
        "market_rules_accounting": ["S-MARKET-RULES-PIT", "S-PFMI"],
        "other": ["S-FIRST-PRINCIPLES"],
    }
    return specialized[category_id]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
