# =============================================================================
# Factors/MmOvernightTrend.py
# 隔夜趋势因子
#
# FactorFamily 表达式驱动版本。
# X_t = mean((C_t - C_{t-1d}) / C_{t-1d}) over N days
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmOvernightTrend(FactorFamily):
    """隔夜趋势因子。\n\n    参数：\n        C (DataColumn) : 收盘价列\n        N (Timedelta)  : 天数\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        C = DataColumnParam('C', default_value='CA')
        N = WindowParam('N', default_value='10d')
        gap = (C - C.shift('1d')) / (C.shift('1d') + 1e-10)
        return gap.ma(N)

    desc = '隔夜趋势'
    description = """
## 这是什么
MmOvernightTrend 是隔夜趋势因子，过去 N 日隔夜跳空收益的均值。

## 它在看什么
隔夜跳空反映收盘后到次日开盘前的新信息冲击。

## 为什么这个因子可能行得通
隔夜跳空方向的持续性可作为信息冲击方向的代理变量。

## 使用提醒
重大事件前后隔夜跳空可能异常剧烈。

## 反转信号
隔夜连续同向跳空后，若日内走势开始反向填补缺口，则是反转信号。
"""

if __name__ == '__main__':
    ff = MmOvernightTrend()
    ff.add_params(F='1d')
