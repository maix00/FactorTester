"""Auditable industry sources referenced by obligation prompts."""

from __future__ import annotations

from typing import Any


_SOURCES = (
    (
        "S-FIRST-PRINCIPLES",
        "第一性原理研究方法",
        "methodology",
        ["https://mp.weixin.qq.com/s/jYy8vzYMUy-oFUmsn-q3dw"],
        "先从可观察事实、机制和反证义务出发，不能把既有流程当作结论。",
    ),
    (
        "S-W3C-PROV",
        "W3C PROV Overview",
        "standard",
        ["https://www.w3.org/TR/prov-overview/"],
        "证据应保存实体、活动、责任主体与派生关系。",
    ),
    (
        "S-DATA-PROVENANCE-PIT",
        "Point-in-time data and provenance practice",
        "industry_practice",
        [
            "https://www.w3.org/TR/prov-overview/",
            "https://www.sec.gov/featured-topics/market-structure-analytics/research-analysis-market-structure",
        ],
        "可回测不等于当时可知；时间戳、修订和来源版本必须分开记录。",
    ),
    (
        "S-MECHANISM-FALSIFIABILITY",
        "Mechanism and falsifiability discipline",
        "methodology",
        ["https://mp.weixin.qq.com/s/jYy8vzYMUy-oFUmsn-q3dw"],
        "经济故事必须给出替代解释、边界条件与可能证伪它的观察。",
    ),
    (
        "S-NIST-DOE",
        "NIST Engineering Statistics Handbook - Blocking",
        "standard",
        ["https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm"],
        "使用对照、blocking 与受控变量区分目标效应和混杂。",
    ),
    (
        "S-ICH-E9R1",
        "ICH E9(R1) Estimands and Sensitivity Analysis",
        "standard",
        ["https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf"],
        "事前明确 estimand、处理变量、目标总体与敏感性分析。",
    ),
    (
        "S-ROLLING-ORIGIN",
        "Tashman rolling-origin forecast evaluation",
        "research",
        ["https://doi.org/10.1016/S0169-2070(00)00065-0"],
        "时间序列验证应保持时间方向并允许递进的未见窗口。",
    ),
    (
        "S-ASA-PVALUE",
        "ASA Statement on Statistical Significance and P-Values",
        "standard",
        ["https://www.amstat.org/asa/files/pdfs/p-valuestatement.pdf"],
        "统计结论不能只由单一阈值或 p 值决定。",
    ),
    (
        "S-WHITE-REALITY-CHECK",
        "White - A Reality Check for Data Snooping",
        "research",
        ["https://doi.org/10.1111/1468-0262.00152"],
        "搜索过的模型和参数必须进入选择偏差与多重检验评估。",
    ),
    (
        "S-BAILEY-BACKTEST-OVERFITTING",
        "Bailey et al. - Probability of Backtest Overfitting",
        "research",
        ["https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf"],
        "回测选择过程会夸大最佳结果，应保留试验账本并评估过拟合。",
    ),
    (
        "S-MARKET-MICROSTRUCTURE",
        "Kyle - Continuous Auctions and Insider Trading",
        "research",
        ["https://doi.org/10.2307/1913210"],
        "订单流、流动性和价格冲击是机制候选，不能由跨市场类比直接确认。",
    ),
    (
        "S-MARKET-RULES-PIT",
        "Exchange rules and effective-date discipline",
        "official_rules",
        [
            "https://www.cffex.com.cn/lssjfw/",
            "https://www.jpx.co.jp/english/derivatives/rules/",
            "https://www.sec.gov/rules-regulations/2005/06/regulation-nms",
            "https://www.cmegroup.com/market-data/real-time-and-historical-data.html",
        ],
        "规则必须按具体市场、产品和生效日期解析，不能跨地区直接代替验证。",
    ),
    (
        "S-PFMI",
        "CPMI-IOSCO Principles for Financial Market Infrastructures",
        "standard",
        ["https://www.bis.org/cpmi/publ/d101.htm"],
        "结算、保证金与基础设施风险必须保留可追溯的制度口径。",
    ),
)


def build_industry_basis_catalog() -> list[dict[str, Any]]:
    return [
        {
            "source_ref": source_ref,
            "title": title,
            "source_kind": source_kind,
            "locators": locators,
            "principle_zh": principle,
        }
        for source_ref, title, source_kind, locators, principle in _SOURCES
    ]
