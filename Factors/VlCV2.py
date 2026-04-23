# =============================================================================
# Factors/VlCV2.py
# 变异系数因子 2（σ²/μ）
#
# 收益率方差与收益率均值之比：
#   X_t = σ²_N / μ_N
# 有符号，能区分正收益环境和负收益环境下的高方差状态。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VlCV2(FactorFamily):
    """
    变异系数因子 2（σ²/μ）。

    收益率方差除以收益率均值，保留符号，
    可视为风险调整后的"噪声-信号"比值。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 20d
        RF (Timedelta)  : 单期收益率计算步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '变异系数 2'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlCV2 是带符号的变异系数因子，用收益率方差除以收益率均值（不取绝对值），因此保留了方向性：方差/正均值为正，方差/负均值为负。',
        },
        {
            'title': '它在看什么',
            'body': '当因子为正且较大，意味着上涨趋势中波动大；为负且较大（绝对值），意味着下跌趋势中波动大。绝对值接近 0 则意味着波动小或方向漂移快。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '带符号的变异系数不仅反映信噪比，也反映"当前是高波动上涨还是高波动下跌"，能比无符号版本提供更多维度的信息。在量化组合中，它常被用于区分同样的高波动环境下截然不同的方向性质量。',
        },
        {
            'title': '使用提醒',
            'body': '当均值趋近 0 时因子会剧烈波动甚至为 NaN，需要做极值处理。建议搭配收益率水平的阈值条件使用，或在极端值处截断。',
        },
        {
            'title': '反转信号',
            'body': '当因子极度负（高方差负收益），往往对应超卖恐慌阶段，反弹概率上升；当因子极度正（高方差正收益），往往对应过度追涨，均值回归概率上升。与无符号变异系数 (VlCV) 配合，可以更精确地判断方向性反转时机。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_s &:= \frac{P_s - P_{s-RF}}{P_{s-RF}}, \\[4pt]
            X_t &:= \frac{\sigma^2(r_{t-N+1},\ldots,r_t)}{\mu(r_{t-N+1},\ldots,r_t)}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret   = price.pct_change(RF)
        roll_var  = ret.rolling(N).var()
        roll_mean = ret.rolling(N).mean().replace(0, float('nan'))
        cv2 = (roll_var / roll_mean).fillna(0.0).replace([float('inf'), -float('inf')], 0.0)
        return self.sync_signal(cv2)

if __name__ == '__main__':
    ff = VlCV2()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
