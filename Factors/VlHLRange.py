# =============================================================================
# Factors/VlHLRange.py
# 日内高低价幅度因子
#
# N 期滚动的日内振幅均值，归一化为价格百分比：
#   HL_t = (H_t - L_t) / ((H_t + L_t) / 2)
#   X_t = MA(HL, N)
# 反映市场的日内波动强度，高值常见于趋势转折或消息冲击期。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VlHLRange(FactorFamily):
    """
    日内高低价幅度因子（High-Low Range）。

    计算每期高低价幅度相对于中间价的百分比，
    在 N 期窗口内取均值，衡量日内波动的持续强度。

    参数：
        N (Timedelta) : 滚动均值窗口，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = '高低点区间比'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlHLRange 是高低振幅因子，用每期高低价差相对价格中枢的比例来度量市场的日内或周期内波动幅度。',
        },
        {
            'title': '它在看什么',
            'body': '高低价差越大，说明这一期价格分歧越大、波动越剧烈。滚动均值后，它可以表示近期“典型振幅”处在什么水平。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '高低振幅直接反映了市场在一个周期内的争夺强度。趋势爆发、消息冲击、止损踩踏和流动性下降，往往都会先体现在振幅扩张上。这个量虽然简单，但对捕捉状态切换很有效。',
        },
        {
            'title': '使用提醒',
            'body': '与 ATR 相比，它对跳空不敏感；因此若市场经常跨时段大幅跳动，单独使用 HLRange 会低估真实风险。',
        },
        {
            'title': '反转信号',
            'body': '高低点区间因子（归一化日内/窗口波动幅度）的反转逻辑：（1）HL 区间占价格比例急速扩大（如涨停或暴跌日），随后连续多期迅速收窄，是"震荡后方向选择"的前兆；（2）长时间低波动区间（HL 区间持续窄压）后突破，往往是方向性启动而非反转——此时已有趋势信号的话，延续概率更高；（3）区间在高价位持续扩大（价格横盘但波动加大）意味着多空分歧严重，更容易出现急速下行反转。反转在以下情况更有效：高 HL 区间伴随成交量下降（大幅波动无真实交投支撑）；或区间扩大的位置位于历史强阻力/强支撑附近。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            HL_t &:= \frac{H_t - L_t}{(H_t + L_t) / 2} \\[5pt]
            X_t  &:= MA(HL,\, N)_t
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high = product.MIN1[DataColumn.HIGH]
        low  = product.MIN1[DataColumn.LOW]
        mid  = ((high + low) / 2.0).replace(0, float('nan'))
        hl_range = (high - low) / mid
        factor = hl_range.rolling(N).mean()
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = VlHLRange()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    ff.add_params(F='1d', N='5d')
    ff.add_params(F='1d', N='20d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
