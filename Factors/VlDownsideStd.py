# =============================================================================
# Factors/VlDownsideStd.py
# 下行波动率因子
#
# FactorFamily 表达式驱动版本。
# neg_ret = clip(ret, upper=0); X = sqrt(mean(neg_ret^2, N))
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class VlDownsideStd(FactorFamily):
    """下行波动率（仅统计负收益的波动）。\n\n    参数：\n        P (DataColumn) : 价格列\n        RF (Timedelta)  : 收益步长\n        N (Timedelta)   : 滚动窗口"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        RF = WindowParam('RF', default_value='1d')
        N = WindowParam('N', default_value='20d')
        p = P.shift(0)
        ret = p.delta(RF) / (p.shift(RF) + 1e-10)
        neg_ret = (ret - ret.abs()) / 2.0
        return (neg_ret * neg_ret).ma(N).sqrt()

    desc = '下行波动率'
    description = """
## 这是什么
VlDownsideStd 只统计负收益（下行）的波动率，忽略正收益。

## 它在看什么
上行波动是"好的波动"，下行波动才是风险。该因子分离出纯下行风险。

## 为什么这个因子可能行得通
投资者对下行风险天然更敏感。下行波动率在预测尾部风险方面优于对称波动率。

## 使用提醒
牛市中下行波动率接近零，因子可能失去区分度。

## 反转信号
下行波动率飙升后回落，是恐慌性抛售结束的信号。
"""

if __name__ == '__main__':
    ff = VlDownsideStd()
    ff.add_params(F='1d')
