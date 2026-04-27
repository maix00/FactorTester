# =============================================================================
# Factors/OiAmtChgRatio.py
# 持仓金额变化比值因子
#
# 当前持仓金额与 N 期前的比值：
#   OIAmt_t = OI_t * P_t
#   X_t = OIAmt_t / OIAmt_{t-N}
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class OiAmtChgRatio(FactorFamily):
    """
    持仓金额变化比值因子。

    当前持仓金额（OI × 价格）与 N 期前的倍数关系，
    与 OiAmtChgRat（变化率）相比保留绝对比例含义。

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

    chinese_name = '持仓金额变化比值'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'OiAmtChgRatio 是持仓金额变化比值因子，用持仓量乘以价格估算持仓金额后，计算当前与 N 期前的比值（倍数），衡量市场总资金锁定规模的相对扩张程度。',
        },
        {
            'title': '它在看什么',
            'body': '比值为 2 表示持仓金额翻倍；为 0.5 表示腰斩。相比变化率，比值对初始基数更稳定，跨时间段的可比性更强。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '资金锁定量的倍数变化（而非绝对变化）更能反映市场参与者对该品种的整体态度变化。从"持仓金额翻倍"这一维度，可以识别资金快速涌入的"爆发期"和资金快速撤离的"危险期"。',
        },
        {
            'title': '使用提醒',
            'body': '在合约换月前后，主力合约的持仓量会出现跳变，持仓金额也会随之失真；建议在分析时过滤换月期附近的异常点，或使用所有合约合计而非主力合约。',
        },
        {
            'title': '反转信号',
            'body': '与 OiAmtChgRat 类似，持仓金额比值极度偏高后若价格不涨（或开始下跌），资金被套的规模非常大，强制平仓带来的反转力量更猛烈；持仓金额比值处于极低位（资金大幅撤离后）时，边际做空力量减弱，反弹弹性更大。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            OIAmt_t &:= OI_t \cdot P_t, \\[4pt]
            X_t     &:= \frac{OIAmt_t}{OIAmt_{t-N}}.
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

        oi_prev = oi_amt.shift(steps).replace(0, float('nan'))
        ratio = (oi_amt / oi_prev).fillna(1.0).replace([float('inf'), -float('inf')], 1.0)
        return self.sync_signal(ratio)

if __name__ == '__main__':
    ff = OiAmtChgRatio()
    ff.clear_params()
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
