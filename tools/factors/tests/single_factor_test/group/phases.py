"""
分组测试阶段元数据 — 单一数据源 (Single Source of Truth)

所有阶段的 key、中文标签、执行顺序统一在此定义。
后端在 emit_start 时通过 _emit_progress("init") 携带该列表，
前端据此注册阶段顺序和标签，无需硬编码。

用法：
    from tools.factors.tests.single_factor_test.group.phases import GROUP_TEST_PHASES
    # GROUP_TEST_PHASES 是一个 list[dict]，每项 {"key": str, "label": str}
"""

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
