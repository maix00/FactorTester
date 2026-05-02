# =============================================================================
# Factors/MmCCI.py
# 商品通道指数因子
#
# FactorFamily 表达式驱动版本。
# TP = (H+L+C)/3; X = (TP - MA_N(TP)) / (0.015 * MeanAbsDev_N(TP))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmCCI(FactorFamily):
    """商品通道指数（CCI）。\n\n    参数：\n        N (Timedelta) : 回看窗口"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        N = WindowParam('N', default_value='20d')
        H = DataColumnParam('H', default_value='HA')
        L = DataColumnParam('L', default_value='LA')
        C = DataColumnParam('C', default_value='CA')
        tp = (H.shift(0) + L.shift(0) + C.shift(0)) / 3.0
        return (tp - tp.ma(N)) / (0.015 * tp.std(N) + 1e-10)

    desc = '商品通道指数'
    description = """
## 这是什么
MmCCI 是商品通道指数，比较当前 TP 相对其滚动均值的偏离程度。

## 它在看什么
TP = (H+L+C)/3，典型价格相对均值的偏离。

## 为什么这个因子可能行得通
CCI 在趋势市场中能持续发出同向信号。

## 使用提醒
0.015 为 CCI 原始常数，保证约 70-80% 的值落在 ±100 之间。

## 反转信号
CCI 从超买超卖极端值回归零轴是反转信号。
"""

if __name__ == '__main__':
    ff = MmCCI()
    ff.add_params(F='1d')
