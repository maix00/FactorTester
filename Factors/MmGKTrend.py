# =============================================================================
# Factors/MmGKTrend.py
# 日内 GK 波动趋势因子
#
# 过去 N 个交易日，GK 波动量乘以日内方向的均值：
#   direction_s = sign(C_s - O_s)
#   GK_s = Garman-Klass 单 Bar 估计量
#   X_t = (1/N) * Σ direction_s * GK_s
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmGKTrend(FactorFamily):
    """
    日内 GK 波动趋势因子。

    将 Garman-Klass 单日波动估计量乘以日内方向后求 N 日均值。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = 'GK 波动趋势'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmGKTrend 是日内 GK 波动趋势因子，将 Garman-Klass 单日波动量乘以当日收相对开的方向（涨为正，跌为负），在 N 日内求均值，是 MmRSTrend 的 GK 版替代。',
        },
        {
            'title': '它在看什么',
            'body': '利用 GK 估计量（包含开收价信息的高效估计量）来度量每日的"有方向波动强度"，在有明确趋势的环境中比纯 RS 版本的偏差更小。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': 'GK 估计量同时考虑了高低点区间（代表日内随机游走）和开收价差（代表方向性漂移），因此它的"方向波动乘积"比只用区间的 Parkinson 版本更能区分路径结构与噪声。',
        },
        {
            'title': '使用提醒',
            'body': 'GK 假设无隔夜跳空，夜盘跳空活跃的品种会低估波动；因此在有夜盘且活跃的期货品种上，YZ 趋势因子（MmYZTrend）通常更准确。',
        },
        {
            'title': '反转信号',
            'body': '与 MmRSTrend 相似，GK 趋势因子从极端正值开始快速回落，尤其是伴随日内振幅收窄，是动能减弱的明确信号。GK 和 RS 趋势因子同时反向，信号可靠性更高；两者背离时，应优先参考 YZ 趋势因子。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            GK_s &:= \tfrac{1}{2}\ln\!\left(\tfrac{H_s}{L_s}\right)^2
                     - (2\ln 2 - 1)\ln\!\left(\tfrac{C_s}{O_s}\right)^2, \\[4pt]
            X_t  &:= \frac{1}{N}\sum_{s=t-N+1}^{t} \text{sign}(C_s - O_s)\cdot GK_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH]
        low   = product.DAY1[DataColumn.LOW]
        open_ = product.DAY1[DataColumn.OPEN]
        close = product.DAY1[DataColumn.CLOSE]

        eps = 1e-10
        hl = np.log((high / (low   + eps).replace(0, eps)).clip(lower=eps))
        co = np.log((close / (open_ + eps).replace(0, eps)).clip(lower=eps))

        gk_bar    = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
        direction = (close - open_).apply(np.sign)
        factor    = (direction * gk_bar).rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmGKTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
