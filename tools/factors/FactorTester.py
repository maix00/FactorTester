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

    def _test_by_group_single_factor(self, factor: 'Factor',
                                     returns_col: FactorNextPeriodReturns,
                                     n_groups: int, n_groups_name: Dict[int, str],
                                     time_range: Optional[Tuple],
                                     plot_remark_str: Optional[str],
                                     plot_flag: bool, save_plot: bool, plot_show: bool,
                                     plot_n_group_list: Optional[List[int]],
                                     sift_volume_ratio: Optional[float] = None) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
        """单因子分组测试核心逻辑（已 numpy 加速），供多线程调用。"""
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date   = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date

        if factor.returns.empty:
            factor.calc_returns(next_return=True, returns_col=returns_col)
        assert not factor.returns.empty

        # ---------- numpy 预计算 ----------
        # 先按时间范围截取数据（兼容 tuple 多级索引）
        table_src   = factor.table
        returns_src = factor.returns
        if start_date is not None:
            mask = [_signal_time(k) >= start_date for k in table_src.index]
            table_src   = table_src[mask]
            mask = [_signal_time(k) >= start_date for k in returns_src.index]
            returns_src = returns_src[mask]
        if end_date is not None:
            mask = [_signal_time(k) <= end_date for k in table_src.index]
            table_src   = table_src[mask]
            mask = [_signal_time(k) <= end_date for k in returns_src.index]
            returns_src = returns_src[mask]

        # 把 factor.table / factor.returns 转成 numpy 矩阵，列为品种
        # 统一列顺序
        all_cols = list(table_src.columns)
        ret_cols  = list(factor.returns.columns)
        # 只取交集（有 returns 的品种）
        valid_cols = [c for c in all_cols if c in set(ret_cols)]

        table_np  = factor.table[valid_cols].to_numpy(dtype=float)   # shape (T, P)
        returns_np = factor.returns[valid_cols].to_numpy(dtype=float) # shape (T, P)
        index_list = list(factor.table.index)                         # len T
        T = len(index_list)

        n_names = {i: n_groups_name.get(i, 'group_' + str(i)) for i in range(n_groups)}

        P = len(valid_cols)
        membership_np = np.zeros((T, n_groups, P), dtype=bool)

        # current_members: (n_groups, P) bool，在循环内原地更新
        current_members = np.zeros((n_groups, P), dtype=bool)

        for t in tqdm(range(T), desc='Testing by group for factor ' + factor.alias):
            row     = table_np[t]       # (P,)
            ret_row = returns_np[t]     # (P,)

            # 一次性预计算 NaN 掩码，后续复用
            isnan_ret = np.isnan(ret_row)   # (P,)
            isnan_fac = np.isnan(row)       # (P,)

            # carryover：上期持有 & 本期 returns=NaN 的品种继续保留
            if t == 0:
                carry_members = np.zeros((n_groups, P), dtype=bool)
            else:
                carry_members = current_members & isnan_ret[np.newaxis, :]  # (n_groups, P)

            # active_groups：上期有持仓且本期 carryover < 上期持仓数的组，或全新组
            prev_count  = current_members.sum(axis=1)   # (n_groups,)
            carry_count = carry_members.sum(axis=1)     # (n_groups,)
            active_mask = (carry_count < prev_count) | (prev_count == 0)
            active_groups = np.where(active_mask)[0]

            # 更新 current_members 为 carryover 状态
            current_members = carry_members.copy()

            # 可分配品种 = 因子值非 NaN & 未被 carryover 持有
            held_mask      = carry_members.any(axis=0)          # (P,)
            available_mask = (~isnan_fac) & (~held_mask)        # (P,)
            available_idx  = np.where(available_mask)[0]

            if len(available_idx) > 0 and len(active_groups) > 0:
                # 按因子值降序排列可分配品种
                new_idx    = available_idx[np.argsort(-row[available_idx])]
                bucket_idx = np.floor(
                    np.linspace(0, len(active_groups), len(new_idx), endpoint=False)
                ).astype(int)
                for slot, g in enumerate(active_groups):
                    assigned = new_idx[bucket_idx == slot]
                    current_members[g, assigned] = True

            membership_np[t] = current_members

        # ---------- 向量化计算各组各期收益 ----------
        # products_dict 移出循环，从 membership_np 重建
        products_dict = {
            g: {index_list[t]: [valid_cols[i] for i in np.where(membership_np[t, g])[0]]
                for t in range(T)}
            for g in range(n_groups)
        }

        # ---------- 向量化计算各组各期收益 ----------
        # returns_np_filled: NaN→0，shape (T, P)
        returns_filled = np.where(np.isnan(returns_np), 0.0, returns_np)
        # group_returns_np: (T, n_groups) — 等权平均
        member_counts = membership_np.sum(axis=2).astype(float)          # (T, n_groups)
        member_counts[member_counts == 0] = 1.0                           # 避免除零
        group_returns_np = (membership_np * returns_filled[:, np.newaxis, :]).sum(axis=2) / member_counts  # (T, n_groups)

        # 兼容原接口：构建 returns_dict[g][dt]
        returns_dict = {g: {index_list[t]: float(group_returns_np[t, g]) for t in range(T)} for g in range(n_groups)}

        # 预计算累积收益 (T, n_groups)，供调用方直接使用
        cum_rets_filled = np.where(np.isnan(group_returns_np), 0.0, group_returns_np)
        cumulative_returns_np = np.cumprod(1 + cum_rets_filled, axis=0)  # (T, n_groups)

        # ---------- 汇总指标（向量化） ----------
        # 构建时间戳数组，用于日期过滤
        signal_times = np.array([_signal_time(d) for d in index_list])
        mask_report = np.ones(T, dtype=bool)
        if start_date is not None:
            mask_report &= (signal_times >= start_date)
        if end_date is not None:
            mask_report &= (signal_times <= end_date)

        report_groups = {}
        for idx in range(n_groups):
            r = group_returns_np[mask_report, idx]

            def _metrics(arr: np.ndarray) -> dict:
                s = pd.Series(arr).dropna()
                cum = (1 + s).cumprod()
                n = len(s)
                total_ret  = (cum.iloc[-1] - 1) * 100 if n > 0 else 0
                annual_ret = (cum.iloc[-1] ** (252 / n) - 1) * 100 if n > 1 else 0
                vol        = s.std() * np.sqrt(252) * 100
                sharpe     = (s.mean() * 252) / (s.std() * np.sqrt(252)) if s.std() != 0 else 0
                dd         = ((cum.cummax() - cum) / cum.cummax()).max() * 100 if n > 0 else 0
                calmar     = annual_ret / dd if dd != 0 else 0
                win_rate   = (s > 0).sum() / n * 100 if n > 0 else 0
                return dict(total_ret=total_ret, annual_ret=annual_ret, vol=vol,
                            sharpe=sharpe, dd=dd, calmar=calmar, win_rate=win_rate,
                            mean_ret=s.mean() * 100, skew=s.skew(), kurt=s.kurtosis())

            m = _metrics(r)
            report_groups[idx] = pd.Series({
                'Total Return':  m['total_ret'],
                'Annual Return': m['annual_ret'],
                'Volatility':    m['vol'],
                'Sharpe Ratio':  m['sharpe'],
                'Max Drawdown':  m['dd'],
                'Calmar Ratio':  m['calmar'],
                'Win Rate':      m['win_rate'],
                'Mean Return':   m['mean_ret'],
                'Skewness':      m['skew'],
                'Kurtosis':      m['kurt'],
            })

        report_df = pd.DataFrame(report_groups).T.sort_index()
        if not plot_flag or (plot_flag and plot_show):
            with pd.option_context('display.max_rows', None, 'display.max_columns', None):
                print("Group Performance Summary:\n", report_df)

        if plot_flag:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(12, 6))
            _start_date = start_date if start_date is not None else self.start_date
            _end_date   = end_date   if end_date   is not None else self.end_date
            plot_mask = np.ones(T, dtype=bool)
            if _start_date is not None:
                plot_mask &= (signal_times >= _start_date)
            if _end_date is not None:
                plot_mask &= (signal_times <= _end_date)
            plot_index = [index_list[t] for t in range(T) if plot_mask[t]]
            dates = plot_index
            for idx in range(n_groups):
                if plot_n_group_list is not None and idx not in plot_n_group_list:
                    continue
                rets = group_returns_np[plot_mask, idx]
                cumulative_returns = np.cumprod(1 + np.where(np.isnan(rets), 0.0, rets)) * 10000
                plt.plot(
                    [str(d[-1].date()) if isinstance(d, tuple) else str(d.date()) for d in plot_index],
                    cumulative_returns, label=n_names[idx]
                )
            plt.xlabel('日期')
            plt.ylabel('平均收益')
            plt.title(f'平均收益: {factor.alias}' + (f' - {plot_remark_str}' if plot_remark_str else ''))
            plt.rcParams['font.sans-serif'] = ['Kaiti SC']
            plt.legend()
            n_ticks = 10
            if dates:
                tick_indices = np.linspace(0, len(dates) - 1, min(n_ticks, len(dates)), dtype=int)
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

        return products_dict, returns_dict, report_df, cumulative_returns_np, index_list

    def test_by_group(self, factors: 'Optional[Factor|List[Factor]]' = None,
                      returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None, **kwargs) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
        """
        按因子值分 N 组，逐期持有并统计各组收益指标。多因子时并行执行（ThreadPoolExecutor）。

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
        from concurrent.futures import ThreadPoolExecutor, as_completed

        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)

        if plot_flag and plot_n_group_list is not None:
            plot_n_group_list = [n_groups + n_group if n_group < 0 else n_group for n_group in plot_n_group_list] if plot_n_group_list else None

        products_out: Any = {}
        returns_out: Any = {}
        report_df: pd.DataFrame = pd.DataFrame()
        def _run(f: Factor) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
            return self._test_by_group_single_factor(
                f, returns_col=returns_col, n_groups=n_groups, n_groups_name=n_groups_name,
                time_range=time_range, plot_remark_str=plot_remark_str,
                plot_flag=plot_flag, save_plot=save_plot, plot_show=plot_show,
                plot_n_group_list=plot_n_group_list,
                sift_volume_ratio=sift_volume_ratio,
            )

        cum_np_out: Optional[np.ndarray] = None
        idx_list_out: Optional[list] = None

        if len(factors) == 1:
            products_out, returns_out, report_df, cum_np_out, idx_list_out = _run(factors[0])
        else:
            max_workers = min(len(factors), 8)
            results: Dict[int, Any] = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {executor.submit(_run, f): i for i, f in enumerate(factors)}
                for future in as_completed(future_to_idx):
                    results[future_to_idx[future]] = future.result()
            last_idx = max(results.keys())
            products_out, returns_out, report_df, cum_np_out, idx_list_out = results[last_idx]

        assert cum_np_out is not None and idx_list_out is not None
        return products_out, returns_out, report_df, cum_np_out, idx_list_out
    
def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    """
    创建包含全部品种的 FactorTester 实例（便捷工厂函数）。

    参数：
        time_range : (start, end) 测试时间区间，None 则不设置

    返回：
        FactorTester 实例
    """
    return FactorTester(products=get_all_products(), time_range=time_range)