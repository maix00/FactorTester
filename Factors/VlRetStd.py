# =============================================================================
# Factors/VlRetStd.py
# 收益率波动率因子（滚动标准差）
#
# 在过去 N 个 RF 周期内，收益率的滚动标准差：
#   X_t = std(r_{t-N+1}, ..., r_t)，r_s = (P_s - P_{s-RF}) / P_{s-RF}
# 高值表示近期价格振荡剧烈，低值表示趋势平稳。
# =============================================================================
import pandas as pd
from typing import Any
import os, sys; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, WindowParam


class VlRetStd(FactorFamily):
    """
    收益率波动率因子（滚动标准差）。

    在 N 期窗口内计算收益率序列的标准差，
    作为近期价格波动幅度的直接度量。

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

    chinese_name = '收益率标准差'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'VlRetStd 是收益率标准差因子，也就是最经典的已实现波动率刻画方式之一。',
        },
        {
            'title': '它在看什么',
            'body': '它直接统计最近窗口中收益率围绕其均值的离散程度。离散越大，说明价格变化越不稳定，风险环境越激烈。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '波动率聚类是金融市场最稳健的经验事实之一，即高波动之后更容易继续高波动，低波动之后更容易继续低波动。已实现波动率因此不仅能刻画风险状态，也常能预测未来波动环境本身。',
        },
        {
            'title': '使用提醒',
            'body': '它对极端收益很敏感，且无法区分上涨波动和下跌波动。若你更关心尾部方向，最好配合偏度或下行波动因子。',
        },
        {
            'title': '反转信号',
            'body': '收益率标准差因子与反转的关系：（1）标准差从低位突然快速上升，市场不确定性增加，方向反转概率同步上升；（2）标准差处于极高位时，均值回归力量通常强于趋势延续力量，短期内反转频率更高；（3）Volpremium 效应：在期货市场，高波动率往往对应负预期收益（风险定价），持续高波动后的修复阶段常有反向机会。实践建议：在高波动率环境中主动缩短持有周期或降低仓位，等待波动率收缩后再观察趋势延续性。',
        },
    ]

    math_expr = r'''
        \begin{aligned}
            X_t &:= \sigma\!\left(r_{t-N+1},\, \ldots,\, r_t\right)
        \end{aligned}
    '''

    def func_timeseries(self, product: Product, N: Any = pd.Timedelta('20d'), RF: Any = pd.Timedelta('1d'),
                        P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.Series:
        price = product.MIN1[P]
        ret = price.pct_change(RF)
        vol = ret.rolling(N).std()
        vol = vol.fillna(0.0)
        return self.sync_signal(vol)
if __name__ == '__main__':
    ff = VlRetStd()
    ff.clear_params()
    ff.add_params(F='1d', N='20d', RF='1d')
    ff.add_params(F='1d', N='10d', RF='1d')
    ff.add_params(F='1d', N='5d',  RF='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai')
