# =============================================================================
# Factors/VpLiquidity.py
# 流动性因子
#
# 过去 N 期成交量除以绝对收益率的均值，衡量每单位价格变动所需的成交量：
#   X_t = (1/N) Σ Vol_s / |ret_s|
# 值越大表示流动性越好（价格变动需要更多成交量），是非流动性（Amihud）的倒数。
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class VpLiquidity(FactorFamily):
    """
    流动性因子。

    每单位价格变动（绝对收益率）所对应的成交量，
    即 Amihud 非流动性因子的倒数，衡量市场吸收成交量的能力。

    参数：
        N  (Timedelta) : 回看窗口，默认 10d
        RF (Timedelta) : 单期收益率步长，默认 1m
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1m'),
    ]

    chinese_name = '流动性'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VpLiquidity 是流动性因子，计算过去 N 期每单位价格变动所对应平均成交量，即 Amihud 非流动性因子（VpAmihud）的倒数。值越大说明价格移动"更贵"——需要更多成交量，此时市场流动性好、大单冲击成本低。',
        },
        {
            'title': '它在看什么',
            'body': '它回答的是"用一手的成交，能买到/卖到多少价格空间"的反面问题——即"一个单位的价格空间需要多少手成交来填充"。流动性高时这个数字大；流动性差（如非主力品种、临近节假日）时这个数字小。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '高流动性（大因子值）品种的趋势延续性更好：大资金进出时冲击成本低，愿意持续增仓；低流动性品种更容易被大单拉偏后迅速回撤，趋势不可持续。因此流动性因子可用于筛选适合做趋势策略的交易品种，或作为信号强度的加权权重。',
        },
        {
            'title': '使用提醒',
            'body': '当价格变动极小（如盘整震荡）时，分母接近零，VpLiquidity 会变得极大并失去意义；建议对绝对收益率设置最小阈值（如 1e-6），或在极端值时截尾处理。',
        },
        {
            'title': '反转信号',
            'body': 'VpLiquidity 快速大幅下降（同样的成交量推动了更大的价格变动）是市场流动性危机的早期信号，此时持续建仓风险极高；流动性因子在上涨过程中持续萎缩，说明推涨的成交量越来越"高效"（少量成交就能大幅拉涨），这往往是最后一波轧空/尾部行情而非健康趋势，此后更容易发生急速反转。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{1}{N} \sum_{s} \frac{Vol_s}{\lvert r_s \rvert}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'),
                        RF: Any = pd.Timedelta('1m'), **kwargs) -> pd.Series:
        close  = product.MIN1[DataColumn.CLOSE]
        volume = product.MIN1[DataColumn.VOLUME]

        eps = 1e-6
        ret = close.pct_change(1).abs().replace(0, float('nan'))
        ret = ret.clip(lower=eps)
        liquidity_per_bar = volume / ret
        factor = liquidity_per_bar.rolling(N).mean().fillna(0.0)
        return self.sync_signal(factor)

if __name__ == '__main__':
    ff = VpLiquidity()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1m')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
