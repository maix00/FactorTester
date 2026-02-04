import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from Products import ProductBase
from FactorTester import FactorGrid, PriceColumnMapping, OtherColumnMapping
from typing import List, Dict, Any

class Illiq(FactorGrid): # Day Momentum

    params_space: Dict[str, List[Any]] = {
        'PC': ['C'],
        'PV': ['V'],
    }

    default_params: Dict[str, Any] = {'PC': 'C', 'PV': 'V'}

    def _factor_func(self, data: Dict[ProductBase, pd.DataFrame], data_freq: Dict[ProductBase, pd.Timedelta],
                     PC: str = 'C', PV: str = 'V') -> pd.DataFrame:
        assert all(data_freq[product] < pd.Timedelta('1 day') for product in data_freq)
        assert len({v for v in data_freq.values()}) == 1
        factors = {}
        for product, df in data.items():
            close = df[PriceColumnMapping[PC]].groupby('trading_day').last()
            volume = df[OtherColumnMapping[PV]].groupby('trading_day').sum()
            returns = close.pct_change()
            factors[product] = returns / volume
        return pd.DataFrame(factors)

if __name__ == '__main__':
    Illiq().factor_grid_test()