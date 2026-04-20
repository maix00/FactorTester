# =============================================================================
# Factors/Mm.py
# 动量因子（价格区间方向动量）
#
# Mm 因子度量过去 F 期内最高价与最低价的相对位置关系：
#   - 若最高价出现在最低价之后（上涨趋势），X > 0
#   - 若最低价出现在最高价之后（下跌趋势），X < 0
#   - 若同时出现，X = 0
# 参数：H（高价列）、L（低价列）、F（信号频率，支持 'S' 表示反转）
# =============================================================================
import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools import DataColumn, Product, FactorFamily
from tools.parameters import DataColumnParam, FinRangeParam, TimeDeltaParam
from typing import List, Dict, Any, Sequence, Tuple

class Mm(FactorFamily):
    """
    价格区间方向动量因子。

    在过去 F 周期内，找到最高价出现时间 h_t 和最低价出现时间 l_t：
      - h_t > l_t（最高价在后）→ 看涨，X = (PH - PL) / PH > 0
      - h_t < l_t（最低价在后）→ 看跌，X = (PL - PH) / PL < 0（即 -(PH-PL)/PH）
      - h_t = l_t → X = 0

    支持反转模式 F='S'，此时因子值取反。

    参数：
        H (DataColumn) : 高价列，默认 HIGH
        L (DataColumn) : 低价列，默认 LOW
        F (Timedelta)  : 信号频率，支持 'S'（反转）
    """

    params = [
        DataColumnParam('H'),   # 用于计算最高价的列
        DataColumnParam('L'),   # 用于计算最低价的列
    ]

    math_expr = '''
        \\begin{aligned}
            PH_t &:= \\max_{t-F \\leq s \\leq t} H_s, \\\\[5pt]
            h_t  &:= \\arg\\max_{t-F \\leq s \\leq t} H_s, \\\\[5pt]
            PL_t &:= \\min_{t-F \\leq s \\leq t} L_s, \\\\[5pt]
            l_t  &:= \\arg\\min_{t-F \\leq s \\leq t} L_s, \\\\[5pt]
            X_t  &:= 
            \\begin{cases}
                \\frac{PH_t - PL_t}{PH_t}, & h_t < l_t, \\\\
                \\frac{PL_t - PH_t}{PL_t}, & l_t < h_t, \\\\
                0, & h_t = l_t.
            \\end{cases}
        \\end{aligned}
    '''

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('1d'),
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        """
        批量计算 Mm 因子。

        参数：
            products : 品种列表
            F        : 信号频率（Timedelta 或 'S' 反转）
            H        : 高价列
            L        : 低价列

        返回：
            DataFrame，列为 Product，索引为信号时间戳 MultiIndex
        """
        factors = {}
        for product in products:
            # 按 F 聚合，同时计算 H 的最大值/idxmax 和 L 的最小值/idxmin
            day_high, day_low, idx_high, idx_low = (
                product.MIN1.groupby(freq=F)
                .agg({H.name: ['max', 'idxmax'], L.name: ['min', 'idxmin']})
                .pipe(lambda x: (x[(H.name,'max')], x[(L.name,'min')], x[(H.name,'idxmax')], x[(L.name,'idxmin')]))
            )
            # 若最低价出现时间早于最高价（下跌趋势），交换 high/low 使计算结果为负
            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high

            # 反转模式：因子值取反
            if F == 'S':
                factors[product] = - factors[product]

        return pd.DataFrame(factors)

if __name__ == '__main__':
    ff = Mm()
    # ff.add_params(F = '2d')
    # ff.add_params(F = 'S')
    # ff.add_params(F = '2min')
    # ff.add_params(F = '5min')
    # ff.add_params(F = '10min')
    # ff.add_params(F = '15min')
    ff.clear_params()
    ff.add_params(F = '1d')
    fft = ff.test(start_calc_point='2024-01-03 09:00:00', timezone='Asia/Shanghai', categories=['0'])
    print(fft.products)
    # fft = ff.test(return_freq='6h', start_calc_point='2024-01-03 09:00:00')