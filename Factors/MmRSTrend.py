# =============================================================================
# Factors/MmRSTrend.py
# 日内 RS 波动趋势因子
#
# 过去 N 个交易日，RS 波动率乘以日内方向的均值：
#   direction_s = sign(C_s - O_s)
#   RS_s = Rogers-Satchell 单 Bar 估计量
#   X_t = (1/N) * Σ direction_s * RS_s
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class MmRSTrend(FactorFamily):
    """
    日内 RS 波动趋势因子。

    将每日的 Rogers-Satchell 波动量与日内方向相乘后求均值，
    刻画"有方向的波动"——上涨日的波动贡献为正，下跌日为负。

    参数：
        N (Timedelta) : 回看交易日数，默认 10d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='10d'),
    ]

    chinese_name = 'RS 波动趋势'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmRSTrend 是日内 RS 波动趋势因子，将 Rogers-Satchell 单日波动估计量乘以当日收盘相对开盘的方向（涨为正、跌为负），然后在 N 日内求均值，捕捉"带方向的波动"。',
        },
        {
            'title': '它在看什么',
            'body': '它同时关注波动的大小和方向：如果近期波动大且主要发生在上涨方向，因子偏正；波动大但主要发生在下跌方向，因子偏负；波动大但方向随机，因子接近 0。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '纯波动率不带方向，纯收益率不够关注路径幅度。RS 波动趋势因子将两者结合，更能区分"强趋势大波动"与"无方向大波动"。在期货市场，带方向的大波动频繁出现时，趋势惯性的持续性也更强，因子因此具备一定的前瞻性。',
        },
        {
            'title': '使用提醒',
            'body': 'RS 单 Bar 估计量对 H/L/O/C 的价格质量有一定要求，异常报价或主力合约换月日的价格跳变会干扰估计；窗口 N 较短时，个别极端日会主导整体均值。',
        },
        {
            'title': '反转信号',
            'body': '当 MmRSTrend 处于极端正值（近期上涨波动大且集中），若随后出现几天连续低振幅小幅收红或收平，是动能减弱的信号；当 MmRSTrend 从正值快速下穿 0（方向翻转+波动），往往是趋势切换的强信号，反转持续概率更高。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            RS_s     &:= \ln\!\tfrac{H_s}{C_s}\cdot\ln\!\tfrac{H_s}{O_s}
                        + \ln\!\tfrac{L_s}{C_s}\cdot\ln\!\tfrac{L_s}{O_s}, \\[4pt]
            X_t      &:= \frac{1}{N}\sum_{s=t-N+1}^{t} \text{sign}(C_s - O_s)\cdot RS_s.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), **kwargs) -> pd.Series:
        high  = product.DAY1[DataColumn.HIGH_ADJUSTED]
        low   = product.DAY1[DataColumn.LOW_ADJUSTED]
        open_ = product.DAY1[DataColumn.OPEN_ADJUSTED]
        close = product.DAY1[DataColumn.CLOSE_ADJUSTED]

        eps = 1e-10
        ho = np.log((high / (open_ + eps).replace(0, eps)).clip(lower=eps))
        hc = np.log((high / (close + eps).replace(0, eps)).clip(lower=eps))
        lo = np.log((low  / (open_ + eps).replace(0, eps)).clip(lower=eps))
        lc = np.log((low  / (close + eps).replace(0, eps)).clip(lower=eps))

        rs_bar = hc * ho + lc * lo
        direction = (close - open_).apply(np.sign)
        factor = (direction * rs_bar).rolling(N).mean().fillna(0.0)

        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = MmRSTrend()
    ff.clear_params()
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
