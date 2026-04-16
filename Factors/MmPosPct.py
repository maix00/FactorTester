# =============================================================================
# Factors/MmPosPct.py
# 上涨天数占比因子（胜率因子）
#
# 在过去 WF 个周期内，统计收益率为正的周期占比：
#   r_t = (P_t - P_{t-RF}) / P_{t-RF}
#   X_t = (1/WF) * Σ_{s=t-WF+1}^{t} 1_{r_s > 0}
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam

class MmPosPct(FactorFamily):
    """
    上涨天数占比因子（胜率因子）。

    统计过去 WF 个 RF 周期内价格上涨的比例，值域 [0, 1]。
    高值表示近期持续上涨，低值表示持续下跌。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        WF (Timedelta)  : 滚动窗口长度（计算占比的回溯期）
        RF (Timedelta)  : 单期收益率计算频率
        F  (Timedelta)  : 输出信号频率（继承自 FactorFamily）
    """

    params = [DataColumnParam('P', DataColumn.CLOSE), WindowParam('WF'), WindowParam('RF')]

    math_expr = '''
        \\begin{aligned}
            r_t &:= \\frac{P_t - P_{t-RF}}{P_{t-RF}}, \\\\[5pt]
            X_t &:= \\frac{1}{WF}\\sum_{t-WF \\leq s \\leq t} \\mathbf{1}_{r_s > 0}.
        \\end{aligned}
    '''

    def func_timeseries(self, product: Product, F: Any = pd.Timedelta('1D'),
                        WF: Any = 1, RF: Any = 1, P: DataColumn = DataColumn.CLOSE, **kwargs):
        """
        计算单品种上涨天数占比因子。

        参数：
            product : 品种对象
            F       : 输出信号频率
            WF      : 滚动窗口大小
            RF      : 单期收益率计算步长
            P       : 价格列

        返回：
            按频率 F 同步后的 pd.Series
        """
        # 计算 RF 步长的收益率
        ret = product.MIN1[P].pct_change(RF)
        # 在 WF 窗口内统计收益率 > 0 的比例
        pos_ratio = (ret > 0).rolling(WF).mean()
        # 对齐到信号时间点并返回
        return self.sync_signal(pos_ratio, F)
    
if __name__ == '__main__':
    ff = MmPosPct()

    ff.clear_params()
    # ff.add_params(F='5m', RF='1m', WF='5m')
    # ff.add_params(F='15m', RF='1m', WF='15m')
    # ff.add_params(F='15m', RF='5m', WF='15m')
    # ff.add_params(F='30m', RF='5m', WF='30m')
    # ff.add_params(F='1d', RF='1d', WF='1d')
    # ff.add_params(F='1d', RF='10min', WF='1d')
    # ff.add_params(F='2d', RF='1d', WF='2d')
    # ff.add_params(F='2d', RF='10min', WF='2d')
    # ff.add_params(F='10d', RF='2d', WF='10d')
    ff.add_params(F='1d', RF='1d', WF='10d')
    # ff.add_params(F='2d', RF='2d', WF='10d')

    fft = ff.test(start_calc_point='2024-02-03 09:00:00', timezone='Asia/Shanghai')
    # print(fft.products)