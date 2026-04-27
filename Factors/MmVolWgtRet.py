# =============================================================================
# Factors/MmVolWgtRet.py
# 成交量加权收益因子（VWAP 动量）
#
# 在过去 N 个 RF 周期内，以成交量为权重对每期收益加权求和：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   X_t = Σ V_s * r_s / Σ V_s，s ∈ [t-N+1, t]
# 成交大的周期的收益被赋予更高权重，反映资金主导方向。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmVolWgtRet(FactorFamily):
    """
    成交量加权收益因子。

    在 N 期窗口内，以各周期成交量为权重对收益率进行加权平均，
    使得成交量放大时期的涨跌方向对因子值的贡献更大。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 10d
        RF (Timedelta)  : 单期收益率步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '成交量加权收益'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmVolWgtRet 是成交量加权收益因子，用成交量对每一期收益进行加权后，再衡量最近窗口的净方向。',
        },
        {
            'title': '它在看什么',
            'body': '如果上涨主要发生在高成交量时期，而下跌更多发生在低成交量时期，那么加权后的因子会更强；反之则更弱。这个构造试图回答：最近的价格方向，到底有没有被更大规模的交易活动支持。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '价格本身只能告诉你结果，成交量则提供了过程中的参与度信息。带量上涨通常比缩量上涨更可信，因为它意味着更多资金在相同方向上达成交易；带量下跌同理也更值得警惕。',
        },
        {
            'title': '使用提醒',
            'body': '不同合约和不同阶段的量能口径差异较大，若横截面比较较多，最好配合标准化或只在同类资产中使用。',
        },
        {
            'title': '反转信号',
            'body': '成交量加权收益因子出现以下情况时，反转概率上升：（1）量价背离：价格继续上涨，但成交量不再配合（高成交量出现在下跌方向）——量价加权收益会领先于纯价格收益提前转负；（2）成交量集中于几次极端值时，加权会被单期主导，噪声上升；（3）因子从极端正值快速回落至 0 附近，通常意味着做多资金"边涨边卖"，趋势动能减弱。反转在高换手、主力资金进出明显的资产中更为有效；低流动性品种量能本身波动大，量价关系更不稳定。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            r_t &:= \frac{P_t - P_{t-RF}}{P_{t-RF}} \\[5pt]
            X_t &:= \frac{\sum_{s=t-N+1}^{t} V_s \cdot r_s}{\sum_{s=t-N+1}^{t} V_s}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        price  = product.MIN1[P]
        volume = product.MIN1[DataColumn.VOLUME]
        ret = price.pct_change(RF)
        vol_ret = volume * ret
        vwr = vol_ret.rolling(N).sum() / volume.rolling(N).sum().replace(0, float('nan'))
        vwr = vwr.fillna(0.0)
        return self.sync_signal(vwr)
if __name__ == '__main__':
    ff = MmVolWgtRet()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    ff.add_params(F='1d', N='5d',  RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
