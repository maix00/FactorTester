# =============================================================================
# Factors/OiPriceDiv.py
# 价格持仓背离因子
#
# FactorFamily 表达式驱动版本。
# div = sign(d_price) * sign(d_oi); X = div.rolling_mean(N)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class OiPriceDiv(FactorFamily):
    """价格持仓背离因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        OI (DataColumn) : 持仓量列\n        RF (Timedelta)  : 差分步长\n        N (Timedelta)   : 滚动窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        OI = DataColumnParam('OI', default_value='OI')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='10d')
        p = P.shift(0)
        oi = OI.shift(0)
        price_sign = p.delta(RF).sign()
        oi_sign = oi.delta(RF).sign()
        div = price_sign * oi_sign
        return div.rolling_mean(N)

    desc = '价格持仓背离'
    description = """
## 这是什么
OiPriceDiv 度量价格方向与持仓方向是同步还是背离。

## 它在看什么
价格涨 + 持仓涨 = 正向（同向），价格涨 + 持仓降 = 负向（背离）。跨 N 期平均得到趋势的同向程度。

## 为什么这个因子可能行得通
持续的同向运动（价格涨持仓涨、价格跌持仓跌）是强趋势的标志。背离则暗示趋势动力不足。

## 使用提醒
该因子在趋势中与价格高度正相关，背离是该因子的核心信号而非噪声。

## 反转信号
因子从与价格同向转为背离，是最经典的趋势衰竭信号——量价背离。
"""

if __name__ == '__main__':
    ff = OiPriceDiv()
    ff.add_params(F='1d')
