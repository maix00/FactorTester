# =============================================================================
# Factors/MmMACD.py
# MACD 柱状线动量因子
#
# 快慢 EMA 差（DIF）与 DIF 的 EMA（DEA）之差，即 MACD 柱：
#   DIF_t = EMA(P, fast) - EMA(P, slow)
#   DEA_t = EMA(DIF, signal)
#   X_t = DIF_t - DEA_t
# 归一化后除以价格使其可跨品种比较。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmMACD(FactorFamily):
    """
    MACD 柱状线动量因子。

    计算快线（short EMA）与慢线（long EMA）之差（DIF），
    再减去 DIF 的信号线（signal EMA），得到 MACD 柱，
    除以当期价格进行归一化以便跨品种比较。

    参数：
        P      (DataColumn) : 价格列，默认 CLOSE
        Fast   (Timedelta)  : 快线 EMA 窗口，默认 12d
        Slow   (Timedelta)  : 慢线 EMA 窗口，默认 26d
        Signal (Timedelta)  : 信号线 EMA 窗口，默认 9d
        F      (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('Fast',   default_value='12d'),
        WindowParam('Slow',   default_value='26d'),
        WindowParam('Signal', default_value='9d'),
    ]

    chinese_name = '指数均线趋势加速'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmMACD 是基于快慢均线差及其信号线的趋势加速度因子。相比只看快慢均线之差，它进一步看“快慢差本身是否还在扩张或收敛”。',
        },
        {
            'title': '它在看什么',
            'body': '当短期均线相对长期均线持续走强，并且这种强势还在加速时，MACD 柱值会偏正；反之则偏负。因子通常再做价格归一化，以便跨品种比较。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '市场从盘整切换到趋势时，往往先表现为短周期价格对长周期价格的领先，随后表现为这种领先幅度继续扩大。MACD 类构造抓的正是这种“趋势斜率变化”，因此在趋势启动和趋势衰减阶段都比较敏感。',
        },
        {
            'title': '使用提醒',
            'body': 'MACD 对参数组合比较敏感。太短会过度追噪声，太长会明显滞后；因此更适合与成交量、波动率或持仓类确认信号一起使用。',
        },
        {
            'title': '反转信号',
            'body': '以下情况出现时，MACD 类因子容易出现方向反转：（1）MACD 柱高度从高位开始收缩（顶/底背离的前兆）；（2）MACD 线与价格出现顶背离（价格创新高但 MACD 未创新高）或底背离；（3）快慢均线形成死叉或金叉，因子符号从正转负或从负转正。MACD 反转在以下环境更可靠：震荡区间而非单边；背离持续数周以上而非单根 K 线；成交量在背离时萎缩而不是放大。趋势加速期背离可以反复欺骗，在趋势类资产中单用 MACD 反转信号成功率较低。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            DIF_t &:= EMA(P, Fast)_t - EMA(P, Slow)_t \\[5pt]
            DEA_t &:= EMA(DIF, Signal)_t \\[5pt]
            X_t   &:= (DIF_t - DEA_t) / P_t
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, Fast: Any = pd.Timedelta('12d'),
                        Slow: Any = pd.Timedelta('26d'),
                        Signal: Any = pd.Timedelta('9d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        # ewm 的 span 参数只接受数值；Timedelta 窗口用 halflife 表达
        ema_fast = price.ewm(halflife=Fast, adjust=False).mean()
        ema_slow = price.ewm(halflife=Slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(halflife=Signal, adjust=False).mean()
        macd_bar = (dif - dea) / price.replace(0, float('nan'))
        macd_bar = macd_bar.fillna(0.0)
        return self.sync_signal(macd_bar)
if __name__ == '__main__':
    ff = MmMACD()
    ff.clear_params()
    ff.add_params(F='1d', Fast='12d', Slow='26d', Signal='9d')
    ff.add_params(F='1d', Fast='6d',  Slow='13d', Signal='5d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
