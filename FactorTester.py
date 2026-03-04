from datetime import datetime
from enum import Enum
import itertools
import pandas as pd
import numpy as np
from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any
import os

from Products import Futures, ProductBase, DataFreq
from CNFutures import get_categories_with_products, get_cnfutures
import logging

from tqdm import tqdm

sift_volume_ratio = 0.8
default_test_start_date = '2025-01-01'
default_test_end_date = '2025-05-31'
default_plot_test_start_date = '2025-01-01'
default_plot_test_end_date = '2025-12-31'
logger_dir_path_default = '../data/factor_tester_log/'
factor_info_path = '../data/Factors/'

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

class Factor:
    def __init__(self, name: str, func: Callable[..., pd.DataFrame],
                 freq: Any, params: Dict[str, Any]):
        self.name = name
        self.func = func
        self.freq = freq
        self.params = params
        self.data: pd.DataFrame = pd.DataFrame()
        self.end_market_signal = False

    def calc(self, products: Any) -> pd.DataFrame:
        if isinstance(products, ProductBase):
            products = [products]
        products = list(products)
        self.data = self.func(products)
        for col in self.data.columns:
            if max(self.data[col].dropna()) == min(self.data[col].dropna()):
                self.data.drop(columns=col, inplace=True)
        if isinstance(self.data.index, pd.MultiIndex):
            idx_lvls = len(self.data.index.names)
            self.freq = pd.Timedelta(self.data.index.get_level_values(idx_lvls-1).to_series().diff().mode()[0])
        else:
            self.freq = pd.Timedelta(self.data.index.to_series().diff().mode()[0])
            if self.freq.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0:
                self.end_market_signal = True
        return self.data
    
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
            category_names: Optional[str|List[str]] = None,
            sift_volume_ratio: float = sift_volume_ratio):
        
        factor_cache_path = os.path.join(factor_info_path, self.name_stem, self.name_stem + '.csv')
        if not os.path.exists(factor_info_path):
            os.makedirs(factor_info_path)
        if os.path.exists(factor_cache_path) and os.path.isfile(factor_cache_path):
            factor_table = pd.read_csv(factor_cache_path)
        else:
            factor_table = pd.DataFrame()
        
        tester = get_factor_tester(category_names=category_names)
        
        for factor in self.get_factors():

            tester.calc_factor(factor)

            _, ic_stats = tester.calc_ic()
            
            _, _, report_df = tester.group_classes(factor, 
                plot_flag=True, n_groups=n_groups, plot_n_group_list=plot_n_group_list,
                start_date=default_plot_test_start_date, end_date=default_plot_test_end_date,
                plot_show=False,
                sift_volume_ratio=sift_volume_ratio, plot_remark_str=','.join(category_names) if category_names else None,
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
                'sift_method': 'volume',
                'sift_volume_ratio': sift_volume_ratio,
                'category_names': category_names,
            } | factor.params | ic_stats.iloc[:, 0].to_dict() | report_dict)
            factor_table = pd.concat([factor_table, new_row.to_frame().T], ignore_index=True)
            factor_table.to_csv(factor_cache_path, index=False)
        
class FactorTester:
    def __init__(self, products: Sequence[ProductBase],
                 start_date: Optional[str] = None, end_date: Optional[str] = None,
                 volume_col: str = 'volume',
                 futures_flag: bool = True, futures_adjust_col: Optional[List[str]] = None,
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
        
        self.volume_col = volume_col
        self.products = set(products)
        self.all_products = set(products)
        self.sift_product_by_empty_data_bool = False
        self.factors = []
        self.product_mapping = {}
        self.return_data = {}
        self.start_date = pd.to_datetime(start_date) if start_date is not None else None
        self.end_date = pd.to_datetime(end_date) if end_date is not None else None
        self.futures_flag = futures_flag
        self.futures_adjust_col = futures_adjust_col
        self.logger.info(f"FactorTester initialized with {len(self.products)} products")
    
    def sift_product_by_empty_data(self):
        new_products = set()
        for product in self.products:
            df = product.get_some_data()
            if not df.empty and max(df[self.volume_col]) > 0:
                new_products.add(product)
        self.products = new_products
        self.sift_product_by_empty_data_bool = True

    def sift_product_by_volumes(self, ratio: Optional[float] = None,
                                time_range: Optional[Any] = None) -> Set[ProductBase]:
        if ratio is None:
            return self.products
        if not self.sift_product_by_empty_data_bool:
            self.sift_product_by_empty_data()
        results = {}
        for product in self.products:
            results[product] = product.get_slices(self.volume_col, time_range=time_range).sum().values
        sorted_products = sorted(results, key=lambda x: results[x], reverse=True)
        return set(sorted_products[:int(len(sorted_products) * ratio)])

    def calc_return_by_factor(self, factor: Factor, return_period: Any, 
                              price_cols: Tuple[Tuple[str, str], Tuple[str,str]] 
                                = (('first', 'open_price_adjusted'), ('first', 'open_price_adjusted')),
                            ) -> pd.DataFrame:
        
        assert all(price_cols[0][i] == price_cols[1][i] for i in range(1))
        assert all(price_cols[i][0] in ['last', 'first'] for i in range(1))
        assert all(any(price_cols[i][1].startswith(prefix) for prefix in ['open_price', 'close_price']) for i in range(1))
        
        returns = {}
        assert factor.data is not None and factor.freq is not None
        return_period = pd.Timedelta(return_period)
        assert return_period <= factor.freq
        for product in factor.data.columns:
            assert isinstance(product, ProductBase)
            all_f = product.get_available_freqs()
            if factor.end_market_signal and DataFreq.DAY1 in all_f \
                and return_period.total_seconds() % pd.Timedelta('1 day').total_seconds() == 0:
                data_freq = DataFreq.DAY1
            else:
                assert len(all_f) > 0
                data_freq = sorted([_f for _f in all_f if _f.value <= factor.freq \
                                    and factor.freq.total_seconds() % _f.value.total_seconds() == 0], 
                                    key=lambda x: x.value)[-1]
            assert return_period.total_seconds() % data_freq.value.total_seconds() == 0, f"return_period必须是数据频率{data_freq}的整数倍，现在为{return_period}"
            time_cols_mapping = product.time_cols_mapping[data_freq]
            time_col_freq = sorted(
                [_f for _f in time_cols_mapping.keys() if return_period.total_seconds() % _f.value.total_seconds() == 0], 
                key=lambda x: x.value)[-1]
            time_col = time_cols_mapping[time_col_freq]
            df = product.get_data(data_freq)
            if isinstance(product, Futures):
                for _, col in price_cols:
                    if col.endswith('_adjusted') and col not in df.columns:
                        product.adjust_cols(data_freq, col.removesuffix('_adjusted'))
            df_grouped = df.groupby(time_col)
            period = int(return_period.total_seconds() / time_col_freq.value.total_seconds())
            offset = 0
            if price_cols[0][0] == 'first':
                df = df_grouped.first()
                offset = -1
            else:
                df = df_grouped.last()
            df = df[price_cols[0][1]].pct_change(periods=period).shift(-period+offset)
            idx_loc = factor.data.index.intersection(df.index)
            returns[product] = df.loc[idx_loc]
        return pd.DataFrame(returns)
        
    def calc_factor(self, factors: Factor|List[Factor], 
                    sift_settings: Optional[Dict[str, Any]] = None):
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors
        self.sift_product_by_empty_data()
        for factor in tqdm(factors, desc='Factor processing'):
            factor.calc(self.products)
    
    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)

    def calc_ic(self, return_freq: Optional[str|pd.Timedelta] = None,
                start_date: Optional[str|pd.Timestamp] = None, 
                end_date: Optional[str|pd.Timestamp] = None) -> tuple[pd.DataFrame, pd.DataFrame]:
                        
        ic_series = {}
        ic_stats = {}
        for factor in self.factors:
            factor_rank = self.calc_rank(factor.data)
            return_df = self.calc_return_by_factor(factor, return_period=return_freq if return_freq is not None else factor.freq,
                                                   price_cols=(('first', 'open_price_adjusted'), ('first', 'open_price_adjusted')))
            return_rank = self.calc_rank(return_df)
            dt_index = factor_rank.index.intersection(return_rank.index)
            start_date = pd.to_datetime(start_date) if start_date is not None else self.start_date
            end_date = pd.to_datetime(end_date) if end_date is not None else self.end_date
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
            ic_series[factor.name] = pd.Series(ic, index=dt_index)
            avg_coverage = np.mean(coverage)
            stats_df = self.ic_stats(ic_series[factor.name])
            stats_df['avg_coverage'] = avg_coverage
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

    def group_classes(self, factor: Factor, n_groups: int = 5, 
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      start_date: Optional[str|pd.Timestamp] = None, end_date: Optional[str|pd.Timestamp] = None,
                      return_freq: Optional[str|pd.Timedelta] = None,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None) -> \
        Tuple[Dict[str, Dict[str, List[ProductBase]]], Dict[str, Dict[str, float]], pd.DataFrame]:

        returns = self.calc_return_by_factor(factor, return_period=return_freq if return_freq is not None else factor.freq,
                                            price_cols=(('first', 'open_price_adjusted'), ('first', 'open_price_adjusted')))

        # Plot adjustment for group numbers
        plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        group_names = ['group_' + str(i) for i in range(n_groups)]
        group_names = group_names[::-1]
        groups = {name: {} for name in group_names}
        returns_groups = {name: {} for name in group_names}

        start_date = pd.to_datetime(start_date) if start_date is not None else None
        end_date = pd.to_datetime(end_date) if end_date is not None else None
        
        for dt, row in factor.data.iterrows():
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
    
def get_factor_tester(
        category_names: Optional[str|List[str]] = None,
        start_date: Optional[str] = default_test_start_date, 
        end_date: Optional[str] = default_test_end_date) -> FactorTester:
    
    if category_names is not None:
        if isinstance(category_names, str):
            category_names = [category_names]
        products = [product for category_name in category_names for product in get_categories_with_products().get(category_name, [])]
    else:
        products = get_cnfutures()
    
    tester = FactorTester(products=products,
                          start_date=start_date, end_date=end_date,
                          futures_flag=True, futures_adjust_col=['close_price', 'open_price', 'highest_price', 'lowest_price'])
    
    return tester

# def factor_test(factors: FactorGrid|tuple[str, Callable]|List[tuple[str, Callable]],
#                 n_groups: int = 5, plot_n_group_list: Optional[List[int]] = None,):
    
#     # import cProfile
#     # import pstats

#     # profiler = cProfile.Profile()
#     # profiler.enable()

#     tester = get_factor_tester()
#     tester.calc_factor(factors)

#     ic_series, stats = tester.calc_ic(factors=factors, return_price_col='open_price_adjusted',
#                               return_daily_anchors='open_market')#, return_freq='5 days')
#     # import matplotlib.pyplot as plt

#     # plt.figure(figsize=(14, 6))
#     # for col in ic_series.columns:
#     #     plt.plot(ic_series.index, ic_series[col], label=col, alpha=0.7)
#     # plt.xlabel('Date')
#     # plt.ylabel('IC')
#     # plt.title('IC Series Over Time')
#     # plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
#     # plt.grid(True, alpha=0.3)
#     # plt.tight_layout()
#     # plt.show()

#     print('IC Stats Median t_stat:', stats.loc['t_stat'].median())
#     if len(stats.columns) >= 4:
#         stats = stats.T.sort_values('t_stat', ascending=False)
#         mid = len(stats.columns)//2
#         stats = pd.concat([
#             stats[:2].T, stats[mid:mid+1].T, stats[-1:].T
#         ], axis=1)
#     print('Selected by t_stat:\n', stats)
#     factor_names = stats.columns.tolist()
    
#     loop_bool = True
#     while loop_bool:
#         which_factor = input(f'选择哪一个因子进行分类回测 (1 - {len(factor_names)}): ')
#         if which_factor.isdigit() and 1 <= int(which_factor) <= len(factor_names):
#             which_factor = int(which_factor) - 1
#             groups, returns_groups, _ = tester.group_classes(factor_names[which_factor], 
#                                                 plot_flag=True, n_groups=n_groups, plot_n_group_list=plot_n_group_list,
#                                                 start_date='2025-01-01', end_date='2025-12-31',
#                                                 return_price_col='open_price_adjusted', return_daily_anchors='open_market'
#                                                 )
#         else:
#             loop_bool = False

#     # # Get the earliest five dates from the 'top' group
#     # earliest_dates = sorted(groups['group_0'].keys())[:5]
#     # for date in earliest_dates:
#     #     print(date, groups['group_0'][date])
#     #     print(date, returns_groups['group_0'][date])
#     #     pass

#     # profiler.disable()
#     # # 输出分析结果
#     # stats = pstats.Stats(profiler)
#     # stats.sort_stats('cumulative')  # 按累计时间排序
#     # stats.print_stats(20)  # 显示前20个耗时最多的函数