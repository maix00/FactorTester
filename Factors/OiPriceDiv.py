# =============================================================================
# Factors/OiPriceDiv.py
# 持仓量与价格背离因子
#
# 比较持仓量变化方向与价格变化方向的差异：
#   r_t  = sign(P_t  - P_{t-RF})
#   oi_t = sign(OI_t - OI_{t-RF})
#   div_t = r_t * oi_t  ∈ {-1, 0, +1}
#   X_t = rolling mean(div, N)
# +1 表示量价同向（价涨仓增 or 价跌仓减），-1 表示背离。
# =============================================================================
import pandas as pd
import numpy as np
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class OiPriceDiv(FactorFamily):
    """
    持仓量与价格背离因子。

    逐期判断持仓量变化方向与价格变化方向是否一致，
    在 N 期窗口内取均值：
      正值 → 量价同向（多头增仓或空头减仓）
      负值 → 量价背离

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 均值窗口，默认 10d
        RF (Timedelta)  : 单期步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '价格持仓背离'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiPriceDiv 是价格与持仓方向关系因子，用价格变化方向和持仓变化方向的一致性或背离程度来刻画市场结构。',
        },
        {
            'title': '它在看什么',
            'body': '如果价格上涨且持仓增加，通常可解释为顺势增仓；价格上涨但持仓减少，则更像空头回补或旧仓离场；价格下跌且持仓增加，则可能是空头增仓。这个因子把这些组合压缩为一个方向一致性度量。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '价格与持仓的组合信息往往比单独任何一个变量更有解释力。价格涨跌告诉你表面方向，持仓变化告诉你背后是新仓推动还是旧仓了结。二者一致时，趋势可能更扎实；二者背离时，走势可能更脆弱。',
        },
        {
            'title': '使用提醒',
            'body': '它本质上是在做结构判别，因此更适合配合趋势因子确认，而不一定适合作为唯一的方向打分。',
        },
        {
            'title': '反转信号',
            'body': '价格与持仓量背离因子本身就是一个反转/分歧信号：（1）价格上涨但持仓量下降（因子为负）：趋势由平仓行为推动，多方共识疲弱，反转风险高；（2）价格下跌但持仓量上升（因子为负的另一极）：可能是空头大幅新建仓，趋势可能延续，也可能是多头抄底被套——需结合是否接近历史支撑判断；（3）价格上涨且持仓量上涨（因子为正）：趋势与增仓方向一致，反转风险相对较低。背离类因子反转在价格接近趋势末端最为有效；趋势初期阶段背离可能只是信息扩散的时滞，不宜直接做反转。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{1}{N} \sum_{s} \operatorname{sign}(\Delta P_s) \cdot \operatorname{sign}(\Delta OI_s)
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        oi    = product.MIN1[DataColumn.OPEN_INTEREST]
        price_sign = np.sign(price.diff(RF))
        oi_sign    = np.sign(oi.diff(RF))
        div = price_sign * oi_sign
        factor = div.rolling(N).mean()
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = OiPriceDiv()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    ff.add_params(F='1d', N='5d',  RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
