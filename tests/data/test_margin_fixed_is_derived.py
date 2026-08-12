"""
验证 margin_fixed 字段（交易所原始列）是否恒为 0，以及
计算保证金（做多1手保证金）是否等于 最新价 × 合约乘数 × 保证金率。

OpenCTP 表格中：
  col 5  = 合约乘数 (multiplier)
  col 13 = 做多保证金率 (long_margin_ratio)
  col 14 = 做多保证金/手 (long_margin_fixed) ← 交易所原始列
  col 19 = 最新价 (price)
  col 25 = 做多1手保证金 (计算列)
  col 27 = 1手市值 (latest_price × multiplier)

如果 col 14 恒为 0 且 col 25 ≡ col 27 × col 13，
则 simulate_groups 只需要 margin_ratio_mat，不需要 margin_fixed_mat。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _fetch_openctp() -> pd.DataFrame:
    url = 'http://openctp.cn/fees.html'
    try:
        tables = pd.read_html(url, flavor='html5lib')
    except Exception as exc:  # external integration source is optional
        pytest.skip(f"OpenCTP fee table unavailable: {type(exc).__name__}")
    return max(tables, key=lambda t: len(t))


def test_margin_fixed_is_always_zero():
    """验证交易所原始列 '做多保证金/手' 在所有品种中恒为 0。"""
    raw = _fetch_openctp()
    # col 14 = 做多保证金/手 (交易所原始)
    long_fixed = pd.to_numeric(raw.iloc[:, 14], errors='coerce')
    # col 16 = 做空保证金/手 (交易所原始)
    short_fixed = pd.to_numeric(raw.iloc[:, 16], errors='coerce')

    non_zero_long = (long_fixed > 0).sum()
    non_zero_short = (short_fixed > 0).sum()

    assert non_zero_long == 0, f"'做多保证金/手' 有 {non_zero_long} 行非零"
    assert non_zero_short == 0, f"'做空保证金/手' 有 {non_zero_short} 行非零"


def test_calculated_margin_equals_market_value_times_ratio():
    """验证 做多1手保证金(计算列) ≡ 1手市值 × 做多保证金率。"""
    raw = _fetch_openctp()

    # col 13 = 做多保证金率, col 25 = 做多1手保证金(计算列), col 27 = 1手市值
    ratio = pd.to_numeric(raw.iloc[:, 13], errors='coerce')
    calc_margin = pd.to_numeric(raw.iloc[:, 25], errors='coerce')
    mv = pd.to_numeric(raw.iloc[:, 27], errors='coerce')

    mask = (ratio > 0) & (calc_margin > 0) & (mv > 0)
    assert mask.sum() > 0, "没有有效数据行"

    expected = mv[mask].values * ratio[mask].values
    actual = calc_margin[mask].values

    # 允许 0.05 元浮点误差 (1手市值×保证金率的四舍五入)
    abs_diff = np.abs(expected - actual)
    max_abs_diff = abs_diff.max()
    assert max_abs_diff < 0.1, (
        f"计算保证金与 市值×保证金率 最大偏差为 {max_abs_diff}，应精确匹配"
    )

    # 确保至少有足够样本
    assert mask.sum() >= 100, f"样本量不足: {mask.sum()}"


def test_one_tick_pnl_equals_multiplier_times_min_tick():
    """验证 1Tick 盈亏由合约乘数 × 最小跳动决定，不是最小交易手数。"""
    raw = _fetch_openctp()

    multiplier = pd.to_numeric(raw.iloc[:, 5], errors='coerce')
    min_tick = pd.to_numeric(raw.iloc[:, 6], errors='coerce')
    one_tick_pnl = pd.to_numeric(raw.iloc[:, 28], errors='coerce')

    mask = (multiplier > 0) & (min_tick > 0) & (one_tick_pnl > 0)
    assert mask.sum() > 0, "没有有效 1Tick 样本"

    expected = multiplier[mask].values * min_tick[mask].values
    actual = one_tick_pnl[mask].values
    np.testing.assert_allclose(actual, expected, atol=1e-10)


if __name__ == '__main__':
    test_margin_fixed_is_always_zero()
    print("✓ test_margin_fixed_is_always_zero passed")
    test_calculated_margin_equals_market_value_times_ratio()
    print("✓ test_calculated_margin_equals_market_value_times_ratio passed")
