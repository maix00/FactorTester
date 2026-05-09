# =============================================================================
# tests/test_factor_expr.py
# 因子表达式系统测试
#
# 验证 FactorExpr 表达式树的构建、求值、与 FactorFamily 的整合。
# =============================================================================
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np

from tools.factors.FactorExpr import (
    FactorExpr, ColumnRef, ConstExpr, CompositeExpr, UnaryOp,
    RollingOp, ShiftOp, CrossSectionalOp,
    OPEN, HIGH, LOW, CLOSE, VOLUME, OPEN_INTEREST,
    expr_max, expr_min, ParamRef,
)
from tools.data.DataColumn import DataColumn
from tools.data.DataFreq import DataFreq
from tools.parameters.WindowParam import WindowParam


# ═════════════════════════════════════════════════════════════════════════════
# 1. 表达式树构建测试
# ═════════════════════════════════════════════════════════════════════════════

def test_expression_construction():
    """测试表达式树的构建和依赖追踪。"""
    print("=== 1. 表达式树构建 ===")

    # 基本列引用
    assert isinstance(CLOSE, ColumnRef)
    assert CLOSE.column == DataColumn.CLOSE_ADJUSTED
    print(f"  CLOSE = {CLOSE}")

    # 算术组合
    expr1 = CLOSE - OPEN
    assert isinstance(expr1, CompositeExpr)
    assert expr1.op == 'sub'
    print(f"  CLOSE - OPEN = {expr1}")

    # 复合表达式
    expr2 = (CLOSE - OPEN) / (HIGH - LOW + 1e-8)
    assert isinstance(expr2, CompositeExpr)
    assert expr2.op == 'div'
    print(f"  (CLOSE-OPEN)/(HIGH-LOW+eps) = {expr2}")

    # 依赖追踪
    deps = expr2.dependencies
    dep_aliases = {d._get_alias() for d in deps}
    print(f"  Dependencies: {dep_aliases}")
    assert len(deps) >= 2  # 至少包含 CLOSE/OPEN/HIGH/LOW 中的几个

    print("  ✓ 表达式树构建通过\n")


def test_window_operators():
    """测试时序窗口算子。"""
    print("=== 2. 时序窗口算子 ===")

    # MA
    ma_expr = CLOSE.rolling_mean(20)
    assert isinstance(ma_expr, RollingOp)
    assert ma_expr.op == 'rolling_mean'
    assert ma_expr.window == 20
    print(f"  CLOSE.rolling_mean(20) = {ma_expr}")

    # STD
    std_expr = CLOSE.rolling_std(20)
    assert isinstance(std_expr, RollingOp)
    assert std_expr.op == 'rolling_std'
    print(f"  CLOSE.rolling_std(20) = {std_expr}")

    # SHIFT
    shift_expr = CLOSE.shift(5)
    assert isinstance(shift_expr, ShiftOp)
    assert shift_expr.periods == 5
    print(f"  CLOSE.shift(5) = {shift_expr}")

    # DELTA
    delta_expr = CLOSE.delta(5)
    assert isinstance(delta_expr, CompositeExpr)
    assert delta_expr.op == 'sub'
    print(f"  CLOSE.delta(5) = {delta_expr}")

    print("  ✓ 时序窗口算子通过\n")


def test_cross_sectional_operators():
    """测试横截面算子。"""
    print("=== 3. 横截面算子 ===")

    # CS_ZSCORE
    z_expr = CLOSE.cs_zscore()
    assert isinstance(z_expr, CrossSectionalOp)
    assert z_expr.op == 'cs_zscore'
    print(f"  CLOSE.cs_zscore() = {z_expr}")

    # CS_RANK
    rank_expr = CLOSE.cs_rank()
    assert isinstance(rank_expr, CrossSectionalOp)
    assert rank_expr.op == 'cs_rank'
    print(f"  CLOSE.cs_rank() = {rank_expr}")

    print("  ✓ 横截面算子通过\n")


def test_unary_operators():
    """测试一元算子。"""
    print("=== 4. 一元算子 ===")

    # LOG
    log_expr = CLOSE.log()
    assert isinstance(log_expr, UnaryOp)
    print(f"  CLOSE.log() = {log_expr}")

    # ABS
    abs_expr = abs(CLOSE - OPEN)
    assert isinstance(abs_expr, CompositeExpr)
    print(f"  abs(CLOSE-OPEN) = {abs_expr}")

    # NEG
    neg_expr = -CLOSE
    assert isinstance(neg_expr, CompositeExpr)
    print(f"  -CLOSE = {neg_expr}")

    print("  ✓ 一元算子通过\n")


def test_variadic_max_min():
    """测试多元 max/min。"""
    print("=== 5. 多元 max/min ===")

    max_expr = expr_max(HIGH, CLOSE, OPEN)
    print(f"  max(HIGH, CLOSE, OPEN) = {max_expr}")

    min_expr = expr_min(LOW, CLOSE, OPEN)
    print(f"  min(LOW, CLOSE, OPEN) = {min_expr}")

    # 依赖
    deps_max = max_expr.dependencies
    dep_aliases_max = {d._get_alias() for d in deps_max}
    print(f"  max dependencies: {dep_aliases_max}")
    assert len(deps_max) >= 3

    print("  ✓ 多元 max/min 通过\n")


def test_chained_expression():
    """测试链式组合表达式（模拟真实因子）。"""
    print("=== 6. 链式表达式（真实因子模拟）===")

    # 因子 1：日内位置 (close-open)/(high-low)
    intraday_pos = (CLOSE - OPEN) / (HIGH - LOW + 1e-8)

    # 因子 2：价格在 20 日均线上方程度
    ma_break = (CLOSE - CLOSE.rolling_mean(20)) / CLOSE.rolling_std(20)

    # 因子 3：横截面标准化后组合
    combined = intraday_pos.cs_zscore() * 0.5 + ma_break.cs_zscore() * 0.5

    print(f"  intraday_pos = {intraday_pos}")
    print(f"  ma_break = {ma_break}")
    print(f"  combined = {combined}")
    print(f"  combined.dependencies count = {len(combined.dependencies)}")

    # LaTeX
    print(f"  LaTeX: {combined.to_latex()}")

    print("  ✓ 链式表达式通过\n")


def test_const_expr():
    """标量常量。"""
    print("=== 7. 标量参与表达式 ===")

    expr_with_const = CLOSE * 2 - OPEN * 0.5 + 1
    print(f"  CLOSE*2 - OPEN*0.5 + 1 = {expr_with_const}")

    # 反向运算
    rev_expr = 1 - CLOSE / HIGH
    print(f"  1 - CLOSE/HIGH = {rev_expr}")

    print("  ✓ 标量常量通过\n")


# ═════════════════════════════════════════════════════════════════════════════
# 2. 表达式求值测试（使用模拟数据）
# ═════════════════════════════════════════════════════════════════════════════

def create_mock_product(name, n_bars=100):
    """创建模拟品种，返回其 data Meta 对象。"""
    from tools.products.Product import Product

    dates = pd.date_range('2024-01-01', periods=n_bars, freq='min', tz='Asia/Shanghai')
    np.random.seed(hash(name) % 2**31)

    # 模拟价格走势（带趋势+噪声）
    prices = 100 + np.cumsum(np.random.randn(n_bars) * 0.1)

    # DataFreq MIN1 映射
    freq_min1 = DataFreq('1min')
    freq_day1 = DataFreq('1day')

    # 创建简化测试：直接用 Product 子类
    # 由于真实 Product 依赖 DataSource 注册，这里采用 Mock
    class MockProduct:
        def __init__(self, name, data_df):
            self.name = name
            self.alias = name
            self.MIN1 = self._make_mock_meta(data_df, '1min')
            self.DAY1 = self._make_mock_meta(data_df, '1day')

        def _make_mock_meta(self, data_df, freq_name):
            from tools.data.DataMeta import DataMeta
            from tools.base.UniqueObject import UniqueObject

            class MockObj:
                name = 'mock'
                alias = 'mock'

            # 构建数据
            df = data_df.copy()
            df.index = pd.MultiIndex.from_arrays(
                [df.index, df.index],
                names=['DAY1', 'MIN1']
            )

            return type('FakeMeta', (), {
                'name': freq_name,
                'alias': freq_name,
                'get_data': lambda self, copy=False, **kw: df,
                'freq': DataFreq(freq_name),
                'object': MockObj(),
                'original_object': MockObj(),
                'timezone': 'Asia/Shanghai',
                'data': df,
                '__getattr__': lambda self, name: getattr(df, name),
            })()

    df = pd.DataFrame({
        'OA': prices * (1 + np.random.randn(n_bars) * 0.001),   # OPEN_ADJUSTED
        'HA': prices * (1 + np.random.randn(n_bars) * 0.002 + 0.005),  # HIGH_ADJUSTED
        'LA': prices * (1 + np.random.randn(n_bars) * 0.002 - 0.005),  # LOW_ADJUSTED
        'CA': prices,  # CLOSE_ADJUSTED
        'V': np.random.rand(n_bars) * 1000 + 500,  # VOLUME
        'OI': np.cumsum(np.random.randn(n_bars).astype(int) % 50 + 100),  # OPEN_INTEREST
    }, index=dates)

    return MockProduct(name, df)


def test_expression_evaluation():
    """测试表达式求值。"""
    print("=== 8. 表达式求值（模拟数据）===")

    products = [
        create_mock_product('IF', 500),
        create_mock_product('IC', 500),
        create_mock_product('IH', 500),
    ]

    freq = DataFreq('1min')

    # 测试简单列引用
    close_df = CLOSE.evaluate(products, freq)
    assert close_df.shape == (500, 3)
    assert list(close_df.columns) == products
    print(f"  CLOSE shape: {close_df.shape}")

    # 测试算术
    o_c = (OPEN - CLOSE).evaluate(products, freq)
    assert o_c.shape == (500, 3)
    print(f"  OPEN-CLOSE shape: {o_c.shape}")

    # 测试窗口操作
    ma20 = CLOSE.rolling_mean(20).evaluate(products, freq)
    assert ma20.shape == (500, 3)
    print(f"  CLOSE.rolling_mean(20) shape: {ma20.shape}")

    # 测试横截面
    cs_z = CLOSE.cs_zscore().evaluate(products, freq)
    assert cs_z.shape == (500, 3)
    # 每行均值应接近 0
    mean_by_row = cs_z.mean(axis=1).abs().mean()
    assert mean_by_row < 0.1, f"cs_zscore mean should be ~0, got {mean_by_row:.4f}"
    # 每行 std 应接近 1
    std_by_row = cs_z.std(axis=1).mean()
    assert abs(std_by_row - 1.0) < 0.2, f"cs_zscore std should be ~1, got {std_by_row:.4f}"
    print(f"  CLOSE.cs_zscore() row_mean={mean_by_row:.6f}, row_std={std_by_row:.4f}")

    # 测试复杂表达式
    expr = (CLOSE - CLOSE.rolling_mean(20)) / (CLOSE.rolling_std(20) + 1e-8)
    result = expr.evaluate(products, freq)
    assert result.shape == (500, 3)
    # 不应有全 NaN 列
    assert not result.isna().all().any()
    print(f"  (CLOSE-MA20)/STD20 shape: {result.shape}")

    print("  ✓ 表达式求值通过\n")


def test_cache_reuse():
    """测试求值缓存：同一表达式不重复计算。"""
    print("=== 9. 求值缓存 ===")

    products = [
        create_mock_product('IF', 300),
        create_mock_product('IC', 300),
    ]
    freq = DataFreq('1min')

    # 带缓存的求值
    cache = {}
    result1 = CLOSE.evaluate(products, freq, cache=cache)
    result2 = CLOSE.evaluate(products, freq, cache=cache)

    # 第二次应从缓存返回
    assert result1 is result2
    assert CLOSE in cache
    print(f"  Cache hit: result1 is result2 = {result1 is result2}")

    # 依赖缓存：表达式求值时，子表达式也被缓存
    cache2 = {}
    expr = CLOSE.rolling_mean(10)
    result3 = expr.evaluate(products, freq, cache=cache2)
    # CLOSE 应该在缓存中（被 expr 的递归求值自动缓存）
    print(f"  After evaluate: CLOSE in cache = {CLOSE in cache2}")
    print(f"  After evaluate: rolling_mean(10) in cache = {expr in cache2}")

    print("  ✓ 求值缓存通过\n")


# ═════════════════════════════════════════════════════════════════════════════
# 3. ExprFactorFamily 测试
# ═════════════════════════════════════════════════════════════════════════════

def test_expr_factor_family():
    """测试 ExprFactorFamily 整合。"""
    print("=== 10. ExprFactorFamily 整合 ===")

    from tools.factors.FactorFamily import FactorFamily, make_factor_family

    # 定义表达式：日内位置因子
    expr = (CLOSE - OPEN) / (HIGH - LOW + 1e-8)

    # 创建因子族
    family = ExprFactorFamily(
        alias='IntradayPosition',
        expr=expr,
        chinese_name='日内位置因子',
        source_freq='MIN1',
    )

    print(f"  family.name = {family.name}")
    print(f"  family.alias = {family.alias}")
    print(f"  family.chinese_name = {family.chinese_name}")
    print(f"  family.math_expr = {family.math_expr}")

    # 获取因子
    factor = family.get_factor()
    print(f"  factor.name = {factor.name}")
    print(f"  factor.alias = {factor.alias}")
    assert factor.family is family

    # 快捷创建
    family2 = make_factor_family(
        'MaBreak',
        (CLOSE - CLOSE.rolling_mean(20)) / CLOSE.rolling_std(20),
        chinese_name='均线突破',
        source_freq='DAY1',
    )
    print(f"  family2.alias = {family2.alias}")
    print(f"  family2.math_expr = {family2.math_expr}")

    print("  ✓ FactorFamily 整合通过\n")


# ═════════════════════════════════════════════════════════════════════════════
# 4. LaTeX 生成测试
# ═════════════════════════════════════════════════════════════════════════════

def test_latex_generation():
    """测试 LaTeX 表达式生成。"""
    print("=== 11. LaTeX 生成 ===")

    # 简单
    print(f"  CLOSE: {CLOSE.to_latex()}")
    print(f"  CLOSE - OPEN: {(CLOSE - OPEN).to_latex()}")
    print(f"  CLOSE / OPEN: {(CLOSE / OPEN).to_latex()}")

    # 复合
    expr = (CLOSE - CLOSE.rolling_mean(20)) / CLOSE.rolling_std(20)
    print(f"  (CLOSE-MA20)/STD20: {expr.to_latex()}")

    # max/min
    print(f"  max(HIGH, CLOSE): {expr_max(HIGH, CLOSE).to_latex()}")

    print("  ✓ LaTeX 生成通过\n")


def test_latex_parenthesis_rules():
    """检验二元算子在 LaTeX 中的括号规则。"""
    mul_add = ((CLOSE + OPEN) * HIGH).to_latex()
    assert '\\left(' in mul_add and '\\right)' in mul_add

    mul_div = (CLOSE * (OPEN / HIGH)).to_latex()
    assert '\\left(\\frac' in mul_div

    sub_add = (CLOSE - (OPEN + HIGH)).to_latex()
    assert '\\left(' in sub_add and '\\right)' in sub_add

    pow_add = ((CLOSE + OPEN) ** 2).to_latex()
    assert '\\left(' in pow_add and ' ^ ' in pow_add


# ═════════════════════════════════════════════════════════════════════════════
# 12. Parameter 依赖追踪 (param_deps) 测试
# ═════════════════════════════════════════════════════════════════════════════

def test_param_deps():
    """测试 param_deps 在各节点中的正确传播。"""
    print("=== 12. Parameter 依赖追踪 ===")

    W = WindowParam('W', 10)

    # 1. 叶子节点
    assert CLOSE.param_deps == set(), "ColumnRef should have no param_deps"
    assert ConstExpr(5).param_deps == set(), "ConstExpr should have no param_deps"

    ref = ParamRef(W)
    assert ref.param_deps == {W}, f"ParamRef should track W, got {ref.param_deps}"
    print(f"  Leaf nodes: OK")

    # 2. UnaryOp / ShiftOp / CrossSectionalOp — 透传 operand 的 param_deps
    op_with_param = UnaryOp('log', ref)
    assert op_with_param.param_deps == {W}, "UnaryOp should pass through param_deps"

    shift_with_param = ShiftOp('shift', ref, 1)
    assert shift_with_param.param_deps == {W}, "ShiftOp should pass through param_deps"

    cs_with_param = CrossSectionalOp('cs_zscore', ref)
    assert cs_with_param.param_deps == {W}, "CrossSectionalOp should pass through param_deps"
    print(f"  Unary/Shift/CS passthrough: OK")

    # 3. RollingOp — operand 的 param_deps + 自身的 Parameter window
    ma_with_param = CLOSE.rolling_mean(W)
    assert ma_with_param.param_deps == {W}, f"RollingOp(W) should have W, got {ma_with_param.param_deps}"

    ma_no_param = CLOSE.rolling_mean(20)
    assert ma_no_param.param_deps == set(), "RollingOp(20) should have no param_deps"
    print(f"  RollingOp tracking: OK")

    # 4. CompositeExpr — 聚合所有 operand 的 param_deps
    simple = CLOSE - OPEN
    assert simple.param_deps == set(), "Pure expression should have no param_deps"

    with_param = (CLOSE - CLOSE.rolling_mean(W)) / CLOSE.rolling_std(W)
    assert with_param.param_deps == {W}, f"Composite should aggregate W, got {with_param.param_deps}"

    W2 = WindowParam('W2', 5)
    multi_param = CLOSE.rolling_mean(W) + CLOSE.rolling_std(W2)
    assert multi_param.param_deps == {W, W2}, f"Should track both W and W2, got {multi_param.param_deps}"
    print(f"  CompositeExpr aggregation: OK")

    # 5. dependencies 和 param_deps 独立
    deps_count = len(multi_param.dependencies)
    param_count = len(multi_param.param_deps)
    print(f"  deps count={deps_count}, param_deps count={param_count} (independent systems)")

    print("  ✓ Parameter 依赖追踪通过\n")


# ═════════════════════════════════════════════════════════════════════════════
# 13. Parameter 解析 (ExprFactorFamily._resolve_expr_params) 测试
# ═════════════════════════════════════════════════════════════════════════════

def test_param_resolve():
    """测试 ExprFactorFamily 的 param 解析过程。"""
    print("=== 13. Parameter 解析 ===")

    from tools.factors.ExprFactorFamily import ExprFactorFamily

    W = WindowParam('W', 10)
    expr = (CLOSE - CLOSE.rolling_mean(W)) / CLOSE.rolling_std(W)
    family = FactorFamily('TestParamResolve', expr, source_freq='1min')

    # 1. 解析前：window 是 Parameter
    # expr = (CLOSE - rolling_mean(CLOSE,W)) / rolling_std(CLOSE,W)
    # operands[1] = rolling_std(CLOSE,W) 即 RollingOp —— 直接是 RollingOp
    std_op = family._expr.operands[1]
    assert isinstance(std_op, RollingOp)
    from tools.parameters.Parameter import Parameter
    assert isinstance(std_op.window, Parameter), \
        f"Before resolve: window should be Parameter, got {type(std_op.window)}"
    print(f"  Before resolve: window type = {type(std_op.window).__name__}")

    # 2. 解析后：window 被替换为 int
    resolved = family._resolve_expr_params(family._expr)
    rw = resolved.operands[1]
    assert isinstance(rw, RollingOp)
    assert rw.window == 10, f"After resolve: window should be 10, got {rw.window}"
    assert isinstance(rw.window, int), \
        f"After resolve: window should be int, got {type(rw.window)}"
    print(f"  After resolve: window = {rw.window} (type={type(rw.window).__name__})")

    # 3. 解析后可以求值
    products = [
        create_mock_product('IF', 200),
        create_mock_product('IC', 200),
    ]
    freq = DataFreq(family._source_freq_name)
    res = resolved.evaluate(products, freq)
    assert res.shape == (200, 2), f"Expected (200,2), got {res.shape}"
    print(f"  Resolved evaluate shape: {res.shape} OK")

    # 4. 单产品 evaluate 也能工作
    single_res = resolved.evaluate([products[0]], freq)
    print(f"  Single product evaluate shape: {single_res.shape} OK")

    # 5. 原始表达式不变（不修改原始树）
    std_op2 = family._expr.operands[1]
    assert isinstance(std_op2.window, Parameter), \
        "Original expression should NOT be mutated by resolve"
    print(f"  Immutability: original window still Parameter ✓")

    print("  ✓ Parameter 解析通过\n")


# ═════════════════════════════════════════════════════════════════════════════
# RUN
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    test_expression_construction()
    test_window_operators()
    test_cross_sectional_operators()
    test_unary_operators()
    test_variadic_max_min()
    test_chained_expression()
    test_const_expr()
    test_expression_evaluation()
    test_cache_reuse()
    test_expr_factor_family()
    test_latex_generation()
    test_param_deps()
    test_param_resolve()

    print("\n" + "=" * 60)
    print("  全部测试通过! ✓")
    print("=" * 60)
