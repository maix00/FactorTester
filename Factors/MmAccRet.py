# =============================================================================
# Factors/MmAccRet.py
# 跳过近期的长周期累积收益因子（12-1 动量）
#
# 经典的跨期动量：计算 [t-NL, t-NS] 内的累积收益，跳过最近 NS 期以规避短期反转：
#   X_t = (P_{t-NS} - P_{t-NL}) / P_{t-NL}
#
# 重写为 ExprFactorFamily 表达式驱动版本。
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors.ExprFactorFamily import ExprFactorFamily
from tools.parameters import WindowParam, DataColumnParam

class MmAccRet(ExprFactorFamily):
    """
    跳过近期的长周期累积收益因子（经典 12-1 动量）。

    计算 NL 期前到 NS 期前的价格涨幅，跳过最近 NS 期（规避短期反转）。
    NL=252d, NS=21d 对应经典的 12 个月减去 1 个月动量。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE_ADJUSTED
        NL (Timedelta)  : 长周期（回看起点），默认 30m
        NS (Timedelta)  : 短周期（跳过的近期），默认 10m
        F  (Timedelta)  : 输出信号频率
    """

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        NL = WindowParam('NL', default_value='30m')
        NS = WindowParam('NS', default_value='10m')
        return (P.shift(NS) - P.shift(NL)) / (P.shift(NL) + 1e-10)

    desc = '跳期累积动量'
    description = """
## 这是什么
MmAccRet 是一个"跳过最近一段时间"的累计动量因子。它比较的是较长窗口之前到较短窗口之前这一段价格变化，而不是直接把最新一段涨跌也算进去。

## 它在看什么
这个构造本质上是在估计"中期趋势"，同时尽量绕开最近几期可能出现的短期反转。常见理解是：保留较稳定的趋势成分，剔除最靠近当前时点的拥挤交易和均值回归噪声。

## 为什么这个因子可能行得通
很多市场同时存在中期动量和短期反转两种效应。直接使用总累计收益时，这两者会互相污染；而跳过最近一段时间后，往往能更干净地保留趋势延续部分。因此它常用于区别"真正的中期强势"与"刚刚冲过头的短线过热"。

## 使用提醒
短窗口和长窗口之间的间隔决定了你想剔除多少短期噪声。若跳过区间过短，短期反转仍可能污染信号；若过长，则会损失趋势的时效性。

## 反转信号
跳过近期之后的中期动量，在以下场景中更容易面临反转：（1）NS 跳过窗口之内积累了极端负收益（急跌后的超卖反弹）；（2）市场整体从趋势模式切换至均值回归模式，例如波动率突然抬升、成交量快速倍增但价格原地踏步；（3）因子值本身处于极端高/低分位，历史上这类极端动量值的持续性会显著下降。反转在中短周期（NS 与 NL 之差较小）时发生更频繁，因为样本量更少、稳定性更差。
"""

if __name__ == '__main__':
    ff = MmAccRet()
    ff.clear_params()
    ff.add_params(F='1d', NL='252d', NS='21d')
    ff.add_params(F='1d', NL='120d', NS='10d')
