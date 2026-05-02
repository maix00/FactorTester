# =============================================================================
# Factors/MmRateOfChg.py
# 价格变化率因子
#
# FactorFamily 表达式驱动版本。
# X_t = (P_t - P_{t-N}) / P_{t-N}
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRateOfChg(FactorFamily):
    """价格变化率（ROC）因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : 回看窗口\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='10d')
        return (P - P.shift(N)) / (P.shift(N) + 1e-10)

    desc = '价格变化率'
    description = """
## 这是什么
MmRateOfChg 是价格变化率（ROC）因子，计算当前价格相对 N 期前价格的涨跌幅。

## 它在看什么
与 MmRet 类似但用独立的 N 参数控制回看窗口，与信号频率 F 解耦。

## 为什么这个因子可能行得通
ROC 是最经典的趋势跟踪指标之一。

## 使用提醒
N 太短时噪声大，N 太长时信号滞后。

## 反转信号
极端 ROC 值在均值回归环境中容易出现反转，尤其当成交量萎缩时。
"""

if __name__ == '__main__':
    ff = MmRateOfChg()
    ff.add_params(F='1d')
