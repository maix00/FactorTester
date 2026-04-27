# =============================================================================
# Factors/MmClose2High.py
# 收盘价相对高点位置因子
#
# 在过去 N 的窗口内，收盘价相对于最高价与最低价区间的位置：
#   X_t = (C_t - min(L, N)) / (max(H, N) - min(L, N))
# 即 Williams %R 的正值化版本，值域 [0, 1]。
# 高值（接近1）表示收盘价接近 N 期高点，低值接近低点。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmClose2High(FactorFamily):
    """
    收盘价相对高低点位置因子（Williams %R 正值化）。

    在 N 期窗口内，当前收盘价处于最高价与最低价区间的百分位位置。
    等价于 1 + Williams %R / 100。

    参数：
        N (Timedelta) : 滚动窗口长度，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = '收盘价区间位置'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmClose2High 是一个区间位置因子，用来衡量当前收盘价在最近一段高低区间中的相对位置。',
        },
        {
            'title': '它在看什么',
            'body': '如果收盘价靠近区间最高点，因子会接近 1；如果更靠近区间最低点，因子会接近 0。它不直接关心这段时间涨了多少，而是关心价格现在处在近期交易区间的哪个位置。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '价格长期贴近区间上沿，往往意味着买盘在持续抬高成交重心，市场更像在高位换手而不是高位被砸；反之，长期贴近区间下沿则意味着承接偏弱。这个“区间驻留位置”信息常能补充纯收益率动量看不到的强弱差异。',
        },
        {
            'title': '使用提醒',
            'body': '若近期区间非常窄，因子会对微小价格变动非常敏感；若区间过宽，又会降低当前价格位置的解释力。',
        },
        {
            'title': '反转信号',
            'body': '当因子值长期维持在高位（接近 1）或低位（接近 0）后，出现以下迹象时反转概率上升：（1）最新 K 线无法再突破区间高点，但 Close2High 仍然高——即上影线变长、实体缩短；（2）成交量在高位收缩，说明推动价格靠近高点的力量减弱；（3）市场处于关键阻力/支撑附近，历史上多次在此价位出现拐点。区间越窄、因子值越极端，反转弹性通常越明显；区间很宽时，价格靠近高位本身未必意味着透支。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            H_t^{(N)} &:= \mathrm{RollingMax}_{N}(H)_t,\quad L_t^{(N)} := \mathrm{RollingMin}_{N}(L)_t \\[4pt]
            X_t &:= \frac{C_t - L_t^{(N)}}{H_t^{(N)} - L_t^{(N)}}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.MIN1[DataColumn.HIGH_ADJUSTED]
        low   = product.MIN1[DataColumn.LOW_ADJUSTED]
        close = product.MIN1[DataColumn.CLOSE_ADJUSTED]
        highest = high.rolling(N).max()
        lowest  = low.rolling(N).min()
        rng = (highest - lowest).replace(0, float('nan'))
        factor = (close - lowest) / rng
        factor = factor.fillna(0.5)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = MmClose2High()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    ff.add_params(F='1d', N='5d')
    ff.add_params(F='1d', N='20d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
