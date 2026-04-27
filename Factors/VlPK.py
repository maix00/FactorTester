# =============================================================================
# Factors/VlPK.py
# Parkinson 波动率因子
#
# 只用日内高低点估计波动率：
#   PK_bar = ln(H/L)^2 / (4*ln2)
#   X_t = sqrt((1/N) * sum(PK_bar))
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VlPK(FactorFamily):
    """
    Parkinson 波动率因子。

    仅使用高低点区间估计波动率，统计效率约为收益率估计量的 5 倍。

    参数：
        N (Timedelta) : 滚动窗口，默认 14d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='14d'),
    ]

    chinese_name = 'Parkinson 波动率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlPK 是 Parkinson 波动率估计量，仅使用每个 Bar 的最高价和最低价，不依赖开盘价和收盘价，是最简单有效的 OHLC 波动率估计方法之一。',
        },
        {
            'title': '它在看什么',
            'body': '它衡量的是每个 Bar 内价格的极值跨度。高低点差距越大，Parkinson 波动率越高，反映了该 Bar 内市场参与者的最大分歧程度。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '高低点范围包含了日内所有过渡价格的信息，比收盘价更难被操纵，也比收益率更少受到均值回归噪声的影响。它对于那些收盘价接近开盘价但日内振幅巨大的"十字星"行情格外敏感。',
        },
        {
            'title': '使用提醒',
            'body': 'Parkinson 估计量假设价格无漂移，在单边趋势市场中会系统性低估波动率；对隔夜跳空也无法捕捉。',
        },
        {
            'title': '反转信号',
            'body': 'Parkinson 波动率连续扩大后出现"上影线/下影线很长但实体很短"的 Bar（即同等 H-L 但 C 和 O 更接近），说明虽然波动率高但参与者方向共识开始收敛，此时博反转的条件正在积累；Parkinson 处于历史低位但价格逼近前期高/低点，突破后的方向性持续概率更高。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            PK_t &:= \frac{\ln\!\left(\tfrac{H_t}{L_t}\right)^2}{4\ln 2},\\[4pt]
            X_t  &:= \sqrt{\frac{1}{N}\sum_{s=t-N+1}^{t} PK_s}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('14d'), **kwargs) -> pd.Series:
        high = product.DAY1[DataColumn.HIGH_ADJUSTED]
        low  = product.DAY1[DataColumn.LOW_ADJUSTED]

        eps = 1e-10
        hl = np.log((high / (low + eps).replace(0, eps)).clip(lower=eps))
        pk_bar = hl ** 2 / (4 * np.log(2))
        pk_var = pk_bar.rolling(N).mean().clip(lower=0.0)
        pk_vol = pk_var.apply(np.sqrt)

        return self.sync_signal(pk_vol.fillna(0.0))

if __name__ == '__main__':
    ff = VlPK()
    ff.clear_params()
    ff.add_params(F='1d', N='14d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
