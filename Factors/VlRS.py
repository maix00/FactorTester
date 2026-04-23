# =============================================================================
# Factors/VlRS.py
# Rogers-Satchell 波动率因子
#
# 使用 OHLC 四价计算无漂移估计量：
#   RS_bar = log(H/C)*log(H/O) + log(L/C)*log(L/O)
#   X_t = sqrt((1/N) * sum(RS_bar))
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VlRS(FactorFamily):
    """
    Rogers-Satchell 波动率因子。

    不需要假设零漂移，能在有趋势的市场中更准确地估计波动率。

    参数：
        N (Timedelta) : 滚动窗口，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = 'Rogers-Satchell 波动率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlRS 是 Rogers-Satchell 波动率估计量，利用每个 OHLC Bar 的四个价格计算波动，无需假设市场无漂移，在趋势市场中比 Parkinson 估计量更准确。',
        },
        {
            'title': '它在看什么',
            'body': '它将高价相对开盘和收盘的位置、以及低价相对开盘和收盘的位置联合起来，合成为一个无偏的单 Bar 方差估计量，再在 N 个 Bar 上求平均后开根号得到波动率。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '相比单纯用高低点范围（Parkinson），RS 利用了开收价的相对位置信息，能区分"区间大但属于来回震荡"和"区间大且方向明确"两种情况，提供更精细的波动率估计。',
        },
        {
            'title': '使用提醒',
            'body': '在极端窗口（N 很小）时方差估计不稳定；该因子对跳空 Bar 中的开盘价误差较敏感。',
        },
        {
            'title': '反转信号',
            'body': 'RS 波动率急速上升后，市场方向不确定性大幅增加，原有趋势容易被打断；RS 从高位开始持续回落（3 期以上），通常意味着波动率环境趋于稳定，方向性信号可靠性恢复。在 RS 极端高位后的第一个明显缩量收窄，是等待方向确认的时机而不是追趋势的时机。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            RS_t &:= \ln\!\left(\tfrac{H_t}{C_t}\right)\cdot\ln\!\left(\tfrac{H_t}{O_t}\right)
                    + \ln\!\left(\tfrac{L_t}{C_t}\right)\cdot\ln\!\left(\tfrac{L_t}{O_t}\right),\\[4pt]
            X_t  &:= \sqrt{\frac{1}{N}\sum_{s=t-N+1}^{t} RS_s}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH]
        low   = product.DAY1[DataColumn.LOW]
        open_ = product.DAY1[DataColumn.OPEN]
        close = product.DAY1[DataColumn.CLOSE]

        eps = 1e-10
        ho = np.log((high / (open_  + eps).replace(0, eps)).clip(lower=eps))
        hc = np.log((high / (close + eps).replace(0, eps)).clip(lower=eps))
        lo = np.log((low  / (open_  + eps).replace(0, eps)).clip(lower=eps))
        lc = np.log((low  / (close + eps).replace(0, eps)).clip(lower=eps))

        rs_bar = hc * ho + lc * lo
        rs_var = rs_bar.rolling(N).mean().clip(lower=0.0)
        rs_vol = rs_var.apply(np.sqrt)

        return self.sync_signal(rs_vol.fillna(0.0))

if __name__ == '__main__':
    ff = VlRS()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
