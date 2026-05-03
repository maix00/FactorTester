# =============================================================================
# Factors/MmRSI.py
# 相对强弱指数因子
#
# FactorFamily 表达式驱动版本。
# r=(P-P.shift(RF))/P.shift(RF); gain=mean(max(r,0)); loss=mean(max(-r,0)); X=gain/(gain+loss)
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRSI(FactorFamily):
    """相对强弱指数（RSI）。\n\n    参数：\n        P (DataColumn) : 价格列\n        N (Timedelta)  : RSI 窗口\n        RF (Timedelta) : 收益步长"""


    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        N = WindowParam('N', default_value='14d')
        RF = WindowParam('RF', default_value='1d')
        r = P.delta(RF) / P.shift(RF)
        gain = ((r + r.abs()) / 2.0).ma(N)
        loss = ((r.abs() - r) / 2.0).ma(N)
        rs = gain / (loss + 1e-10)
        return rs / (1.0 + rs)

    desc = '相对强弱指数'
    description = """
## 这是什么
MmRSI 是相对强弱指数因子，用上涨幅度与下跌幅度的相对比例衡量价格偏向。

## 它在看什么
RSI 不是单纯看累计收益，而是把正向变化和负向变化分开统计，再计算二者的相对强弱。

## 为什么这个因子可能行得通
RSI 抓的是"上涨力量是否系统性压过下跌力量"。强趋势里高 RSI 可能意味着趋势健康。

## 使用提醒
RSI 的解释高度依赖市场状态。强趋势里高 RSI 可能健康；震荡市场里高 RSI 更像短期过热。

## 反转信号
RSI 进入超买区（>70）或超卖区（<30）后，在震荡市中是经典反转信号；顶/底背离是最有效的形态。
"""

if __name__ == '__main__':
    ff = MmRSI()
    ff.add_params(F='1d')
