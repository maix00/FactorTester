import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from CNFutures import CNFutures
from Products import Product, DataColumn
from Factor import FactorFamily
from Parameter import DataColumnParam, FinRangeParam
from typing import List, Dict, Any, Sequence, Tuple

class Mm(FactorFamily): # Day Momentum

    additional_params = [
        DataColumnParam('H').set_default_value(DataColumn.HIGH),
        DataColumnParam('L').set_default_value(DataColumn.LOW),
        FinRangeParam('F', ['1d', 'S', '5h', '3h'])
    ]

    def funcMIN1(self, products: Sequence[Product],
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _H = product.get_col_name(H)
            df = product.get_data('1min')[_H]
            factors[product] = df
        return pd.DataFrame(factors)
    
    def funcMIN5(self, products: Sequence[Product],
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            _H = product.get_col_name(H)
            df = product.get_data('1min')[_H]
            factors[product] = df[4::5]
        return pd.DataFrame(factors)
    
    def func(self, products: Sequence[Product], F: str = '1d',
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        for product in products:
            df = product.get_data('1min')
            
            _H = product.get_col_name(H)
            _L = product.get_col_name(L)
            _TD = product.get_col_name(DataColumn.TIME_COL_DAY)
            _TM = product.get_col_name(DataColumn.TIME_COL_MIN)

            if F == '1d':
                idx = _TD
            elif F == 'S':
                _TD_ = df.index.get_level_values(_TD).to_series().reset_index(drop=True)
                _TM_ = df.index.get_level_values(_TM).to_series().reset_index(drop=True)
                time_part = _TM_.dt.time
                cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
                end_session = _TD_ + pd.Timedelta('9 hours')
                end_session[cond] = _TD_[cond] + pd.Timedelta('15 hours')
                df.index = pd.MultiIndex.from_arrays([_TD_, end_session], names=[_TD, 'end_session'])
                idx = [_TD, 'end_session']
            elif F == '5h' or F == '3h':
                period = pd.Timedelta('5 hours') % pd.Timedelta('1 min')
                idx = _TD
            else:
                continue

            day_high, day_low, idx_high, idx_low = (
                df.groupby(idx)
                .agg({_H: ['max', 'idxmax'], _L: ['min', 'idxmin']})
                .pipe(lambda x: (x[(_H,'max')], x[(_L,'min')], x[(_H,'idxmax')], x[(_L,'idxmin')]))
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
    ff.add_params(return_freq = '5h')
    # ff.change_default_return_freq('3h')
    # ff.add_params(F = 'S')
    # ff.add_params(F = '5h')
    fft = ff.test()
