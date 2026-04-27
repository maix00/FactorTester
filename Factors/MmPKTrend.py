# =============================================================================
# Factors/MmPKTrend.py
# 日内 PK 波动趋势因子
#
# 过去 N 个交易日，Parkinson 波动量乘以日内方向的均值：
#   direction_s = sign(C_s - O_s)
#   PK_s = log(H_s/L_s)^2 / (4*ln2)
#   X_t = (1/N) * Σ direction_s * PK_s
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmPKTrend(FactorFamily):
    """
    日内 PK 波动趋势因子。

    将 Parkinson 单日波动估计量乘以日内方向后求 N 日均值，
    是实现最简单的趋势-波动复合因子。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = 'PK 波动趋势'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmPKTrend 是日内 PK 波动趋势因子，用最简单的 Parkinson 高低点区间波动量（仅用 H 和 L）乘以日内方向，再做 N 日均值，是趋势-波动结合型因子中构造最简洁的版本。',
        },
        {
            'title': '它在看什么',
            'body': '它专注于"带方向的日内极值区间"，如果近期多数上涨日伴随宽幅振荡，因子偏正；多数下跌日伴随宽幅振荡，因子偏负；振幅很小或涨跌各半，因子接近 0。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '高低点区间是最难被人为操纵的价格信息（改变极值需要真实成交），因此 Parkinson 趋势因子对高频价格操纵的鲁棒性强。在数据质量有限的场景下，PK 趋势比 GK/RS/YZ 更稳定可靠。',
        },
        {
            'title': '使用提醒',
            'body': 'Parkinson 估计量假设无漂移，在有强趋势的日内走势中会低估方向性波动，因此 PK 趋势因子的绝对值通常低于 RS 或 GK 趋势因子；建议引用时结合标准化处理（如 z-score）。',
        },
        {
            'title': '反转信号',
            'body': '当 PK 趋势因子在高位连续平稳（不再创新高）但同期 GK/RS 趋势继续上升，说明高低点区间（日内范围）开始收窄，而开收方向性仍在推进，这是趋势从" 扩张期"进入"惯性期"的过渡——此时追趋势的性价比下降，反转概率上升。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            PK_s &:= \frac{\ln\!\left(\tfrac{H_s}{L_s}\right)^2}{4\ln 2}, \\[4pt]
            X_t  &:= \frac{1}{N}\sum_{s=t-N+1}^{t} \text{sign}(C_s - O_s)\cdot PK_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH_ADJUSTED]
        low   = product.DAY1[DataColumn.LOW_ADJUSTED]
        open_ = product.DAY1[DataColumn.OPEN_ADJUSTED]
        close = product.DAY1[DataColumn.CLOSE_ADJUSTED]

        eps = 1e-10
        hl = np.log((high / (low + eps).replace(0, eps)).clip(lower=eps))
        pk_bar    = hl ** 2 / (4 * np.log(2))
        direction = (close - open_).apply(np.sign)
        factor    = (direction * pk_bar).rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmPKTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
