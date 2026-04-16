# =============================================================================
# tools/factors/FactorTester.py
# 因子测试器模块
#
# FactorTester 负责驱动因子的量化分析流程，包括：
#   - 品种管理（全量 / 按成交量筛选 / 按空数据过滤）
#   - calc_factor  : 批量计算各 Factor 的信号表
#   - calc_ic      : 计算 Spearman 秩相关 IC 序列及统计量
#   - ic_stats     : 汇总 IC 的均值/std/IR/t-stat/max/min
#   - test_by_group: 按因子值分 N 组，计算各组收益并绘制净值曲线
#
# 辅助函数：
#   get_factor_tester : 一键创建包含全部品种的 FactorTester 实例
# =============================================================================
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
    """从索引项中提取最末一级时间戳（兼容 tuple 多级索引和单值索引）。"""
    return obj if not isinstance(obj, tuple) else obj[-1]

class FactorTester(SerialObject):
    """
    因子测试器。

    属性：
        products  (set)         : 当前参与测试的品种集合（可经筛选后缩小）
        all_products (set)      : 初始全量品种集合
        factors   (list)        : 已计算的 Factor 列表
        start_date (Timestamp)  : 测试起始日期
        end_date   (Timestamp)  : 测试截止日期
        logger    (Logger)      : 日志记录器（文件 + 可选控制台）
    """
    _instances = WeakValueDictionary()

    def __new__(cls, alias: Optional[str] = None, *args, **kwargs):
        alias=alias if alias else cls.__name__
        return super().__new__(cls, type_alias='FT', alias=alias)

    def __init__(self, products: Sequence[Product],
                 alias: Optional[str] = None,
                 time_range: Optional[Tuple] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        """
        初始化 FactorTester。

        参数：
            products       : 参与测试的品种列表
            alias          : 实例别名，默认类名
            time_range     : (start, end) 测试时间区间（Timestamp 或可解析字符串）
            logger_file    : 是否写日志到文件
            logger_dir_path: 日志目录
            logger_console : 是否同时输出到控制台
        """
        if not hasattr(self, '_initialized'):
            super().__init__(type_alias='FT', alias=alias)

            # 初始化日志记录器
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

            self.products = set(products)       # 当前测试品种集（可经筛选减少）
            self.all_products = set(products)   # 原始全量品种集
            self.sift_product_by_empty_data_bool = False  # 记录是否已执行空数据过滤
            self.factors = []
            if time_range is not None:
                self.update_time_range(time_range)
            else:
                self.start_date = None
                self.end_date = None
            self.logger.info(f"FactorTester initialized with {len(self.products)} products")
    
    def update_time_range(self, time_range: Tuple):
        """更新测试时间区间并记录日志。"""
        self.start_date = pd.to_datetime(time_range[0])
        self.end_date = pd.to_datetime(time_range[1])
        self.logger.info(f"Time range updated to {self.start_date} - {self.end_date}")

    def sift_product(self, sift_func: Callable[[Product], bool]):
        """按自定义函数筛选品种，不满足条件的品种从 self.products 中移除。"""
        new_products = set()
        for product in self.products:
            if sift_func(product):
                new_products.add(product)
        self.products = new_products

    def sift_product_by_empty_data(self):
        """移除所有无有效成交量数据的品种，同时为剩余品种注册计算起始点。"""
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
        """
        按成交量排名保留头部品种。

        参数：
            ratio      : 保留比例（0~1），None 则返回全量
            time_col   : 成交量统计的时间列（传给 get_slices）
            time_range : 成交量统计的时间范围

        返回：
            按成交量从高到低排序后取前 ratio 比例的品种集合
        """
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

    def calc_factor(self, factors: 'Factor|List[Factor]'):
        """
        批量计算因子值并自动过滤空数据品种。

        参数：
            factors : 单个 Factor 或 Factor 列表
        """
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors
        self.sift_product_by_empty_data()
        for factor in tqdm(self.factors, desc=f'Calculate factors for {len(self.products)} products'):
            factor.calc(self.products)

    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        """对 DataFrame 按行（各信号时间点）进行百分位秩排名，只保留属于 self.products 的列。"""
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)

    def calc_ic(self, returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                return_freq: Optional[Any] = None, factors: 'Optional[Factor|List[Factor]]' = None,
                time_range: Optional[Tuple] = None) -> 'tuple[pd.DataFrame, pd.DataFrame]':
        """
        计算 Spearman IC 序列及统计量。

        流程：
          1. 对因子值和收益率分别做百分位秩排名
          2. 逐时间点计算二者的 Spearman 相关系数
          3. 汇总为 ic_series 和 ic_stats 写入各 Factor

        参数：
            returns_col : 收益类型枚举（默认次日开盘收益）
            return_freq : 收益频率（None 则沿用 Factor 现有收益）
            factors     : 指定 Factor，None 则使用 self.factors
            time_range  : 覆盖 self.start_date/end_date 的测试区间

        返回：
            (ic_series_df, ic_stats_df) 两个 DataFrame
        """
        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date

        ic_series = {}
        ic_stats = {}

        for factor in tqdm(factors, desc='Calculating IC'):
            factor_rank = self.calc_rank(factor.table)
            # 若收益为空或频率不匹配，重新计算收益
            if factor.returns.empty or (not factor.returns.empty and DataFreq(factor.get_current_return_freq()) != DataFreq(return_freq)):
                return_df = factor.calc_returns(next_return=True, returns_col=returns_col, return_freq=return_freq)
            else:
                return_df = factor.returns
            assert not return_df.empty
            return_rank = self.calc_rank(return_df)
            # 取因子与收益的交集时间点，并按 start/end_date 截断
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
                        with np.errstate(invalid='ignore'):
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
        """
        计算 IC 序列的汇总统计量。

        返回 pd.Series，包含：mean、std、IR（=mean/std）、t_stat、max、min
        """
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

    def test_by_group(self, factors: 'Optional[Factor|List[Factor]]' = None,
                      returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None, **kwargs) -> Tuple[Any, Any, pd.DataFrame]:
        """
        按因子值分 N 组，逐期持有并统计各组收益指标。

        分组逻辑：
          - 每个信号时间点按因子值从高到低排序
          - 均匀分入 n_groups 组（前一组为最高值组）
          - 若某品种上期持有后收益数据为 NaN（未退市但无成交），则继续持有，不换入新品种
          - 计算各组等权平均收益，汇总 Total/Annual Return、Sharpe、Max Drawdown 等指标

        参数：
            factors          : 指定 Factor（默认 self.factors）
            returns_col      : 收益类型
            n_groups         : 分组数，默认 5
            n_groups_name    : 组号→自定义名称映射
            time_range       : IC 测试区间（绘图用）
            plot_remark_str  : 图标题附加说明字符串
            plot_flag        : 是否绘制净值曲线
            save_plot        : 是否保存图片
            plot_show        : 是否调用 plt.show()
            plot_n_group_list: 只绘制指定组号（None 表示全部）

        返回：
            (products_dict, returns_dict, report_df)
              products_dict : {组号: {时间点: [品种列表]}}
              returns_dict  : {组号: {时间点: 平均收益}}
              report_df     : 各组绩效汇总 DataFrame
        """

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
    """
    创建包含全部品种的 FactorTester 实例（便捷工厂函数）。

    参数：
        time_range : (start, end) 测试时间区间，None 则不设置

    返回：
        FactorTester 实例
    """
    return FactorTester(products=get_all_products(), time_range=time_range)