import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from CNFutures import CNFutures
from Products import Product, DataColumn, DataFreq
from Factor import FactorFamily
from Parameter import DataColumnParam, FinRangeParam, TimeDeltaParam
from typing import List, Dict, Any, Sequence, Tuple

class Mm(FactorFamily): # Day Momentum

    params = [
        DataColumnParam('H'),
        DataColumnParam('L'),
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
        factors = {}
        for product in products:

            day_high, day_low, idx_high, idx_low = (
                product.MIN1.groupby(self, freq=F)
                .agg({H.name: ['max', 'idxmax'], L.name: ['min', 'idxmin']})
                .pipe(lambda x: (x[(H.name,'max')], x[(L.name,'min')], x[(H.name,'idxmax')], x[(L.name,'idxmin')]))
            )

            mask = idx_low < idx_high
            temp_high = day_high.copy()
            day_high.loc[mask] = day_low.loc[mask]
            day_low.loc[mask] = temp_high.loc[mask]
            factors[product] = (day_high - day_low) / day_high
            
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