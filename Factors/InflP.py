import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import ProductBase
from Factor import FactorGrid, PriceColumnMapping
from typing import List, Dict, Any

class InflP(FactorGrid): # Inflection Point

    params_space: Dict[str, List[Any]] = {
        'PC': list(PriceColumnMapping.keys()),
        'W': [5, 9],
        'WS': [3, 5],
        'S': [1, 0],
    }

    default_params: Dict[str, Any] = {'PC': 'CA', 'W': 5, 'WS': 1, 'S': 1}

    def _factor_func(self, data: Dict[ProductBase, pd.DataFrame], data_freq: Dict[ProductBase, pd.Timedelta],
                     PC: str = 'CA', WS: int = 1, W: int = 5, S: int = 1) -> pd.DataFrame:
        assert all(data_freq[product] < pd.Timedelta('1 day') for product in data_freq)
        assert len({v for v in data_freq.values()}) == 1
        factors = {}
        for product, df in data.items():
            price = df[PriceColumnMapping[PC]]
            direction = pd.Series(np.sign(price.diff()), index=price.index)
            inflection = (direction != direction.shift(WS)) & (direction != 0) & (direction.shift(WS) != 0)
            if S == 1:
                for idx in range(WS - 1):
                    inflection[idx::WS] = False
            daily_inflection = inflection.astype(int).groupby('trading_day').sum()
            rolling_mean = daily_inflection.rolling(window=W, min_periods=1).mean().shift(1)
            factors[product] = daily_inflection - rolling_mean
        return pd.DataFrame(factors)

if __name__ == '__main__':
    InflP().factor_grid_test()