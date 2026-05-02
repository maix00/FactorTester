# =============================================================================
# Factors/MmUpRatio.py
# 上涨占比因子
#
# FactorFamily 表达式驱动版本。
# X_t = sum(max(r_i,0)) / sum(|r_i|) over N*RF window
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmUpRatio(FactorFamily):
    """上涨占比因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 统计周期数\n        RF (Timedelta) : 单期步长\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='5d')
        RF = WindowParam('RF', default_value='1d')
        r = P.delta(RF) / P.shift(RF)
        up = (r + r.abs()) / 2.0
        return up.rolling_sum(N) / (r.abs().rolling_sum(N) + 1e-10)

    desc = '上涨占比'
    description = """
## 这是什么
MmUpRatio 是上涨占比因子，累计上涨幅度占累计总波动幅度的比例。

## 它在看什么
不仅看涨跌频率，还考虑涨跌幅度。

## 为什么这个因子可能行得通
因子值 > 0.5 表示买方主导；< 0.5 表示卖方主导。

## 使用提醒
极端值在小样本下容易逆转。

## 反转信号
极端高位 + 成交量萎缩 = 买方力量衰竭。
"""

if __name__ == '__main__':
    ff = MmUpRatio()
    ff.add_params(F='1d')
