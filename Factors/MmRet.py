# =============================================================================
# Factors/MmRet.py
# 收益率动量因子
#
# FactorFamily 表达式驱动版本。
# X_t = (P_t - P_{t-F}) / P_{t-F}
# =============================================================================
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.factors import FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmRet(FactorFamily):
    """收益率动量因子。\n\n    参数：\n        P (DataColumn) : 价格列，默认 CLOSE_ADJUSTED\n        F (Timedelta)  : 信号频率"""

    source_freq = 'MIN1'

    @staticmethod
    def factor_expr():
        P = DataColumnParam('P', default_value='CA')
        return P.delta('$F') / P.shift('$F')

    desc = '收益率动量'
    description = """
## 这是什么
MmRet 是最直接的收益率动量因子，计算的是当前价格相对一个信号频率窗口之前价格的涨跌幅。

## 它在看什么
如果最近一个 `$F` 周期上涨，因子为正；下跌则为负。

## 为什么这个因子可能行得通
如果市场存在最基本的趋势惯性，那么最近一期的收益方向本身就带有预测信息。

## 使用提醒
周期太短时会更像噪声；周期太长时则会降低信号更新速度。

## 反转信号
极短周期的微观结构反转；日线连续多日同向后市场过度拥挤；突破失败后的快速反向。
"""

if __name__ == '__main__':
    ff = MmRet()
    ff.add_params(F='1d')
