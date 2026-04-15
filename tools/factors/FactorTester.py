import os
import logging
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime
from weakref import WeakValueDictionary 
from typing import Optional, Sequence, Tuple, Callable, Any, Set, List, Dict

from tools.factors.Factor import Factor
from tools.products.Product import Product
from tools import SerialObject, DataColumn, DataFreq
from tools.factors.Parameters import StartCalcPointParam, FactorNextPeriodReturns

from Settings import get_all_products, logger_dir_path_default, factor_info_path

def _signal_time(obj: Any):
    return obj if not isinstance(obj, tuple) else obj[-1]

class FactorTester(SerialObject):
    _instances = WeakValueDictionary()

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FT', alias=alias)
    
    def __init__(self, products: Sequence[Product],
                 alias: Optional[str] = None,
                 time_range: Optional[Tuple] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='FT', alias=alias)

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
                    logger_file_path = os.path.join(logger_dir_path, f"factor_tester_{self.serial_number}_{datetime.now().strftime('%Y%m%d')}.log")
                    file_handler = logging.FileHandler(logger_file_path, encoding='utf-8')
                    file_handler.setFormatter(formatter)
                    self.logger.addHandler(file_handler)
            
            self.products = set(products)
            self.all_products = set(products)
            self.sift_product_by_empty_data_bool = False
            self.factors = []
            if time_range is not None:
                self.update_time_range(time_range)
            else:
                self.start_date = None
                self.end_date = None
            self.logger.info(f"FactorTester initialized with {len(self.products)} products")
    
    def update_time_range(self, time_range: Tuple):
        self.start_date = pd.to_datetime(time_range[0])
        self.end_date = pd.to_datetime(time_range[1])
        self.logger.info(f"Time range updated to {self.start_date} - {self.end_date}")

    def sift_product(self, sift_func: Callable[[Product], bool]):
        new_products = set()
        for product in self.products:
            if sift_func(product):
                new_products.add(product)
        self.products = new_products

    def sift_product_by_empty_data(self):
        new_products = set()
        for product in self.products:
            product.set_StartCalcPointParam(StartCalcPointParam, StartCalcPointParam.get_value(self.factors[0]))
            df = product.get_some_data(copy=False)
            if not df.empty and max(df[DataColumn.VOLUME.name]) > 0:
                new_products.add(product)
        self.products = new_products
        self.sift_product_by_empty_data_bool = True

    def sift_product_by_volumes(self, ratio: Optional[float] = None, time_col: Optional[Any] = None,
                                time_range: Optional[Any] = None) -> Set[Product]:
        if ratio is None:
            return self.products
        if not self.sift_product_by_empty_data_bool:
            self.sift_product_by_empty_data()
        results = {}
        for product in self.products:
            sum_volume = product.get_slices(target_cols=DataColumn.VOLUME, 
                                                  time_col=time_col, time_range=time_range,
                                                  copy=False).sum().values
            if sum_volume == 0:
                continue
            results[product] = sum_volume
        sorted_products = sorted(results, key=lambda x: results[x], reverse=True)
        return set(sorted_products[:int(len(sorted_products) * ratio)])
        
    def calc_factor(self, factors: Factor|List[Factor]):
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors
        self.sift_product_by_empty_data()
        for factor in tqdm(self.factors, desc=f'Calculate factors for {len(self.products)} products'):
            factor.calc(self.products)
    
    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)
    
    def calc_ic(self, returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                return_freq: Optional[Any] = None, factors: Optional[Factor|List[Factor]] = None,
                time_range: Optional[Tuple] = None,) -> tuple[pd.DataFrame, pd.DataFrame]:
                        
        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        ic_series = {}
        ic_stats = {}

        for factor in tqdm(factors, desc='Calculating IC'):
            factor_rank = self.calc_rank(factor.table)
            if factor.returns.empty or (not factor.returns.empty and DataFreq(factor.get_current_return_freq()) != DataFreq(return_freq)):
                return_df = factor.calc_returns(next_return=True, returns_col=returns_col, return_freq=return_freq)
            else:
                return_df = factor.returns
            assert not return_df.empty
            return_rank = self.calc_rank(return_df)
            dt_index = factor_rank.index.intersection(return_rank.index)
            if start_date is not None:
                dt_index = dt_index[[start_date <= _signal_time(k) for k in dt_index]]
            if end_date is not None:
                dt_index = dt_index[[_signal_time(k) <= end_date for k in dt_index]]
            ic = []
            coverage = []
            for dt in dt_index:
                f = factor_rank.loc[dt]
                r = return_rank.loc[dt]
                valid = f.notna() & r.notna()
                coverage.append(valid.sum())
                if valid.sum() > 1:
                    if f[valid].nunique() > 1 and r[valid].nunique() > 1:
                        ic.append(pd.Series(f[valid]).corr(r[valid], method='spearman'))
                    else:
                        ic.append(np.nan)
                else:
                    ic.append(np.nan)
            factor.ic_series = pd.Series(ic, index=dt_index)
            ic_series[factor] = factor.ic_series
            avg_coverage = np.mean(coverage)
            stats_df = self.ic_stats(ic_series[factor])
            stats_df['avg_coverage'] = avg_coverage
            factor.ic_stats = stats_df
            ic_stats[factor] = stats_df
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
                      returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None, **kwargs) -> Tuple[Any, Any, pd.DataFrame]:

        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)

        if plot_flag and plot_n_group_list is not None:
            plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        products = {i: {} for i in range(n_groups)}
        returns = {i: {} for i in range(n_groups)}
        names = {i: n_groups_name.get(i, 'group_' + str(i)) for i in range(n_groups)}

        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date
        
        report_df = pd.DataFrame()
        for factor in factors:

            if factor.returns.empty:
                factor.calc_returns(next_return=True, returns_col=returns_col)
            assert not factor.returns.empty

            last_dt, _ = next(factor.table.iterrows())
            for dt, row in tqdm(factor.table.iterrows(), desc='Testing by group for factor ' + factor.alias):
                sifted_products = factor.returns.columns
                # sifted_products = self.sift_product_by_volumes(
                #     ratio=sift_volume_ratio, 
                #     time_range=(last_dt if dt != last_dt else None, dt)
                # )
                sorted_products = sorted(row.dropna().index, key=lambda x: (row[x], x.name), reverse=True)
                sorted_products = [product for product in sorted_products if product in sifted_products]
                n = len(sorted_products)
                idx = list(sorted_products)
                
                # Split contracts into n_groups groups
                if n == 0:
                    continue
                else:
                    n_split = n_groups
                    last_dt_has_product_now_at_market = set(range(n_groups))
                    for i in range(n_groups):
                        if not products[i]:
                            products[i][dt] = []
                        else:
                            # products[i][dt] = []
                            products[i][dt] = [product for product in products[i][last_dt]
                                if np.isnan(factor.returns[product].loc[dt])]
                            if products[i][dt] and len(products[i][dt]) == len(products[i][last_dt]):
                                last_dt_has_product_now_at_market.remove(i)
                            n_split = len(last_dt_has_product_now_at_market)
                    bucket_idx = np.floor(np.linspace(0, n_split, len(idx), endpoint=False)).astype(int)
                    split = [list(np.asarray(idx)[bucket_idx == i]) for i in range(n_split)]
                    last_dt_has_product_now_at_market = sorted(list(last_dt_has_product_now_at_market))
                    for i, group in enumerate(split):
                        products[last_dt_has_product_now_at_market[i]][dt].extend(group)

                for i in range(n_groups):
                    series = factor.returns[products[i][dt]].loc[dt].fillna(0)
                    returns[i][dt] = 0 if series.empty else np.mean(series.values)

                last_dt, _ = dt, row

            report_groups = {}
            for idx in range(n_groups):

                dates = list(returns[idx].keys()) if returns[idx] else []
                test_dates = [date for date in dates if self.start_date <= _signal_time(date)] if self.start_date else dates
                test_dates = [date for date in test_dates if _signal_time(date) <= self.end_date] if self.end_date else dates
                dates = [date for date in dates if start_date <= _signal_time(date)] if start_date else dates
                dates = [date for date in dates if _signal_time(date) <= end_date] if end_date else dates
                
                returns_list = [returns[idx][date] for date in dates]
                returns_series = pd.Series(returns_list).dropna()
                cumulative_returns = (1 + returns_series).cumprod()

                test_returns = [returns[idx][date] for date in test_dates]
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
                'Volatility': pd.Series(returns_list).std() * np.sqrt(252) * 100,
                'Sharpe Ratio': (pd.Series(returns_list).mean() * 252) / (pd.Series(returns_list).std() * np.sqrt(252)) if pd.Series(returns_list).std() != 0 else 0,
                'Max Drawdown': ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100 if len(cumulative_returns) > 0 else 0,
                'Calmar Ratio': ((cumulative_returns.iloc[-1] ** (252 / len(cumulative_returns)) - 1) * 100) / (((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() * 100) if ((cumulative_returns.cummax() - cumulative_returns) / cumulative_returns.cummax()).max() != 0 else 0,
                'Win Rate': (pd.Series(returns_list) > 0).sum() / len(pd.Series(returns_list)) * 100 if len(pd.Series(returns_list)) > 0 else 0,
                'Mean Return': pd.Series(returns_list).mean() * 100,
                'Skewness': pd.Series(returns_list).skew(),
                'Kurtosis': pd.Series(returns_list).kurtosis(),

                }

                report_groups[idx] = pd.Series(metrics)
            
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
                for idx in range(n_groups):
                    if plot_n_group_list is not None and idx not in plot_n_group_list:
                        continue
                    dates = list(returns[idx].keys()) if returns[idx] else []
                    dates = [date for date in dates if start_date <= _signal_time(date)] if start_date else dates
                    dates = [date for date in dates if _signal_time(date) <= end_date] if end_date else dates
                    returns_list = [returns[idx][date] for date in dates]
                    cumulative_returns = []
                    prev_value = 10000
                    for ret in returns_list:
                        if not np.isnan(ret):
                            prev_value = prev_value * (1 + ret)
                        cumulative_returns.append(prev_value)
                    plt.plot([str(date[-1].date()) if isinstance(date, tuple) else str(date.date()) for date in dates], cumulative_returns, label=names[idx])
                plt.xlabel('日期')
                plt.ylabel('平均收益')
                if plot_remark_str:
                    plt.title(f'平均收益: {factor.alias} - {plot_remark_str}')
                else:
                    plt.title(f'平均收益: {factor.alias}')
                plt.rcParams['font.sans-serif'] = ['Kaiti SC']
                plt.legend()
                # Only show every nth tick to reduce crowding
                n_ticks = 10
                assert len(dates) > 0, "No dates available for plotting."
                tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
                # plt.xticks(ticks=[str(dates[i][-1].date()) if isinstance(dates[i], tuple) else str(dates[i].date()) for i in tick_indices], rotation=45)
                ticks = [str(dates[i][-1].date()) if isinstance(dates[i], tuple) else str(dates[i].date()) for i in tick_indices]
                plt.xticks(ticks=ticks, rotation=45)
                plt.tight_layout()
                if save_plot:
                    factor_stem = factor.alias.split('|')[0]
                    figs_path = os.path.join(factor_info_path, factor_stem, 'figs')
                    if not os.path.exists(figs_path):
                        os.makedirs(figs_path)
                    plt.savefig(os.path.join(figs_path, f'{factor.alias}_{start_date}_{end_date}.png'))
                if plot_show:
                    plt.show()

        return products, returns, report_df
    
def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    return FactorTester(products=get_all_products(), time_range=time_range)