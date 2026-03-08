import numpy as np
import pandas as pd
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Products import ProductBase
from Factor import FactorGrid, PriceColumnMapping, OtherColumnMapping
from typing import List, Dict, Any
from tqdm import tqdm

class Alpha005(FactorGrid): # Inflection Point

    params_space: Dict[str, List[Any]] = {
        'PC': list(PriceColumnMapping.keys()),
        'VC': ['V'], 
        'VRW': [5], 
        'PRW': [5], 
        'CW': [5], 
        'MW': [3]
    }

    default_params: Dict[str, Any] = {'VC': 'V', 'PC': 'HA', 'VRW': 5, 'PRW': 5, 'CW': 5, 'MW': 3}

    def _factor_func(self, data: Dict[ProductBase, pd.DataFrame], data_freq: Dict[ProductBase, pd.Timedelta],
                     VC: str = 'V', VRW: int = 5, PC: str = 'HA', PRW: int = 5, CW: int = 5, MW: int = 3) -> pd.DataFrame:
        assert all(data_freq[product] < pd.Timedelta('1 day') for product in data_freq)
        assert len({v for v in data_freq.values()}) == 1
        factors = {}
        for product, df in tqdm(data.items()):
            volume = df[OtherColumnMapping[VC]].groupby('trading_day').sum()
            price = df[PriceColumnMapping[PC]].groupby('trading_day').max()
            tsrank_volume = volume.rolling(window=VRW, min_periods=1).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])#.shift(1)
            tsrank_price = price.rolling(window=PRW, min_periods=1).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])#.shift(1)
            corr_volume_price = tsrank_volume.rolling(window=CW, min_periods=1).corr(tsrank_price)
            tsmax_corr = corr_volume_price.rolling(window=MW, min_periods=1).max()#.shift(1)
            factors[product] = - tsmax_corr
        return pd.DataFrame(factors)

if __name__ == '__main__':
    Alpha005().factor_grid_test()