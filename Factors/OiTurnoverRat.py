# =============================================================================
# Factors/OiTurnoverRat.py
# 持仓换手率因子（持仓/成交量比值）
#
# 持仓量与成交量的比值，反映每单位成交量对应的持仓量累积程度：
#   X_t = OI_t / MA(V, N)
# 比值高：成交量相对持仓少，市场参与者持仓稳定（低换手）
# 比值低：相对成交活跃，持仓频繁换手（高流动性、投机气氛浓）
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import WindowParam


class OiTurnoverRat(FactorFamily):
    """
    持仓换手率因子（持仓量 / 成交量均值）。

    比值高表示持仓相对稳定（不活跃）；
    比值低表示市场换手频繁（投机性强）。

    参数：
        N (Timedelta) : 成交量均值窗口，默认 5d
        F (Timedelta) : 输出信号频率
    """

    params = [
        WindowParam('N', default_value='5d'),
    ]

    chinese_name = '持仓换手率'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiTurnoverRat 是持仓量相对成交活跃度的比例因子，用持仓量与成交量均值的比值来衡量市场更像是“存量仓位主导”还是“高换手主导”。',
        },
        {
            'title': '它在看什么',
            'body': '当持仓量相对成交量更高时，说明大量头寸处于被持有状态，市场更偏向存量博弈；当成交量相对更高时，则说明换手频繁、短线交易更活跃。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '同样的价格波动，如果发生在低换手高持仓环境里，往往说明仓位更稳定、趋势可能更有延续性；如果发生在高换手环境里，则可能更多是短线冲击和噪声交易。这个比例因此能辅助判断行情的持久性和交易结构。',
        },
        {
            'title': '使用提醒',
            'body': '不同品种天然具有不同的持仓和换手特征，横向比较时要注意品种属性差异。',
        },
        {
            'title': '反转信号',
            'body': '持仓换手率因子的反转场景：（1）换手率从极低位置快速抬升——市场从冷清到活跃，往往伴随方向性启动，此时原有趋势更可能反转或加速；（2）换手率处于极高位时，市场博弈激烈，方向不稳定，短期反转频率更高；（3）换手率持续下降伴随价格缓慢漂移（低流动性推升价格），一旦流动性恢复，价格容易快速向均值回归。反转在以下情况更可靠：换手率极端值与季节性（如合约换月期）而非趋势性原因有关；或者换手率的突然变化伴随宏观信息冲击重新定价。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{OI_t}{MA(V,\, N)_t}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('5d'), **kwargs) -> pd.Series:
        oi     = product.MIN1[DataColumn.OPEN_INTEREST]
        volume = product.MIN1[DataColumn.VOLUME]
        ma_vol = volume.rolling(N).mean().replace(0, float('nan'))
        factor = oi / ma_vol
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = OiTurnoverRat()
    ff.clear_params()
    ff.add_params(F='1d', N='5d')
    ff.add_params(F='1d', N='10d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
