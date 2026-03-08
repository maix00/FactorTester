import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from CNFutures import CNFutures
from Products import Product, DataColumn, DataFreq
from Factor import FactorFamily
from Parameter import DataColumnParam, FinRangeParam, TimeParam
from typing import List, Dict, Any, Sequence, Tuple

class Mm(FactorFamily): # Day Momentum

    additional_params = [
        DataColumnParam('H').set_default_value(DataColumn.HIGH),
        DataColumnParam('L').set_default_value(DataColumn.LOW),
        (FinRangeParam('F', 'S') + TimeParam(flag='pos')).set_default_value('1d'),
    ]

    def func(self, products: Sequence[Product], F: Any = '1d',
             H: DataColumn = DataColumn.HIGH,
             L: DataColumn = DataColumn.LOW, **kwargs) -> pd.DataFrame:
        factors = {}
        data_freq = pd.Timedelta('1min')
        for product in products:
            df = product.MIN1.get_data()
            
            _TD = DataFreq.DAY1.name
            _TM = DataFreq.MIN1.name

            if F == '1d':
                df = df.reset_index()
                df = df.rename(columns={_TD: str(_TD), _TM: str(_TM)})
                df = df.set_index([str(_TD), str(_TM)])
                idx = str(_TD)
            elif F == 'S':
                _TD_ = df.index.get_level_values(_TD).to_series().reset_index(drop=True) # type: ignore
                _TM_ = df.index.get_level_values(_TM).to_series().reset_index(drop=True) # type: ignore
                time_part = _TM_.dt.time
                cond = (time_part >= pd.Timestamp('09:00').time()) & (time_part <= pd.Timestamp('15:00').time())
                end_session = _TD_ + pd.Timedelta('9 hours')
                end_session[cond] = _TD_[cond] + pd.Timedelta('15 hours')
                df.index = pd.MultiIndex.from_arrays([_TD_, end_session], names=[_TD, 'end_session'])
                idx = [_TD, 'end_session']
            else:
                continue

            day_high, day_low, idx_high, idx_low = (
                df.groupby(idx)
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
    # ff.add_params(return_freq = '5h')
    # ff.change_default_return_freq('3h')
    # ff.add_params(F = 'S')
    # ff.add_params(F = '5h')
    fft = ff.test()
