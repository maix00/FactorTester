# =============================================================================
# Factors/MmOvernightTrend.py
# 隔夜趋势因子
#
# 过去 N 个交易日隔夜涨幅（今开/昨收 - 1）的均值：
#   X_t = (1/N) * Σ (O_s - C_{s-1}) / C_{s-1}
# 正值意味着近期夜盘持续跳高，负值意味着近期夜盘持续跳低。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmOvernightTrend(FactorFamily):
    """
    隔夜趋势因子。

    计算过去 N 个交易日每日开盘价相对前日收盘价的涨幅均值，
    反映夜盘或隔夜信息对价格的系统性推动方向。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '隔夜趋势'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmOvernightTrend 是隔夜趋势因子，计算最近 N 个交易日每天的隔夜涨幅（今日开盘价相对昨日收盘价的变化）均值，刻画非交易时段信息的净方向性贡献。',
        },
        {
            'title': '它在看什么',
            'body': '它回答"最近的行情是主要由夜盘信息驱动，还是在日内消化"。连续多天跳高开盘说明场外资金持续在非交易时段推升价格；连续跳低开盘则相反。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '隔夜收益和日内收益在来源上有本质区别：隔夜收益通常由宏观事件、海外市场联动或大资金预判驱动，而日内收益更受日内流动性和博弈影响。分离这两个成分，能更精确地判断趋势来源，并对不同驱动力下的持续性做出更准确的预判。',
        },
        {
            'title': '使用提醒',
            'body': '隔夜跳空幅度受样本内外市场冲击影响大，极端单日跳空会严重拉偏均值；建议配合去极值或中位数版本使用。夜盘交易量相对日盘可能存在差异，部分品种的夜盘价格代表性不同。',
        },
        {
            'title': '反转信号',
            'body': '连续多日大幅跳高后，若日内出现持续回落（日内收益与隔夜收益持续背离），说明市场在消化夜盘溢价，反转压力积累；隔夜趋势从持续正值快速转为负值（跳高消失甚至开始跳低），是日内动量方向改变的前奏，此时应减少趋势头寸暴露。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r^{ON}_s &:= \frac{O_s - C_{s-1}}{C_{s-1}}, \\[4pt]
            X_t      &:= \frac{1}{N}\sum_{s=t-N+1}^{t} r^{ON}_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        daily_open  = product.DAY1[DataColumn.OPEN]
        daily_close = product.DAY1[DataColumn.CLOSE]

        prev_close = daily_close.shift(1)
        overnight_ret = (daily_open - prev_close) / prev_close.replace(0, float('nan'))
        factor = overnight_ret.rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmOvernightTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
