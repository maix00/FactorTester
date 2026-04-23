# =============================================================================
# Factors/MmSkew.py
# 收益率偏度因子
#
# 在过去 N 个 RF 周期内，收益率序列的滚动偏度：
#   X_t = skewness(r_{t-N+1}, ..., r_t)
# 正偏（右偏）表示偶有大幅上涨；负偏（左偏）表示偶有大幅下跌。
# 作为反转信号：极端正偏后价格趋于回归，可取负号使用。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class MmSkew(FactorFamily):
    """
    收益率偏度因子。

    在 N 期窗口内计算收益率的滚动三阶矩（偏度），
    捕捉收益率分布的不对称性。

    参数：
        P  (DataColumn) : 价格列，默认 CLOSE
        N  (Timedelta)  : 滚动窗口，默认 20d
        RF (Timedelta)  : 单期步长，默认 1d
        F  (Timedelta)  : 输出信号频率
    """

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        WindowParam('N',  default_value='20d'),
        WindowParam('RF', default_value='1d'),
    ]

    chinese_name = '收益率偏度'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'MmSkew 是收益率偏度因子，衡量最近窗口内收益分布是否更偏向“偶发大涨”还是“偶发大跌”。',
        },
        {
            'title': '它在看什么',
            'body': '当收益分布右尾更长时，偏度为正；左尾更长时，偏度为负。它关注的是收益分布形状，而不只是均值或波动率。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '很多市场风险并不体现在平均收益，而体现在尾部结构。正偏可能意味着上涨主要依赖少数大幅拉升，负偏则可能说明下跌以跳水或踩踏形式集中出现。分布形状往往能反映拥挤、脆弱性和风险补偿结构。',
        },
        {
            'title': '使用提醒',
            'body': '偏度估计需要足够样本，窗口太短时非常不稳定；而且它通常更适合作为辅助风险刻画，而不是单独的主信号。',
        },
        {
            'title': '反转信号',
            'body': '偏度因子的反转逻辑如下：（1）极度负偏（左尾很长）通常意味着近期出现了单次或少次大幅下跌，此类急跌后常出现超卖反弹；（2）极度正偏（右尾很长）则意味着近期出现了单次或少次大幅急涨——急拉后的回落是更常见的结局；（3）当偏度从极值快速向 0 回归时，说明尾部事件的影响正在被常规交易消化，趋势可能恢复。反转在以下情况更有效：偏度极端伴随成交量急放，说明事件性因素主导；若同期波动率也处于高位，均值回归的时机通常更快。注意：偏度估计对异常值非常敏感，窗口短时该因子信噪比很低，要避免对单期偏度值过度反应。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \operatorname{skew}(r_{t-N+1},\, \ldots,\, r_t)
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret = price.pct_change(RF)
        skew = ret.rolling(N).skew()
        skew = skew.fillna(0.0)
        return self.sync_signal(skew)
if __name__ == '__main__':
    ff = MmSkew()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
