# =============================================================================
# Factors/VpAmihud.py
# Amihud 非流动性因子
#
# |r_t| / Turnover_t：单位成交额所产生的价格冲击幅度。
# 高值表示流动性差（小额成交即带来大幅波动），低值表示流动性充裕。
# 滚动均值后取负号可作为流动性正向因子（流动性好 → 回报稳）。
#   r_t = |pct_change(P, RF)|
#   X_t = MA(r_t / TO_t, N)（均值平滑，避免单期极端值干扰）
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VpAmihud(FactorFamily):
    """
    Amihud 非流动性因子。

    衡量单位成交额引起的价格冲击（价格冲击 = |收益率| / 成交额）。
    在 N 期窗口内取均值以平滑极端值。
    高值 → 非流动性强（价格对成交额敏感）；
    低值 → 流动性充裕（成交额不易推动价格）。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动均值窗口，默认 20d
        RF (Timedelta)  : 收益率步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = 'Amihud 非流动性'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VpAmihud 是经典的非流动性因子，用单位成交额对应的价格波动幅度来衡量市场的价格冲击成本。',
        },
        {
            'title': '它在看什么',
            'body': '如果很小的成交额就能带来较大的价格变动，那么市场流动性偏差，因子会偏高；如果需要较大的成交额才会推动价格，说明市场更深、更不容易被冲击，因子会偏低。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '流动性本身就是一种风险和约束。非流动性高的资产通常要求更高风险补偿，也更容易出现价格失真、交易拥挤和冲击放大。Amihud 类指标因此常能反映风险溢价、执行难度和市场承载力。',
        },
        {
            'title': '使用提醒',
            'body': '成交额异常值、停牌时段和极端行情会明显影响该指标，实际使用时通常需要对零成交额或极端值做稳健处理。',
        },
        {
            'title': '反转信号',
            'body': 'Amihud 非流动性因子与反转的关系：（1）非流动性突然飙升（相同成交额对应更大价格冲击），市场流动性恶化，大单冲击效应增大，价格更容易在流动性恢复后回归；（2）长期高非流动性资产在获得新增流动性供给时（如大机构入场），价格的超跌成分容易被快速修复；（3）非流动性溢价理论认为，高非流动性往往对应更高的预期收益补偿——若持有时间足够长，逆向做多高非流动性低价值资产可以获得反转收益。反转在以下情况更有效：非流动性突然上升是由恐慌性单向卖单引发，而非基本面恶化；时间窗口越短，非流动性指标的噪声越大。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \frac{1}{N}\sum_{s=t-N+1}^{t}
                     \frac{|r_s|}{TO_s}
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price    = product.MIN1[P]
        turnover = product.MIN1[DataColumn.TURNOVER]
        abs_ret  = price.pct_change(RF).abs()
        illiq    = abs_ret / turnover.replace(0, float('nan'))
        # 滚动平均平滑极端值
        factor = illiq.rolling(N).mean()
        factor = factor.fillna(0.0)
        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = VpAmihud()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
