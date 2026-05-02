# =============================================================================
# Factors/MmIntradayMom.py
# 日内动量因子
#
# FactorFamily 表达式驱动版本。
# X_t = mean((C_t - O_t) / O_t) over N days
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmIntradayMom(FactorFamily):
    """日内动量因子。\n\n    参数：\n        O (DataColumn) : 开盘价列\n        C (DataColumn) : 收盘价列\n        N (Timedelta)  : 天数\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        O = DataColumnParam('O', default_value='OA')
        C = DataColumnParam('C', default_value='CA')
        N = WindowParam('N', default_value='10d')
        return ((C - O) / (O + 1e-10)).ma(N)

    desc = '日内动量'
    description = """
## 这是什么
MmIntradayMom 是日内动量因子，过去 N 日日内涨跌幅的均值。

## 它在看什么
与隔夜跳空不同，日内动量反映交易时段内的方向性。

## 为什么这个因子可能行得通
日内强势通常伴随盘中买盘的持续流入。

## 使用提醒
涨跌停等极端行情下日内涨幅可能失真。

## 反转信号
连续多日高日内涨幅后出现长上影线，往往是反转前兆。
"""

if __name__ == '__main__':
    ff = MmIntradayMom()
    ff.add_params(F='1d')
