from datetime import datetime
from enum import Enum
import itertools
import pandas as pd
import numpy as np
from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any
import os

from Products import DataColumn, Futures, ProductBase, DataFreq
from CNFutures import get_all_products
import logging

from tqdm import tqdm

sift_volume_ratio = 0.8
default_test_start_date = '2025-01-01'
default_test_end_date = '2025-05-31'
default_plot_test_start_date = '2025-01-01'
default_plot_test_end_date = '2025-12-31'
logger_dir_path_default = '../data/factor_tester_log/'
factor_info_path = '../data/Factors/'

class ReturnPriceCols(Enum):
    NEXT_OPEN_TO_OPEN = (('first', DataColumn.OPEN), ('first', DataColumn.OPEN))
    NEXT_OPEN_TO_OPEN_ADJUSTED = (('first', DataColumn.OPEN_ADJUSTED), ('first', DataColumn.OPEN_ADJUSTED))
    THIS_CLOSE_TO_CLOSE = (('last', DataColumn.CLOSE), ('last', DataColumn.CLOSE))
    THIS_CLOSE_TO_CLOSE_ADJUSTED = (('last', DataColumn.CLOSE_ADJUSTED), ('last', DataColumn.CLOSE_ADJUSTED))

PriceColumnMapping = {
    'C': 'close_price',
    'O': 'open_price',
    'H': 'highest_price',
    'L': 'lowest_price',
    'CA': 'close_price_adjusted',
    'OA': 'open_price_adjusted',
    'HA': 'highest_price_adjusted',
    'LA': 'lowest_price_adjusted',
    'V': 'vwap',
    'T': 'twap',
}

OtherColumnMapping = {
    'V': 'volume',
    'A': 'amount',
    'T': 'turnover',
    'P': 'premium',
    'D': 'dividend',
    'R': 'right',
    'E': 'exchange_rate',
    'S': 'spread',
    'M': 'mid_price',
    'I': 'implied_volatility',
    'B': 'bid_price',
    'A': 'ask_price',
    'BW': 'bid_width',
    'AW': 'ask_width',
    'BW/A': 'bid_ask_width_ratio',
    'B/A': 'bid_ask_ratio',
    'B/A/M': 'bid_ask_mid_ratio'
}

import inspect

def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    products = get_all_products()
    tester = FactorTester(products=products, time_range=time_range)
    return tester

class Factor(ProductBase):
    def __init__(self, name: str, func: Callable[..., pd.DataFrame],
                 freq: Any, params: Dict[str, Any]):
        super().__init__(name=name)
        self.func = func
        self.freq = freq
        self.params = params
        self.table: pd.DataFrame = pd.DataFrame()
        self.end_market_signal = False
        self.ic_series: pd.Series = pd.Series()
        self.ic_stats: pd.Series = pd.Series()
        self.report: pd.DataFrame = pd.DataFrame()

    def calc(self, products: Any) -> pd.DataFrame:
        if isinstance(products, ProductBase):
            products = [products]
        products = list(products)
        self.table = self.func(products)
        for col in self.table.columns:
            if max(self.table[col].dropna()) == min(self.table[col].dropna()):
                self.table.drop(columns=col, inplace=True)
        if isinstance(self.table.index, pd.MultiIndex):
            idx_lvls = len(self.table.index.names)
            self.freq = pd.Timedelta(self.table.index.get_level_values(idx_lvls-1).to_series().diff().mode()[0])
        else:
            self.freq = pd.Timedelta(self.table.index.to_series().diff().mode()[0])
            if self.freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0:
                self.end_market_signal = True
        return self.table
    
class FactorFamily:
    params_space: Dict[str, List[Any]] = {}

    def __init__(self, name_stem: Optional[str] = None):
        self.name_stem = name_stem if name_stem else self.__class__.__name__
        self.set_default_params()
        self.freq = None
    
    def func(self, products: Sequence[ProductBase], *args, **kwargs) -> pd.DataFrame:
        raise NotImplementedError("请在子类中实现 `factor_func` 方法。")
    
    def set_default_params(self, **kwargs):
        self._params_list = [{key: self.params_space[key][0] for key in self.params_space.keys()}]

    def clear_params(self):
        self._params_list = []
    
    def _check_in_space(self, **kwargs):
        for key in kwargs:
            if key not in self.params_space:
                raise KeyError(f"参数 '{key}' 不在定义的参数空间中")
            if kwargs[key] not in self.params_space[key]:
                raise ValueError(f"参数 '{key}' 的值 '{kwargs[key]}' 不在允许范围 {self.params_space[key]} 内")
            
    def add_params(self, **kwargs):
        self._check_in_space(**kwargs)
        new_params = {key: kwargs[key] if key in kwargs else self.params_space[key][0] for key in self.params_space.keys()}
        if new_params not in self._params_list:
            self._params_list.append(new_params)

    def set_all_params(self):
        all_combinations = list(itertools.product(*self.params_space.values()))
        self._params_list = [dict(zip(self.params_space.keys(), combination)) for combination in all_combinations]

    def get_name(self, **params):
        params_str = '|'.join(f"{key}:{value}" for key, value in params.items())
        return f"{self.name_stem}|{params_str}" if params_str else self.name_stem

    def get_factors(self):
        factors = []
        for params in self._params_list:
            factor_name = self.get_name(**params)
            factor_func = lambda products: self.func(products, **params)
            factors.append(Factor(name=factor_name, func=factor_func, freq=self.freq, params=params))
        return factors
    
    def test(self, n_groups: int = 5, plot_n_group_list: Optional[List[int]] = None, 
            categories: Optional[str|List[str]] = None,
            sift_volume_ratio: float = sift_volume_ratio):
        
        factor_cache_path = os.path.join(factor_info_path, self.name_stem, self.name_stem + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()
        
        tester = get_factor_tester(time_range=(default_test_start_date, default_test_end_date))
        tester.sift_product_by_category(categories=categories)
        price_cols = ReturnPriceCols.NEXT_OPEN_TO_OPEN

        factors = self.get_factors()
        tester.calc_factor(factors)
        tester.calc_ic(return_price_cols=price_cols)
        
        for factor in tqdm(factors, desc=f"Ploting {n_groups}-Groups"):
            
            _, _, report_df = tester.test_by_group(factor, return_price_cols=price_cols,
                plot_flag=True, n_groups=n_groups, plot_n_group_list=plot_n_group_list,
                time_range=(default_plot_test_start_date, default_plot_test_end_date),
                plot_show=False, sift_volume_ratio=sift_volume_ratio,
                plot_remark_str=','.join(categories) if categories else None,
                )
            
            report_dict = {}
            for col in report_df.columns:
                key_0 = f"{col} {report_df.index[0]}"
                report_dict[key_0] = report_df.loc[report_df.index[0], col]
            for col in report_df.columns:
                key_1 = f"{col} {report_df.index[1]}"
                report_dict[key_1] = report_df.loc[report_df.index[1], col]

            new_row = pd.Series({
                'factor_stem': self.name_stem,
                'serial_num': pd.Timestamp.now(),
                'factor_name': factor.name,
                'factor_freq': factor.freq,
                'start_date': tester.start_date,
                'end_date': tester.end_date,
                'sift_volume_ratio': sift_volume_ratio,
                'categories': categories,
            } | factor.params | factor.ic_stats.to_dict() | report_dict)
            factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
            factor.report = factor_table
            factor_table.to_csv(factor_cache_path, index=False)
        
class FactorTester:
    def __init__(self, products: Sequence[ProductBase],
                 time_range: Optional[Tuple] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        
        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:

            self.logger.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

            if logger_console:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)
                self.logger.addHandler(console_handler)

            if logger_file:
                if not os.path.exists(logger_dir_path):
                    os.makedirs(logger_dir_path)
                logger_file_path = os.path.join(logger_dir_path, "factor_tester_{}.log".format(datetime.now().strftime("%Y%m%d")))
                file_handler = logging.FileHandler(logger_file_path, encoding='utf-8')
                file_handler.setFormatter(formatter)
                self.logger.addHandler(file_handler)
        
        self.products = set(products)
        self.all_products = set(products)
        self.sift_product_by_empty_data_bool = False
        self.factors = []
        self.start_date = pd.to_datetime(time_range[0]) if time_range is not None else None
        self.end_date = pd.to_datetime(time_range[1]) if time_range is not None else None
        self.logger.info(f"FactorTester initialized with {len(self.products)} products")
    
    def sift_product(self, sift_func: Callable[[ProductBase], bool]):
        new_products = set()
        for product in self.products:
            if sift_func(product):
                new_products.add(product)
        self.products = new_products

    def sift_product_by_category(self, categories: Optional[str|List[str]] = None):
        if categories is None:
            return
        if isinstance(categories, str):
            categories = [categories]
        new_products = set()
        for product in self.products:
            for category in categories:
                if product.get_category() == category:
                    new_products.add(product)
                    break
        self.products = new_products

    def sift_product_by_empty_data(self):
        new_products = set()
        for product in self.products:
            df = product.get_some_data()
            if not df.empty and max(df[product.get_col_name(DataColumn.VOLUME)]) > 0:
                new_products.add(product)
        self.products = new_products
        self.sift_product_by_empty_data_bool = True

    def sift_product_by_volumes(self, ratio: Optional[float] = None, time_col: Optional[str] = None,
                                time_range: Optional[Any] = None) -> Set[ProductBase]:
        if ratio is None:
            return self.products
        if not self.sift_product_by_empty_data_bool:
            self.sift_product_by_empty_data()
        results = {}
        for product in self.products:
            results[product] = product.get_slices(target_cols=DataColumn.VOLUME, time_col=time_col, time_range=time_range).sum().values
        sorted_products = sorted(results, key=lambda x: results[x], reverse=True)
        return set(sorted_products[:int(len(sorted_products) * ratio)])

    def calc_return_by_factor(self, factor: Factor, return_freq: Any, 
                              price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN,
                            ) -> pd.DataFrame:
        
        returns = {}
        assert factor.table is not None and factor.freq is not None
        return_freq = pd.Timedelta(return_freq)
        assert return_freq <= factor.freq
        for product in factor.table.columns:
            assert isinstance(product, ProductBase)
            PC = price_cols
            if isinstance(product, Futures):
                if price_cols == ReturnPriceCols.NEXT_OPEN_TO_OPEN:
                    PC = ReturnPriceCols.NEXT_OPEN_TO_OPEN_ADJUSTED
                elif price_cols == ReturnPriceCols.THIS_CLOSE_TO_CLOSE:
                    PC = ReturnPriceCols.THIS_CLOSE_TO_CLOSE_ADJUSTED
            all_f = product.get_available_freqs()
            if factor.end_market_signal and DataFreq.DAY1 in all_f \
                and return_freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0:
                data_freq = DataFreq.DAY1
            else:
                assert len(all_f) > 0
                data_freq = sorted([_f for _f in all_f if _f.value <= factor.freq \
                                    and factor.freq.total_seconds() % _f.value.total_seconds() == 0], 
                                    key=lambda x: x.value)[-1]
            assert return_freq.total_seconds() % data_freq.value.total_seconds() == 0, f"return_freq必须是数据频率{data_freq}的整数倍，现在为{return_freq}"
            time_cols_mapping = product.time_cols_mapping[data_freq]
            time_col_freq = sorted(
                [_f for _f in time_cols_mapping.keys() if return_freq.total_seconds() % _f.value.total_seconds() == 0], 
                key=lambda x: x.value)[-1]
            time_col = time_cols_mapping[time_col_freq]
            df = product.get_data(data_freq)
            if isinstance(product, Futures):
                for _, col in PC.value:
                    if product.check_col_is_adjusted(col) and col not in df.columns:
                        product.adjust_cols(data_freq, product.get_col_name_nonadjusted(col))
            df_grouped = df.groupby(time_col)
            period = int(return_freq.total_seconds() / time_col_freq.value.total_seconds())
            offset = 0
            if PC.value[0][0] == 'first':
                df = df_grouped.first()
                offset = -1
            else:
                df = df_grouped.last()
            df = df[product.get_col_name(PC.value[0][1])].pct_change(periods=period).shift(-period+offset)
            idx_loc = factor.table.index.intersection(df.index)
            returns[product] = df.loc[idx_loc]
        return pd.DataFrame(returns)
        
    def calc_factor(self, factors: Factor|List[Factor]):
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors
        self.sift_product_by_empty_data()
        for factor in tqdm(factors, desc='Calculating factors'):
            factor.calc(self.products)
    
    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)

    def calc_ic(self, return_price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN,
                factors: Optional[Factor|List[Factor]] = None,
                return_freq: Optional[str|pd.Timedelta] = None,
                time_range: Optional[Tuple] = None,) -> tuple[pd.DataFrame, pd.DataFrame]:
                        
        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        ic_series = {}
        ic_stats = {}

        for factor in tqdm(factors, desc='Calculating IC'):
            factor_rank = self.calc_rank(factor.table)
            return_df = self.calc_return_by_factor(factor, return_freq=return_freq if return_freq is not None else factor.freq,
                                                   price_cols=return_price_cols)
            return_rank = self.calc_rank(return_df)
            dt_index = factor_rank.index.intersection(return_rank.index)
            if start_date is not None:
                dt_index = dt_index[dt_index >= start_date]
            if end_date is not None:
                dt_index = dt_index[dt_index <= end_date]
            ic = []
            coverage = []
            for dt in dt_index:
                f = factor_rank.loc[dt]
                r = return_rank.loc[dt]
                valid = f.notna() & r.notna()
                coverage.append(valid.sum())
                if valid.sum() > 1:
                    ic.append(pd.Series(f[valid]).corr(r[valid], method='spearman'))
                else:
                    ic.append(np.nan)
            factor.ic_series = pd.Series(ic, index=dt_index)
            ic_series[factor.name] = factor.ic_series
            avg_coverage = np.mean(coverage)
            stats_df = self.ic_stats(ic_series[factor.name])
            stats_df['avg_coverage'] = avg_coverage
            factor.ic_stats = stats_df
            ic_stats[factor.name] = stats_df
        return pd.DataFrame(ic_series), pd.DataFrame(ic_stats)

    def ic_stats(self, ic_series: pd.Series) -> pd.Series:
        mean = ic_series.mean()
        std = ic_series.std()
        ir = mean / std if std != 0 else np.nan
        t_stat = mean / (std / np.sqrt(len(ic_series.dropna()))) if std != 0 and len(ic_series.dropna()) > 1 else np.nan
        max_ic = ic_series.max()
        min_ic = ic_series.min()
        stats_df = pd.Series({
            'mean': mean, 'std': std, 'IR': ir, 't_stat': t_stat, 'max': max_ic, 'min': min_ic
        })
        return stats_df

    def test_by_group(self, factors: Optional[Factor|List[Factor]] = None,
                      return_price_cols: ReturnPriceCols = ReturnPriceCols.NEXT_OPEN_TO_OPEN,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      return_freq: Optional[str|pd.Timedelta] = None,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None) -> \
        Tuple[Dict[str, Dict[str, List[ProductBase]]], Dict[str, Dict[str, float]], pd.DataFrame]:

        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)

        if plot_flag and plot_n_group_list is not None:
            plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        group_names = [n_groups_name.get(i, 'group_' + str(i)) for i in range(n_groups)][::-1]
        groups = {name: {} for name in group_names}
        returns_groups = {name: {} for name in group_names}

        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        report_df = pd.DataFrame()
        for factor in factors:

            returns = self.calc_return_by_factor(factor, return_freq=return_freq if return_freq is not None else factor.freq,
                                            price_cols=return_price_cols)
            
            for dt, row in factor.table.iterrows():
                dt_str = dt
                sifted_products = self.sift_product_by_volumes(ratio=sift_volume_ratio, time_range=(dt, dt))
                sorted_products = row.dropna().sort_values(ascending=False)
                sorted_products = sorted_products[sorted_products.index.isin(sifted_products)]
                n = len(sorted_products)
                idx = list(sorted_products.index)
                
                # Split contracts into n_groups groups
                if n > 0:
                    idx_array = np.asarray(idx)
                    split = np.array_split(idx_array, min(n, n_groups))
                    
                    # Fill groups from bottom to top (ascending order of factor values)
                    for i, group_products in enumerate(split):
                        group_idx = n_groups - 1 - i  # Reverse order: bottom group first
                        groups[group_names[group_idx]][dt_str] = list(group_products)
                        returns_groups[group_names[group_idx]][dt_str] = np.mean(np.asarray(returns.loc[dt_str][group_products].values, dtype=float))
                
                # Fill remaining groups (if n < n_groups) with empty lists
                for i in range(min(n, n_groups), n_groups):
                    groups[group_names[i]][dt_str] = []
                    returns_groups[group_names[i]][dt_str] = np.nan

            report_groups = {}
            for name in group_names:

                dates = list(returns_groups[name].keys()) if returns_groups[name] else []
                test_dates = [date for date in dates if self.start_date <= date] if self.start_date else dates
                test_dates = [date for date in test_dates if date <= self.end_date] if self.end_date else dates
                dates = [date for date in dates if start_date <= date] if start_date else dates
                dates = [date for date in dates if date <= end_date] if end_date else dates
                
                returns = [returns_groups[name][date] for date in dates]
                returns_series = pd.Series(returns).dropna()
                cumulative_returns = (1 + returns_series).cumprod()

                test_returns = [returns_groups[name][date] for date in test_dates]
                test_returns_series = pd.Series(test_returns).dropna()
                test_cumulative_returns = (1 + test_returns_series).cumprod()

                metrics = {

                '(Test) Total Return': (test_cumulative_returns.iloc[-1] - 1) * 100 if len(test_cumulative_returns) > 0 else 0,
                '(Test) Annual Return': ((test_cumulative_returns.iloc[-1]) ** (252 / len(test_cumulative_returns)) - 1) * 100 if len(test_cumulative_returns) > 1 else 0,
                '(Test) Volatility': pd.Series(test_returns).std() * np.sqrt(252) * 100,
                '(Test) Sharpe Ratio': (pd.Series(test_returns).mean() * 252) / (pd.Series(test_returns).std() * np.sqrt(252)) if pd.Series(test_returns).std() != 0 else 0,
                '(Test) Max Drawdown': ((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() * 100 if len(test_cumulative_returns) > 0 else 0,
                '(Test) Calmar Ratio': ((test_cumulative_returns.iloc[-1] ** (252 / len(test_cumulative_returns)) - 1) * 100) / (((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() * 100) if ((test_cumulative_returns.cummax() - test_cumulative_returns) / test_cumulative_returns.cummax()).max() != 0 else 0,
                '(Test) Win Rate': (pd.Series(test_returns) > 0).sum() / len(pd.Series(test_returns)) * 100 if len(pd.Series(test_returns)) > 0 else 0,
                '(Test) Mean Return': pd.Series(test_returns).mean() * 100,
                '(Test) Skewness': pd.Series(test_returns).skew(),
                '(Test) Kurtosis': pd.Series(test_returns).kurtosis(),

                'Total Return': (cumulative_returns.iloc[-1] - 1) * 100 if len(cumulative_returns) > 0 else 0,
                'Annual Return': ((cumulative_returns.iloc[-1]) ** (252 / len(cumulative_returns)) - 1) * 100 if len(cumulative_returns) > 1 else 0,
                'Volatility': pd.Series(returns).std() * np.sqrt(252) * 100,
                'Sharpe Ratio': (pd.Series(returns).mean() * 252) / (pd.Series(returns).std() * np.sqrt(252)) if pd.Series(returns).std() != 0 else 0,
                'Max Drawdown': ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100 if len(cumulative_returns) > 0 else 0,
                'Calmar Ratio': ((cumulative_returns.iloc[-1] ** (252 / len(cumulative_returns)) - 1) * 100) / (((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100) if ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() != 0 else 0,
                'Win Rate': (pd.Series(returns) > 0).sum() / len(pd.Series(returns)) * 100 if len(pd.Series(returns)) > 0 else 0,
                'Mean Return': pd.Series(returns).mean() * 100,
                'Skewness': pd.Series(returns).skew(),
                'Kurtosis': pd.Series(returns).kurtosis(),

                }

                name = int(name.split('_')[-1])
                report_groups[name] = pd.Series(metrics)
            
            report_df = pd.DataFrame(report_groups).T.sort_index()  # Convert to DataFrame, transpose, and sort by name
            if not plot_flag or (plot_flag and plot_show):
                with pd.option_context('display.max_rows', None, 'display.max_columns', None):
                    print("Group Performance Summary:\n", report_df)

            if plot_flag:
                import matplotlib.pyplot as plt
                # Plot average open returns per group over time
                plt.figure(figsize=(12, 6))
                start_date = start_date if start_date is not None else self.start_date
                end_date = end_date if end_date is not None else self.end_date
                # print(start_date, end_date)
                dates = []  # Initialize dates as an empty list
                for name in group_names:
                    if plot_n_group_list is not None and name.split('_')[-1] not in [str(n) for n in plot_n_group_list]:
                        continue
                    dates = list(returns_groups[name].keys()) if returns_groups[name] else []
                    dates = [date for date in dates if start_date <= date] if start_date else dates
                    dates = [date for date in dates if date <= end_date] if end_date else dates
                    returns = [returns_groups[name][date] for date in dates]
                    cumulative_returns = []
                    prev_value = 10000
                    for ret in returns:
                        if not np.isnan(ret):
                            prev_value = prev_value * (1 + ret)
                        cumulative_returns.append(prev_value)
                    plt.plot([str(date) for date in dates], cumulative_returns, label=name)
                plt.xlabel('Date')
                plt.ylabel('Average Next Day Open Return')
                if plot_remark_str:
                    plt.title(f'Average Open Return: {factor.name} - {plot_remark_str}')
                else:
                    plt.title(f'Average Open Return: {factor.name}')
                plt.rcParams['font.sans-serif'] = ['Kaiti SC']
                plt.legend()
                # Only show every nth tick to reduce crowding
                n_ticks = 10
                assert len(dates) > 0, "No dates available for plotting."
                tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
                plt.xticks(ticks=[str(dates[i]) for i in tick_indices], rotation=45)
                plt.tight_layout()
                if save_plot:
                    factor_stem = factor.name.split('|')[0]
                    figs_path = os.path.join(factor_info_path, factor_stem, 'figs')
                    if not os.path.exists(figs_path):
                        os.makedirs(figs_path)
                    plt.savefig(os.path.join(figs_path, f'{factor.name}_{start_date}_{end_date}.png'))
                if plot_show:
                    plt.show()

        return groups, returns_groups, report_df