# =============================================================================
# Factors/OiChgRatio.py
# 持仓量变化比值因子
#
# 当前持仓量与 N 期前持仓量的比值（而非变化率）：
#   X_t = OI_t / OI_{t-N}
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class OiChgRatio(FactorFamily):
    """
    持仓量变化比值因子。

    当前持仓量相对 N 期前持仓量的倍数，
    与 OiChgRat（变化率）相比，更直接反映持仓的相对规模变化。

    参数：
        N  (Timedelta) : 回看窗口，默认 5d
        RF (Timedelta) : 单期步长，默认 1d
        F  (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N',  default_value='5d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '持仓量变化比值'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiChgRatio 是持仓量变化比值因子，计算当前持仓量与 N 期前持仓量的比值（倍数关系），而非变化率。值大于 1 表示持仓扩张，小于 1 表示持仓收缩。',
        },
        {
            'title': '它在看什么',
            'body': '比值形式对持仓量的基数更不敏感，适合跨品种纵向比较：比值为 2 意味着持仓翻倍，无论初始持仓绝对量多大，含义一致。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '持仓量翻倍式扩张通常是资金大举入场的信号，而持仓腰斩往往意味着资金撤离或强制平仓。比值形式比变化率更能区分"从 10 万手增到 20 万手"（真正的倍增）和"从 100 万手增略到 102 万手"（微量增仓）这两种本质不同的情况。',
        },
        {
            'title': '使用提醒',
            'body': '持仓量在合约换月、交割期前后会发生不连续跳变，此时的比值会失真；建议对比值做异常值过滤，或限定使用主力合约的稳定期数据。',
        },
        {
            'title': '反转信号',
            'body': '持仓量比值处于历史极高位（持仓大幅扩张）后若价格停滞不前，说明新建头寸无法推动价格，积累了大量被套仓位，此后价格反转常伴随持仓快速去化（比值迅速回落）——去化速度越快，反转越剧烈；持仓量比值长期处于极低水平（持仓枯竭）后突然快速放大，往往是方向性启动的前兆，此时追方向而非反转。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{OI_t}{OI_{t-N}}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('5d'), RF: Any = pd.Timedelta('1d'),
                        **kwargs) -> pd.Series:
        oi = product.MIN1[DataColumn.OPEN_ADJUSTED_INTEREST]
        if isinstance(N, pd.Timedelta) and isinstance(RF, pd.Timedelta):
            steps = max(1, int(N / RF))
        else:
            steps = int(N) if not isinstance(N, pd.Timedelta) else 1
        oi_prev = oi.shift(steps).replace(0, float('nan'))
        ratio = (oi / oi_prev).fillna(1.0).replace([float('inf'), -float('inf')], 1.0)
        return self.sync_signal(ratio)

if __name__ == '__main__':
    ff = OiChgRatio()
    ff.clear_params()
    ff.add_params(F='1d', N='5d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
