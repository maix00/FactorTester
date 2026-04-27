# =============================================================================
# Factors/VlCV.py
# 变异系数因子（σ/μ）
#
# 收益率标准差与收益率均值绝对值之比：
#   X_t = σ_N / |μ_N|
# 度量收益波动相对收益水平的比率。
# =============================================================================
import numpy as np
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VlCV(FactorFamily):
    """
    变异系数因子（Coefficient of Variation）。

    σ/|μ|，衡量收益波动相对于收益均值的大小。
    高值意味着信噪比低，收益不稳定；低值意味着信噪比高。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 20d
        RF (Timedelta)  : 单期收益率计算步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '变异系数'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlCV 是变异系数因子，用收益率的标准差除以收益率均值的绝对值，衡量收益率分布的相对离散程度，即"每单位预期收益对应多少波动"。',
        },
        {
            'title': '它在看什么',
            'body': '当因子偏低时，收益方向明确且波动相对有限，信噪比高；当因子偏高时，收益均值接近 0 但波动大，信号混乱，方向无法判断。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '趋势行情通常伴随较低变异系数（稳定方向性收益）；而震荡行情的特征是高变异系数（大波动但无净方向）。变异系数因此可以作为市场状态切换的早期指标，也常用于策略的风险调仓。',
        },
        {
            'title': '使用提醒',
            'body': '当收益均值接近 0 时（如震荡市初期），变异系数会极度不稳定或趋向无穷大；建议对分母设置最小阈值，或仅在均值符号明确时使用该因子。',
        },
        {
            'title': '反转信号',
            'body': '变异系数从极高位（信噪比极低）开始持续回落，通常意味着市场方向共识正在重新形成，此时可以开始关注方向性动量信号的有效性；当因子处于历史低位（信号极清晰）时，往往说明趋势已经充分确立，追趋势的性价比反而下降——这种低变异系数+高累计动量的组合，历史上是均值回归的常见前奏。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_s &:= \frac{P_s - P_{s-RF}}{P_{s-RF}}, \\[4pt]
            X_t &:= \frac{\mathrm{RollingSTD}_{N}(r)_t}{\left|\mathrm{RollingMean}_{N}(r)_t\right|}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret   = price.pct_change(RF)
        roll_std = ret.rolling(N).std()
        roll_mean = ret.rolling(N).mean().abs().replace(0, float('nan'))
        cv = (roll_std / roll_mean).fillna(0.0).replace([float('inf'), -float('inf')], 0.0)
        return self.sync_signal(cv)

if __name__ == '__main__':
    ff = VlCV()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
