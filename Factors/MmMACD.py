# =============================================================================
# Factors/MmMACD.py
# MACD 柱状线趋势加速因子
#
# FactorFamily 表达式驱动版本。
# DIF=EMA_fast(P)-EMA_slow(P); DEA=EMA_signal(DIF); X=(DIF-DEA)/P
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMACD(FactorFamily):
    """MACD 柱状线趋势加速因子。\n\n    参数：\n        P (DataColumn) : 价格列\n        Fast (Timedelta)  : 快线 EMA 窗口\n        Slow (Timedelta)  : 慢线 EMA 窗口\n        Signal (Timedelta): 信号线 EMA 窗口"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        Fast = WindowParam('Fast', default_value='12d')
        Slow = WindowParam('Slow', default_value='26d')
        Signal = WindowParam('Signal', default_value='9d')
        p = P.shift(0)
        dif = p.rolling_ema(Fast) - p.rolling_ema(Slow)
        dea = dif.rolling_ema(Signal)
        return (dif - dea) / (p + 1e-10)

    desc = '指数均线趋势加速'
    description = """
## 这是什么
MmMACD 是基于快慢均线差及其信号线的趋势加速度因子。

## 它在看什么
当短期均线相对长期均线持续走强且这种强势还在加速时，MACD 柱值偏正。

## 为什么这个因子可能行得通
市场从盘整切换到趋势时，往往先表现为短周期价格领先，随后领先幅度继续扩大。

## 使用提醒
MACD 对参数组合敏感。太短追噪声，太长滞后。

## 反转信号
MACD 柱高度从高位开始收缩、顶/底背离、死叉/金叉都是反转信号。震荡区间中的背离更可靠。
"""

if __name__ == '__main__':
    ff = MmMACD()
    ff.add_params(F='1d')
