import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.products.Product import Product
from tools import DataColumn
from tools.factors.Factor import FactorFamily
from tools.parameters.Parameter import DataColumnParam, FinRangeParam, TimeDeltaParam
from typing import List, Dict, Any, Sequence, Tuple

class MmRet(FactorFamily): # Momentum of Return

    params = [
        DataColumnParam('P', DataColumn.CLOSE),
        TimeDeltaParam('F', flag='pos', default_value='1d'),
    ]

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('1d'),
             P: DataColumn = DataColumn.CLOSE, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _, info = product.MIN1._get_data(self, 
                extra_time_col_freq=F,
                extra_time_col_bfill=True,
                extra_time_col_groupby=True)
            df_grouped = info['grouped']
            factors[product] = df_grouped.last()[P.name].pct_change(1)

        return pd.DataFrame(factors)

if __name__ == '__main__':
    ff = MmRet()
    ff.add_params(F = '10d')
    ff.add_params(F = '5d')
    ff.add_params(F = '3d')
    ff.add_params(F = '2d')
    # # ff.add_params(F = '2min')
    # ff.add_params(F = '5min')
    # ff.add_params(F = '10min')
    # ff.add_params(F = '15min')
    fft = ff.test(start_cal_time=('1min', '2024-01-03 09:00:00'))
    print(fft.products)
    # fft = ff.test(return_freq='6h', start_cal_time=('1min', '2024-01-03 09:00:00'))