# =============================================================================
# Factors/OiAmtChgRat.py
# 持仓金额涨幅因子
#
# 当前持仓金额（OI × 价格）相对 N 期前的变化率：
#   OIAmt_t = OI_t * P_t
#   X_t = (OIAmt_t - OIAmt_{t-N}) / OIAmt_{t-N}
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class OiAmtChgRat(FactorFamily):
    """
    持仓金额涨幅因子。

    用持仓量乘以价格估算持仓金额，再计算 N 期变化率，
    同时捕捉持仓量变化和价格变化对总持仓价值的联合影响。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 回看窗口，默认 10d
        RF (Timedelta)  : 单期步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE_ADJUSTED),
        WindowParam('N',  default_value='10d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '持仓金额涨幅'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiAmtChgRat 是持仓金额涨幅因子，将持仓量乘以当前价格得到估算持仓金额，再计算 N 期变化率，同时反映"持仓扩张"和"价格上涨"对资金规模的联合贡献。',
        },
        {
            'title': '它在看什么',
            'body': '一个市场的总持仓金额上升，可能是因为持仓量增加（新资金入场）、也可能是因为价格上涨（存量头寸升值）、或者两者兼有。这个因子把两种效应叠加在一起，衡量"市场总锁仓资产"的变化方向和幅度。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '持仓金额的快速上升往往意味着市场活跃度和资金关注度在同时提升，这种"双轮驱动"的行情通常比纯涨价格（缩量/平仓）或纯增仓（价格不动）的行情更具延续性。',
        },
        {
            'title': '使用提醒',
            'body': '持仓金额是持仓量和价格的乘积，当价格波动大时，即使持仓量不变，持仓金额也会大幅变化，因此建议和 OiChgRat（纯持仓量变化率）联合拆解贡献。',
        },
        {
            'title': '反转信号',
            'body': '当持仓金额涨幅持续为正但持仓量变化率（OiChgRat）转负时，说明金额上升主要由价格驱动而非新增仓位，追涨资金不足，这是趋势末期常见形态，反转概率上升；持仓金额涨幅从高位快速大幅回落（持仓去化+价格下跌双击），是最强力的趋势反转确认信号。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            OIAmt_t &:= OI_t \cdot P_t, \\[4pt]
            X_t     &:= \frac{OIAmt_t - OIAmt_{t-N}}{OIAmt_{t-N}}.
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('10d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE_ADJUSTED, **kwargs) -> pd.Series:
        oi    = product.MIN1[DataColumn.OPEN_ADJUSTED_INTEREST]
        price = product.MIN1[P]
        oi_amt = oi * price

        if isinstance(N, pd.Timedelta) and isinstance(RF, pd.Timedelta):
            steps = max(1, int(N / RF))
        else:
            steps = int(N) if not isinstance(N, pd.Timedelta) else 1

        oi_amt_prev = oi_amt.shift(steps).replace(0, float('nan'))
        chg_rat = ((oi_amt - oi_amt_prev) / oi_amt_prev).fillna(0.0).replace([float('inf'), -float('inf')], 0.0)
        return self.sync_signal(chg_rat)

if __name__ == '__main__':
    ff = OiAmtChgRat()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
