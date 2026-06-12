"""
分组测试元数据 — 单一数据源 (Single Source of Truth)

阶段顺序、中文标签、指标名称等统一在此定义。
"""

# ── 阶段元数据 ──

GROUP_TEST_PHASES = [
    {"key": "factor_eval",     "label": "因子计算"},
    {"key": "returns_eval",    "label": "收益率"},
    {"key": "membership",      "label": "分组隶属"},
    {"key": "flat_membership", "label": "展开隶属"},
    {"key": "remap",           "label": "产品映射"},
    {"key": "trade_data",      "label": "交易数据"},
    {"key": "liquidity",       "label": "流动性容量"},
    {"key": "simulate",        "label": "模拟中"},
    {"key": "batch",           "label": "批次结果"},
    {"key": "serialize",       "label": "序列化"},
]
