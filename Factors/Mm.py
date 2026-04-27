# =============================================================================
# Factors/Mm.py
# 动量因子（价格区间方向动量）
#
# Mm 因子度量过去 F 期内最高价与最低价的相对位置关系：
#   - 若最高价出现在最低价之后（上涨趋势），X > 0
#   - 若最低价出现在最高价之后（下跌趋势），X < 0
#   - 若同时出现，X = 0
# 参数：H（高价列）、L（低价列）、F（信号频率）
# =============================================================================
import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam
from typing import Any

class Mm(FactorFamily):
    """
    价格区间方向动量因子。

    在过去 F 窗口内，找到最高价出现的相对位置 h_pos 和最低价出现的相对位置 l_pos：
      - h_pos > l_pos（最高价在后）→ 看涨，X = (PH - PL) / PH > 0
      - l_pos > h_pos（最低价在后）→ 看跌，X = (PL - PH) / PL < 0
      - h_pos = l_pos → X = 0

    参数：
        H (DataColumn) : 高价列，默认 HIGH
        L (DataColumn) : 低价列，默认 LOW
        F (Timedelta)  : 信号频率
    """

    params = [
        DataColumnParam('H'),   # 用于计算最高价的列
        DataColumnParam('L'),   # 用于计算最低价的列
    ]

    chinese_name = '区间方向动量'
    description_sections = [
        {
            'title': '这是什么',
            'body': 'Mm 是一个区间方向动量因子。它不直接看净涨跌幅，而是观察在最近一个信号窗口里，最高价和最低价谁先出现、谁后出现，从价格路径的先后顺序判断这段行情更像是先跌后涨，还是先涨后跌。',
        },
        {
            'title': '它在看什么',
            'body': '如果窗口内最低点先出现、最高点后出现，说明价格在这段时间里走出了更完整的上行路径，因子取正；反过来，如果最高点先出现、最低点后出现，则说明这段路径更像先冲高再回落，因子取负。因子幅度还会用区间高低点的距离做归一化，因此不仅区分方向，也区分路径强弱。',
        },
        {
            'title': '为什么这个因子可能行得通',
            'body': '很多趋势并不是由单个时点的收盘价决定，而是由一段时间里的路径结构决定。区间内“低点在前、高点在后”通常意味着买盘逐步占优、回撤被承接，路径上更接近趋势推进；而“高点在前、低点在后”更接近冲高失败或趋势衰竭。这个因子因此能在净收益率之外，补充价格路径信息。',
        },
        {
            'title': '使用提醒',
            'body': 'Mm 更适合拿来刻画趋势结构，而不是极短线噪声。窗口太短时，最高点和最低点的先后顺序很容易被偶然波动扰动；窗口太长时，又可能把多段不同状态混在一起。',
        },
        {
            'title': '反转信号',
            'body': '当窗口内最高价和最低价先后顺序频繁互换、或者区间高低点距离非常小时，说明路径结构本身不稳定，此时因子容易产生噪声信号，反转概率上升。反转信号在以下情况更值得关注：（1）价格已经连续多个窗口维持同一方向，但近窗口内最新高低点先后关系开始动摇；（2）市场成交量明显萎缩，路径方向由少量突破极值的价格铸成而非连续推进；（3）宏观事件或资金面约束使得当前路径结构难以延续。',
        },
    ]

    math_expr = '''
        \\begin{aligned}
            PH_t &:= \\mathrm{RollingMax}_{F}(H)_t, \\\\[5pt]
            h_t  &:= \\mathrm{RollingArgMax}_{F}(H)_t, \\\\[5pt]
            PL_t &:= \\mathrm{RollingMin}_{F}(L)_t, \\\\[5pt]
            l_t  &:= \\mathrm{RollingArgMin}_{F}(L)_t, \\\\[5pt]
            X_t  &:=
            \\begin{cases}
                \\frac{PH_t - PL_t}{PH_t}, & h_t > l_t, \\\\
                \\frac{PL_t - PH_t}{PL_t}, & l_t > h_t, \\\\
                0, & h_t = l_t.
            \\end{cases}
        \\end{aligned}
    '''

    def func_timeseries(self, product: Product, H: DataColumn = DataColumn.HIGH_ADJUSTED,
                        L: DataColumn = DataColumn.LOW_ADJUSTED, **kwargs) -> pd.Series:
        """
        计算单品种 Mm 因子。

        使用滚动窗口 F，通过 argmax/argmin 获取窗口内最高价和最低价的相对位置，
        从而判断趋势方向。不使用 groupby。

        参数：
            product : 品种对象
            F       : 滚动窗口（信号频率）
            H       : 高价列
            L       : 低价列

        返回：
            按频率 F 同步后的 pd.Series
        """
        F = kwargs.get('F', kwargs.get('$F', pd.Timedelta('1d')))
        high = product.MIN1[H]
        low  = product.MIN1[L]

        ph = high.rolling(F).max()
        pl = low.rolling(F).min()

        # argmax/argmin 返回窗口内的相对位置（0=最旧，n-1=最新）
        h_pos = high.rolling(F).apply(np.argmax, raw=True)
        l_pos = low.rolling(F).apply(np.argmin,  raw=True)

        ph_safe = ph.replace(0, float('nan'))
        pl_safe = pl.replace(0, float('nan'))

        up   = h_pos > l_pos   # 最高价在最低价之后 → 上涨动量
        down = l_pos > h_pos   # 最低价在最高价之后 → 下跌动量

        factor = ((ph - pl) / ph_safe * up + (pl - ph) / pl_safe * down).fillna(0.0)

        return self.sync_signal(factor)
if __name__ == '__main__':
    ff = Mm()
    ff.clear_params()
    ff.add_params(F='1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai', categories=['0'])
    print(fft.products)
