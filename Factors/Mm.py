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
        (FinRangeParam('F', 'S') + TimeDeltaParam(flag='pos')).change_default_value('1d'),
    ]

    def func(self, products: Sequence[Product], F: Any = pd.Timedelta('1d'),
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _TD = DataFreq.DAY1.name
            _TM = DataFreq.MIN1.name

            if F == 'S':
                df = product.MIN1.get_data(self)
                _TD_ = df.index.get_level_values(_TD).to_series().reset_index(drop=True)
                _TM_ = df.index.get_level_values(_TM).to_series().reset_index(drop=True)
                time_part = _TM_.dt.time
                cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
                signal_time = _TD_ + pd.Timedelta('9 hours')
                signal_time[cond] = _TD_[cond] + pd.Timedelta('15 hours')
                df.index = pd.MultiIndex.from_arrays([_TD_, signal_time], names=[_TD, 'signal_time'])
                idx = [_TD, 'signal_time']
                df_grouped = df.groupby(idx)
            else:
                df, info = product.MIN1._get_data(self, 
                    extra_time_col_freq=F, 
                    extra_time_col_bfill=True,
                    extra_time_col_groupby=True)
                df_grouped = info['grouped']

            day_high, day_low, idx_high, idx_low = (
                df_grouped
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
    ff.add_params(F = '2d')
    ff.add_params(F = '2min')
    ff.add_params(F = '5min')
    ff.add_params(F = '10min')
    ff.add_params(F = '15min')
    fft = ff.test(start_cal_time=('1min', '2024-01-03 09:00:00'), categories=['1'])
    print(fft.products)
    # fft = ff.test(return_freq='6h', start_cal_time=('1min', '2024-01-03 09:00:00'))