# =============================================================================
# Factors/MmDMI.py
# 趋向指标因子（DMI / DX）
#
# 基于 True Range 与方向运动：
#   TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
#   +DM_t = max(H_t - H_{t-1}, 0) if H_t-H_{t-1} > L_{t-1}-L_t else 0
#   -DM_t = max(L_{t-1} - L_t, 0) if L_{t-1}-L_t > H_t-H_{t-1} else 0
#   +DI_t = 100 * Σ+DM / ΣTR  (N 期)
#   -DI_t = 100 * Σ-DM / ΣTR
#   X_t = (+DI_t - -DI_t) / (+DI_t + -DI_t)  ∈ (-1, 1)
# =============================================================================
import pandas as pd
import numpy as np
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmDMI(FactorFamily):
    """
    趋向指标因子（Directional Movement Index）。

    计算正向方向指数（+DI）和负向方向指数（-DI）之差相对之和的比值，
    反映价格趋势的方向强度。

    参数：
        N  (Timedelta) : 滚动窗口，默认 14d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = '方向性动量指标'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmDMI 是方向性动量因子，源自 DMI/DI 体系。它把向上运动和向下运动分别提取出来，并用真实波动范围做标准化，衡量一段时间内到底是哪一侧的方向性推进更强。',
        },
        {
            'title': '它在看什么',
            'body': '当正向方向运动持续强于负向方向运动时，因子会上升；反之则下降。这个构造强调的是“净方向性”，而不是单纯的涨跌幅，因为它会把日内高低点扩张和跳空等信息也纳入考量。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '有效趋势通常不仅体现为收盘价变动，还体现为高点不断抬升、低点同步上移。DMI 类指标正是试图分离这种方向性推进与普通噪声波动，因此常能更稳定地区分“有方向的趋势”与“无方向的高波动”。',
        },
        {
            'title': '使用提醒',
            'body': 'DMI 在高波动震荡环境中可能反复来回切换，需要配合更慢的趋势过滤或交易拥挤度指标来降低假信号。',
        },
        {
            'title': '反转信号',
            'body': '当 +DI 和 -DI 之差（即本因子）从极端值开始收敛时，往往是趋势衰竭和反转的早期信号：（1）ADX 类指标（若有）开始拐头向下，方向性强度下降；（2）+DI 和 -DI 完成交叉（多翻空或空翻多）是传统反转/趋势切换信号；（3）在高波动但成交量下降的状态下，DMI 的方向性信号可靠性下降，此时反转更容易发生。反转在均值回归市场和区间震荡行情中更有效；在单边期货行情中因子延续性更强，反转更值得谨慎对待。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{(+DI_t) - (-DI_t)}{(+DI_t) + (-DI_t)}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high  = product.MIN1[DataColumn.HIGH]
        low   = product.MIN1[DataColumn.LOW]
        close = product.MIN1[DataColumn.CLOSE]

        prev_high  = high.shift(1)
        prev_low   = low.shift(1)
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low  - prev_close).abs()
        tr = tr1.where(tr1 >= tr2, tr2)
        tr = tr.where(tr >= tr3, tr3)

        up_move   = high - prev_high
        down_move = prev_low - low
        pdm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        ndm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        pdm = pd.Series(pdm, index=high.index)
        ndm = pd.Series(ndm, index=high.index)

        tr_sum  = tr.rolling(N).sum()
        pdi = 100.0 * pdm.rolling(N).sum() / tr_sum.replace(0, float('nan'))
        ndi = 100.0 * ndm.rolling(N).sum() / tr_sum.replace(0, float('nan'))

        dsum = (pdi + ndi).replace(0, float('nan'))
        dx = (pdi - ndi) / dsum
        dx = dx.fillna(0.0)
        return self.sync_signal(dx)
    
if __name__ == '__main__':
    ff = MmDMI()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    ff.add_params(F='1d', N='7d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
