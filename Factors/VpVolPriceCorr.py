# =============================================================================
# Factors/VpVolPriceCorr.py
# 量价相关性因子
#
# 在过去 N 个 RF 周期内，计算成交量与价格涨跌的滚动相关系数：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   X_t = Corr(V, r, N)
# 正值表示放量上涨/缩量下跌（量价配合），负值反之。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VpVolPriceCorr(FactorFamily):
    """
    量价相关性因子。

    在 N 期滚动窗口内计算成交量与价格收益率的相关系数，
    衡量量价配合程度（正值：放量上涨/缩量下跌；负值：放量下跌/缩量上涨）。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 20d
        RF (Timedelta)  : 单期步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '量价相关性'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VpVolPriceCorr 是成交量与收益率的滚动相关系数因子，用来衡量价格变化是否得到量能的同步支持。',
        },
        {
            'title': '它在看什么',
            'body': '当收益率为正时成交量也倾向放大、收益率为负时成交量也倾向收缩，相关性会偏正；反之，如果下跌放量、上涨缩量，则相关性可能偏负。它刻画的是“量价是否同向协同”。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '量价配合常被视为趋势健康度的重要特征。上涨伴随放量通常意味着买盘认可度更高；若上涨缩量而下跌放量，则更像脆弱反弹或派发过程。量价相关结构因此能帮助识别趋势质量和潜在反转风险。',
        },
        {
            'title': '使用提醒',
            'body': '相关系数对窗口长度和异常点比较敏感，样本过短时很容易失真。',
        },
        {
            'title': '反转信号',
            'body': '量价相关性因子的反转逻辑：（1）量价正相关（涨时放量、跌时缩量）是健康趋势的标志；当该相关性开始脱离正值向 0 或负值演变时，原有趋势的可持续性存疑，反转风险上升；（2）量价负相关（涨时缩量、跌时放量）本身是反转因子，表示资金在价格上涨时逐步离场，下跌时被动承接；（3）从正相关到负相关的切换，通常先是量价相关性骤降（相关性接近 0），此阶段应降低趋势信号的权重。反转在以下情况更可靠：量价相关性持续多期为负且价格处于高位（分布性做空）；或者量价相关性由正转负伴随价格大幅波动率上升（资金分歧加剧）。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_t &:= \frac{P_t - P_{t-RF}}{P_{t-RF}} \\[5pt]
            X_t &:= \operatorname{Corr}(V,\, r,\, N)
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price  = product.MIN1[P]
        volume = product.MIN1[DataColumn.VOLUME]
        ret = price.pct_change(RF)
        corr = volume.rolling(N).corr(ret)
        corr = corr.fillna(0.0)
        return self.sync_signal(corr)
if __name__ == '__main__':
    ff = VpVolPriceCorr()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
