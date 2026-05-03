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
import threading
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime
from weakref import WeakValueDictionary
from typing import Optional, Sequence, Tuple, Callable, Any, Set, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.factors.Factor import Factor
from tools.products.Product import Product
from tools import UniqueObject, DataColumn, DataFreq
from tools.base.User import User
from tools.factors.Parameters import StartCalcPointParam, FactorNextPeriodReturns

from Settings import get_all_products, logger_dir_path_default, factor_info_path

def _signal_time(obj: Any) -> Any:
    """从索引项中提取最末一级时间戳（兼容 tuple 多级索引和单值索引）。"""
    return obj[-1] if isinstance(obj, tuple) else obj


def _align_ts(lhs: Any, rhs: Any) -> Any:
    """将 lhs 时区对齐到 rhs；若任一非 Timestamp 则原样返回 lhs。"""
    if isinstance(lhs, pd.Timestamp) and isinstance(rhs, pd.Timestamp):
        if lhs.tzinfo is None and rhs.tzinfo is not None:
            return lhs.tz_localize(rhs.tz)
        if lhs.tzinfo is not None and rhs.tzinfo is None:
            return lhs.tz_localize(None)
        if lhs.tzinfo is not None and rhs.tzinfo is not None:
            return lhs.tz_convert(rhs.tz)
    return lhs


def _extract_signal_index(idx: pd.Index) -> pd.DatetimeIndex:
    """从信号索引中提取时间戳层，返回 DatetimeIndex。

    - DatetimeIndex：直接转换后返回
    - MultiIndex：优先取名称以 _SIGNAL@ 开头的层级，否则取最后一层
    """
    if isinstance(idx, pd.MultiIndex):
        signal_name = next((n for n in idx.names if n and str(n).startswith('_SIGNAL')), None)
        level = idx.names.index(signal_name) if signal_name is not None else -1
        return pd.DatetimeIndex(idx.get_level_values(level), name=idx.names[level])
    return pd.DatetimeIndex(idx)

class FactorTester(UniqueObject):
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

    def __new__(cls, alias: Optional[str] = None, *args, user=None, **kwargs):
        core_alias = alias if alias else cls.__name__
        # 将 user name 嵌入 alias，避免不同用户的同名 tester 冲突
        if user is not None:
            user_name = getattr(user, 'alias', str(user))
            core_alias = f"{user_name}:{core_alias}"
        return super().__new__(cls, alias=core_alias, **kwargs)

    def __init__(self, products: Sequence[Product],
                 alias: Optional[str] = None,
                 time_range: Optional[Tuple] = None,
                 user: Optional['User'] = None,
                 logger_file: bool = True, logger_dir_path: str = logger_dir_path_default,
                 logger_console: bool = False):
        """
        初始化 FactorTester。

        参数：
            products       : 参与测试的品种列表
            alias          : 实例别名，默认类名
            time_range     : (start, end) 测试时间区间（Timestamp 或可解析字符串）
            user           : 创建此 tester 的 User 实例
            logger_file    : 是否写日志到文件
            logger_dir_path: 日志目录
            logger_console : 是否同时输出到控制台
        """
        if not hasattr(self, '_initialized'):
            super().__init__(alias=alias)
            self.user = user  # 创建者 User 实例（None 表示无归属）

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
                    logger_file_path = os.path.join(logger_dir_path, f"factor_tester_{self.name}_{datetime.now().strftime('%Y%m%d')}.log")
                    file_handler = logging.FileHandler(logger_file_path, encoding='utf-8')
                    file_handler.setFormatter(formatter)
                    self.logger.addHandler(file_handler)

            self.products = set(products)       # 当前测试品种集（可经筛选减少）
            self.all_products = set(products)   # 原始全量品种集
            self.sift_product_by_empty_data_bool = False  # 记录是否已执行空数据过滤
            self.factors = []
            # 信号同步索引缓存（per-run，避免跨并发请求共享）
            self.sync_signal_index: Optional[pd.Index] = None
            self.sync_signal_index_replaced: Optional[pd.Index] = None
            self._sync_lock = threading.Lock()
            # Factor 计算结果（keyed by Factor 实例） — 所有 per-run 状态集中在此
            self.factor_tables: Dict['Factor', pd.DataFrame] = {}
            self.factor_returns: Dict['Factor', pd.DataFrame] = {}
            self.factor_return_freqs: Dict['Factor', Any] = {}
            self.factor_ic_series: Dict['Factor', pd.Series] = {}
            self.factor_ic_stats: Dict['Factor', pd.Series] = {}
            self.factor_reports: Dict['Factor', pd.DataFrame] = {}
            if time_range is not None:
                self.update_time_range(time_range)
            else:
                self.start_date = None
                self.end_date = None
                self.start_calc_point = None  # 计算起始点（带时区 Timestamp，与 start_date 合并为同一概念）
            self.logger.info(f"FactorTester initialized with {len(self.products)} products")

    def delete(self):
        """
        清理 FactorTester 及其持有的所有 per-factor 数据。

        调用后：
          - 所有关联 Factor 的计算缓存被清空
          - Factor 和其非$开头 Parameter 副本被从全局缓存中移除（delete）
          - self.products / self.all_products 被置空
          - 将 self 从所属 User 的 tester 列表中移除（如有）
          - 关闭 logger handler 释放文件句柄
        """
        from tools.parameters.Parameter import Parameter
        # 清理所有关联 Factor 及其非$开头参数
        for f in list(self.factors):
            try:
                # 清理非$开头的 Parameter 副本（name = {alias}:{factor.name}）
                for param in list(f.params):
                    if not param.alias.startswith('$'):
                        try:
                            param.delete()
                        except Exception:
                            pass
                f.clear()
                f.delete()
            except Exception:
                pass
        # 清空 per-factor 缓存 dict
        self.factor_tables.clear()
        self.factor_returns.clear()
        self.factor_return_freqs.clear()
        self.factor_ic_series.clear()
        self.factor_ic_stats.clear()
        self.factor_reports.clear()
        self.factors.clear()
        self.products = set()
        self.all_products = set()
        # 从 user 的 tester 列表移除
        if self.user is not None:
            try:
                self.user.remove_tester(self)
            except Exception:
                pass
        # 关闭 logger handler
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)
        try:
            self.logger.info(f"FactorTester {self.alias} deleted")
        except Exception:
            pass

    def update_time_range(self, time_range: Tuple):
        """更新测试时间区间并记录日志。start_calc_point 与 start_date 为同一概念。"""
        self.start_date = pd.to_datetime(time_range[0])
        self.end_date = pd.to_datetime(time_range[1])
        self.start_calc_point = self.start_date  # 带时区，与 start_date 保持同步
        self.logger.info(f"Time range updated to {self.start_date} - {self.end_date}")

    def sift_product(self, sift_func: Callable[[Product], bool]):
        """按自定义函数筛选品种，不满足条件的品种从 self.products 中移除。"""
        new_products = set()
        for product in self.products:
            if sift_func(product):
                new_products.add(product)
        self.products = new_products

    def sift_product_by_empty_data(self):
        """移除所有无有效成交量数据的品种（使用全量数据判断，不依赖 start_calc_point）。"""
        new_products = set()
        for product in self.products:
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

    def calc_factor(self, factors: 'Factor|List[Factor]', parallel: bool = True, max_workers: int = 4):
        """
        批量计算因子值。品种筛选由 func 内部处理。

        参数：
            factors    : 单个 Factor 或 Factor 列表
            parallel   : 是否并行计算（默认 True，单因子时自动退化为串行）
            max_workers: 并行线程数（默认 4）
        """
        if isinstance(factors, Factor):
            factors = [factors]
        self.factors = factors

        if parallel and len(factors) > 1:
            from tools.factors.FactorFamily import _active_tester
            desc = f'Calculate {len(factors)} factors for {len(self.products)} products'
            # 捕获当前 context 中 _active_tester 的值，在每个 worker 线程里手动设置
            token = _active_tester.get()
            def _calc_one(factor: Factor) -> None:
                _active_tester.set(token)
                factor.calc(self.products)
            with ThreadPoolExecutor(max_workers=min(max_workers, len(factors))) as pool:
                futures = {pool.submit(_calc_one, f): f for f in factors}
                for future in tqdm(as_completed(futures), total=len(futures), desc=desc):
                    exc = future.exception()
                    if exc is not None:
                        for fut in futures:
                            fut.cancel()
                        raise RuntimeError(
                            f"calc_factor: {futures[future].alias} 计算失败") from exc
        else:
            for factor in tqdm(factors, desc=f'Calculate factors for {len(self.products)} products'):
                factor.calc(self.products)

    def calc_rank(self, df: pd.DataFrame) -> pd.DataFrame:
        """对 DataFrame 按行（各信号时间点）进行百分位秩排名，只保留属于 self.products 的列。"""
        df = df.loc[:, df.columns.isin(self.products)]
        return df.rank(axis=1, method='average', na_option='keep', pct=True)

    def _calc_ic_single(self, factor: 'Factor',
                        returns_col: FactorNextPeriodReturns,
                        return_freq: Optional[Any],
                        start_date: Optional[pd.Timestamp],
                        end_date: Optional[pd.Timestamp],
                        returns_df: Optional[pd.DataFrame] = None,
                        return_rank: Optional[pd.DataFrame] = None) -> 'tuple[Factor, pd.Series, pd.Series]':
        """单因子 IC 计算（线程安全，不修改共享状态）。

        returns_df  : 若提供，则直接用作收益率表，跳过 calc_returns() 调用。
        return_rank : 若提供，则直接用作收益率排名，跳过 calc_rank() 调用。
        """
        factor_rank = self.calc_rank(factor.table)
        if returns_df is not None:
            return_df = returns_df
            factor.returns = returns_df  # 同步写入，保证后续访问一致性
        else:
            effective_freq = DataFreq(return_freq) if return_freq is not None else factor.freq
            with self._sync_lock:
                cached_freq = self.factor_return_freqs.get(factor)
            if factor.returns.empty or cached_freq is None or cached_freq != effective_freq:
                factor.calc_returns(next_return=True, returns_col=returns_col, return_freq=effective_freq)
                with self._sync_lock:
                    self.factor_return_freqs[factor] = effective_freq
            return_df = factor.returns
        assert not return_df.empty
        if return_rank is not None:
            rank_df = return_rank
        else:
            rank_df = self.calc_rank(return_df)
        factor_rank.index = _extract_signal_index(factor_rank.index)
        rank_df.index = _extract_signal_index(rank_df.index)
        dt_index = factor_rank.index.intersection(rank_df.index)
        if start_date is not None and len(dt_index) > 0:
            dt_index = dt_index[dt_index >= _align_ts(pd.Timestamp(start_date), dt_index[0])]
        if end_date is not None and len(dt_index) > 0:
            dt_index = dt_index[dt_index <= _align_ts(pd.Timestamp(end_date), dt_index[0])]
        ic = []
        coverage = []
        for dt in dt_index:
            f = factor_rank.loc[dt]
            r = rank_df.loc[dt]
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
        # 若 factor.table 有 MultiIndex，将 ic_series 的索引还原为相同结构
        if isinstance(factor.table.index, pd.MultiIndex):
            tbl_signal_idx = _extract_signal_index(factor.table.index)
            mask = tbl_signal_idx.isin(dt_index)
            mapping = {sig: full for sig, full in zip(tbl_signal_idx[mask], factor.table.index[mask])}
            valid_ts = [ts for ts in dt_index if ts in mapping]
            full_idx = pd.MultiIndex.from_tuples([mapping[ts] for ts in valid_ts], names=factor.table.index.names)
            ic_vals = [v for ts, v in zip(dt_index, ic) if ts in mapping]
            ic_series = pd.Series(ic_vals, index=full_idx)
        else:
            ic_series = pd.Series(ic, index=dt_index)
        avg_coverage = np.mean(coverage)
        stats_df = self.ic_stats(ic_series)
        stats_df['avg_coverage'] = avg_coverage
        return factor, ic_series, stats_df

    def calc_ic(self, returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                return_freq: Optional[Any] = None, factors: 'Optional[Factor|List[Factor]]' = None,
                time_range: Optional[Tuple] = None,
                parallel: bool = True, max_workers: int = 4) -> 'tuple[pd.DataFrame, pd.DataFrame]':
        """
        计算 Spearman IC 序列及统计量。

        使用 CrossSectionIC FactorFamily：将因子表达式 FE 和收益率表达式 RE
        作为参数传入，统一预加载和求值后计算截面 Spearman 秩相关系数。

        参数：
            returns_col : 收益类型枚举（默认次日开盘收益）
            return_freq : 收益频率（None 则沿用 Factor 现有收益）
            factors     : 指定 Factor，None 则使用 self.factors
            time_range  : 覆盖 self.start_date/end_date 的测试区间
            parallel    : 是否并行计算
            max_workers : 并行线程数

        返回：
            (ic_series_df, ic_stats_df) 两个 DataFrame
        """
        factors = [factors] if isinstance(factors, Factor) else \
            (factors if factors is not None else self.factors)
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date

        from tools.factors.FactorFamily import CrossSectionIC, _active_tester
        from tools.factors.FactorExpr import DataColumn
        from tools.parameters import DataColumnParam, TypeParam
        from tools.parameters import WindowParam

        CrossSectionFamily = CrossSectionIC()

        # ── 构建去重参数组合 ──
        # 每个因子有唯一的 FE 表达式和频率，RE 可能共享
        # Key: (fe_expr_key, freq_key, lag, returns_col) — 去重后用同一个 CrossSectionIC Factor
        ic_param_map: Dict[tuple, List[Factor]] = {}  # param_key → factors sharing it
        param_key_info: Dict[tuple, tuple] = {}        # param_key → (fe_expr, freq, lag)

        for factor in factors:
            if return_freq is not None:
                effective_freq = DataFreq(return_freq)
            elif factor.freq is not None:
                effective_freq = factor.freq
            elif factor.source_data_freq is not None:
                effective_freq = factor.source_data_freq
            else:
                raise ValueError(f"Factor {factor.alias}: 无法确定频率")

            # Lag: OPEN 类型用 -1（收益率领先1期 → Lag=1），否则用 0
            lag = 1 if returns_col.value.name.startswith('OPEN') else 0
            fe_expr = factor.family._expr if factor.family is not None else None
            if fe_expr is None:
                raise ValueError(f"Factor {factor.alias}: 没有关联的表达式树")
            param_key = (id(fe_expr), effective_freq.name, lag, returns_col.value.name)
            if param_key not in ic_param_map:
                ic_param_map[param_key] = []
                param_key_info[param_key] = (fe_expr, effective_freq, lag)
            ic_param_map[param_key].append(factor)

        # ── 构建 RE 表达式（共享） ──
        # Returns: (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)
        # 对于 IC，S=shift where shift=-1 for OPEN else 0
        shift = -1 if returns_col.value.name.startswith('OPEN') else 0
        SC = DataColumnParam('SC', default_value=returns_col.value)
        RF = WindowParam('RF')
        S = TypeParam('S', default_value=shift)
        re_expr = (SC.delta(RF) / SC.shift(RF)).shift((S - 1) * RF)

        # ── 切换到数据源频率 ──
        sample_factor = factors[0]
        old_freq_map: Dict = {}
        if sample_factor.source_data_freq is not None and sample_factor.products:
            for p in sample_factor.products:
                try:
                    old_freq_map[p] = p.get_current_freq()
                    if sample_factor.source_data_freq in p.list_available_freqs():
                        p.set_current_freq(sample_factor.source_data_freq)
                except Exception:
                    pass

        try:
            ic_series_map = {}
            ic_stats_map = {}

            # ── 并行或串行计算每个去重参数组 ──
            param_items = list(ic_param_map.items())

            def _calc_one_group(param_key, factor_list):
                fe_expr, effective_freq, lag = param_key_info[param_key]
                # 创建 CrossSectionIC Factor
                ic_factor = CrossSectionFamily.get_factor(
                    FE=fe_expr,
                    RE=re_expr,
                    Lag=lag,
                    F=effective_freq.value,
                )
                ic_factor.calc(sample_factor.products)

                # 提取 IC 序列
                ic_raw = ic_factor.table
                if isinstance(ic_raw, pd.DataFrame):
                    ic_series = ic_raw.iloc[:, 0] if ic_raw.shape[1] > 0 else pd.Series(dtype=float)
                else:
                    ic_series = ic_raw

                # 时间范围截断
                if start_date is not None and len(ic_series) > 0:
                    ic_series = ic_series[ic_series.index.get_level_values(-1) >= start_date]
                if end_date is not None and len(ic_series) > 0:
                    ic_series = ic_series[ic_series.index.get_level_values(-1) <= end_date]

                # 提取 RE 中间因子 → 写入 factor.returns
                re_df = CrossSectionFamily.get_intermediate('RE')
                fe_df = CrossSectionFamily.get_intermediate('FE')

                for f in factor_list:
                    if re_df is not None:
                        f.returns = re_df.copy()
                    if fe_df is not None and not hasattr(f, '_ic_fe_intermediate'):
                        object.__setattr__(f, '_ic_fe_intermediate', fe_df.copy())

                # 计算统计量
                stats = self.ic_stats(ic_series)
                return factor_list, ic_series, stats

            if parallel and len(param_items) > 1:
                token = _active_tester.get()
                def _worker(item):
                    _active_tester.set(token)
                    pk, fl = item
                    return _calc_one_group(pk, fl)
                with ThreadPoolExecutor(max_workers=min(max_workers, len(param_items))) as pool:
                    futures = {pool.submit(_worker, item): item for item in param_items}
                    for future in tqdm(as_completed(futures), total=len(futures), desc='Calculating IC'):
                        exc = future.exception()
                        if exc is not None:
                            for fut in futures:
                                fut.cancel()
                            raise RuntimeError("calc_ic: IC 计算失败") from exc
                        factor_list, ic_series, stats = future.result()
                        for f in factor_list:
                            f.ic_series = ic_series
                            f.ic_stats = stats
                            ic_series_map[f] = ic_series
                            ic_stats_map[f] = stats
                            with self._sync_lock:
                                self.factor_ic_series[f] = ic_series
                                self.factor_ic_stats[f] = stats
            else:
                for param_key, factor_list in tqdm(param_items, desc='Calculating IC'):
                    factor_list, ic_series, stats = _calc_one_group(param_key, factor_list)
                    for f in factor_list:
                        f.ic_series = ic_series
                        f.ic_stats = stats
                        ic_series_map[f] = ic_series
                        ic_stats_map[f] = stats
                        with self._sync_lock:
                            self.factor_ic_series[f] = ic_series
                            self.factor_ic_stats[f] = stats

        finally:
            if old_freq_map:
                for p, f in old_freq_map.items():
                    try:
                        p.set_current_freq(f)
                    except Exception:
                        pass

        return pd.DataFrame(ic_series_map), pd.DataFrame(ic_stats_map)

    def ic_stats(self, ic_series: pd.Series) -> pd.Series:
        """
        计算 IC 序列的汇总统计量。

        返回 pd.Series，包含：mean、std、IR（=mean/std）、t_stat、max、min、
        ac1（lag-1 自相关）、half_life（自相关衰减到 0.5 的滞后期数）
        """
        mean = ic_series.mean()
        std = ic_series.std()
        ir = mean / std if std != 0 else np.nan
        t_stat = mean / (std / np.sqrt(len(ic_series.dropna()))) if std != 0 and len(ic_series.dropna()) > 1 else np.nan
        max_ic = ic_series.max()
        min_ic = ic_series.min()

        # 自相关 & 半衰期
        s = ic_series.dropna()
        ac1 = None
        half_life = None
        if len(s) > 2:
            from statsmodels.tsa.stattools import acf
            try:
                # 计算前 min(20, len(s)//2) 个滞后期自相关
                nlags = min(20, max(1, len(s) // 2 - 1))
                acf_vals = acf(s.values, nlags=nlags, fft=False)
                ac1 = float(acf_vals[1]) if len(acf_vals) > 1 else None
                # 半衰期：找到自相关首次 < 0.5 的 lag（从 lag=1 开始）
                for lag in range(1, len(acf_vals)):
                    if acf_vals[lag] < 0.5:
                        # 线性插值
                        prev = acf_vals[lag-1]
                        curr = acf_vals[lag]
                        frac = (0.5 - prev) / (curr - prev) if curr != prev else 0.0
                        half_life = float(lag - 1 + frac)
                        break
                # 如果在所有计算 lag 内未衰减到 0.5，返回正无穷大
                if half_life is None:
                    half_life = float('inf')
            except Exception:
                pass

        stats_df = pd.Series({
            'mean': mean, 'std': std, 'IR': ir, 't_stat': t_stat, 'max': max_ic, 'min': min_ic,
            'ac1': ac1, 'half_life': half_life,
        })
        return stats_df

    def _test_by_group_single_factor(self, factor: 'Factor',
                                     returns_col: FactorNextPeriodReturns,
                                     n_groups: int, n_groups_name: Dict[int, str],
                                     time_range: Optional[Tuple],
                                     plot_remark_str: Optional[str],
                                     plot_flag: bool, save_plot: bool, plot_show: bool,
                                     plot_n_group_list: Optional[List[int]],
                                     sift_volume_ratio: Optional[float] = None,
                                     fee: float = 0.0,
                                     fee_map: dict = {}) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
        """单因子分组测试核心逻辑（已 numpy 加速），供多线程调用。"""
        start_date = pd.to_datetime(time_range[0]) if time_range is not None else self.start_date
        end_date   = pd.to_datetime(time_range[1]) if time_range is not None else self.end_date

        if factor.returns.empty:
            factor.calc_returns(next_return=True, returns_col=returns_col)
        assert not factor.returns.empty

        # ---------- numpy 预计算 ----------
        # 先归一化索引（MultiIndex → DatetimeIndex），再按时间范围截取
        table_src   = factor.table
        returns_src = factor.returns
        table_src.index   = _extract_signal_index(table_src.index)
        returns_src.index = _extract_signal_index(returns_src.index)
        if start_date is not None:
            _sd = _align_ts(pd.Timestamp(start_date), table_src.index[0]) if len(table_src) > 0 else pd.Timestamp(start_date)
            table_src   = table_src[table_src.index >= _sd]
            _sd = _align_ts(pd.Timestamp(start_date), returns_src.index[0]) if len(returns_src) > 0 else pd.Timestamp(start_date)
            returns_src = returns_src[returns_src.index >= _sd]
        if end_date is not None:
            _ed = _align_ts(pd.Timestamp(end_date), table_src.index[0]) if len(table_src) > 0 else pd.Timestamp(end_date)
            table_src   = table_src[table_src.index <= _ed]
            _ed = _align_ts(pd.Timestamp(end_date), returns_src.index[0]) if len(returns_src) > 0 else pd.Timestamp(end_date)
            returns_src = returns_src[returns_src.index <= _ed]

        # 对齐两个 DataFrame 的索引（factor.returns 因 shift 可能比 factor.table 少最后一行）
        common_index = table_src.index.intersection(returns_src.index)
        table_src    = table_src.loc[common_index]
        returns_src  = returns_src.loc[common_index]

        # 把 factor.table / factor.returns 转成 numpy 矩阵，列为品种
        # 统一列顺序
        all_cols = list(table_src.columns)
        ret_cols  = list(returns_src.columns)
        # 只取交集（有 returns 的品种）
        valid_cols = [c for c in all_cols if c in set(ret_cols)]

        table_np  = table_src[valid_cols].to_numpy(dtype=float)   # shape (T, P)
        returns_np = returns_src[valid_cols].to_numpy(dtype=float) # shape (T, P)
        index_list = list(table_src.index)                         # len T
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

            # 破产品种：收益 <= -1 或 inf（本期不应被持有也不应被分配）
            isbad_ret = (ret_row <= -1.0) | np.isinf(ret_row)  # (P,)
            if isbad_ret.any():
                bad_products = [valid_cols[i] for i in np.where(isbad_ret)[0]]
                bad_rets = [float(ret_row[i]) for i in np.where(isbad_ret)[0]]
                print(f"[WARN] t={t} ({index_list[t]}): 品种收益异常（≤-1 或 inf），将从分配中剔除: "
                      + ", ".join(f"{p}={r:.4f}" for p, r in zip(bad_products, bad_rets)))

            # carryover：上期持有 & 本期 returns=NaN（且非破产）的品种继续保留
            if t == 0:
                carry_members = np.zeros((n_groups, P), dtype=bool)
            else:
                carry_members = current_members & isnan_ret[np.newaxis, :] & (~isbad_ret[np.newaxis, :])  # (n_groups, P)

            # active_groups：上期有持仓且本期 carryover < 上期持仓数的组，或全新组
            prev_count  = current_members.sum(axis=1)   # (n_groups,)
            carry_count = carry_members.sum(axis=1)     # (n_groups,)
            active_mask = (carry_count < prev_count) | (prev_count == 0)
            active_groups = np.where(active_mask)[0]

            # 更新 current_members 为 carryover 状态
            current_members = carry_members.copy()

            # 可分配品种 = 因子值非 NaN & 未被 carryover 持有 & 本期收益正常
            held_mask      = carry_members.any(axis=0)                      # (P,)
            available_mask = (~isnan_fac) & (~held_mask) & (~isbad_ret)     # (P,)
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
        # returns_np_filled: NaN→0，≤-1 或 inf → 0（破产品种当期按 0 收益计）
        bad_ret_mask = np.isnan(returns_np) | np.isinf(returns_np) | (returns_np <= -1.0)
        returns_filled = np.where(bad_ret_mask, 0.0, returns_np)
        # 严格资金口径：按每个品种的实际资金差额调仓。
        # 先追踪上期收益后的各品种持仓金额 pre_trade_amounts，
        # 再与本期目标等权金额 target_amounts 比较得到买卖金额差：
        # buy_amt = max(target_amounts - pre_trade_amounts, 0)
        # sell_amt = max(pre_trade_amounts - target_amounts, 0)
        # 手续费 = sum(buy_amt * open_fee + sell_amt * close_fee) / wealth_before_trade
        member_counts = membership_np.sum(axis=2).astype(float)  # (T, n_groups)

        def _variety(col) -> str:
            """从产品列名提取品种代码（大写），如 IF.CFE→IF, rb.SHF→RB。"""
            nm = getattr(col, 'name', str(col))
            return nm.split('.')[0].upper()

        half_fee = float(fee) / 2.0
        open_fee_vec = np.array([
            float((fee_map.get(_variety(c), {}) or {}).get('open', half_fee))
            for c in valid_cols
        ], dtype=float)
        close_fee_vec = np.array([
            float((fee_map.get(_variety(c), {}) or {}).get('close', half_fee))
            for c in valid_cols
        ], dtype=float)

        group_gross_returns_np = np.zeros((T, n_groups), dtype=float)
        fee_costs_np = np.zeros((T, n_groups), dtype=float)
        group_returns_np = np.zeros((T, n_groups), dtype=float)

        for g in range(n_groups):
            wealth = 1.0
            prev_end_amounts = np.zeros(P, dtype=float)
            for t in range(T):
                curr_mask = membership_np[t, g]
                curr_count = int(member_counts[t, g])
                wealth_before_trade = float(wealth)

                if wealth_before_trade <= 0:
                    prev_end_amounts = np.zeros(P, dtype=float)
                    continue

                if curr_count > 0:
                    target_amounts = curr_mask.astype(float) * (wealth_before_trade / curr_count)
                else:
                    target_amounts = np.zeros(P, dtype=float)

                buy_amounts = np.clip(target_amounts - prev_end_amounts, 0.0, None)
                sell_amounts = np.clip(prev_end_amounts - target_amounts, 0.0, None)
                fee_amount = float((buy_amounts * open_fee_vec + sell_amounts * close_fee_vec).sum())
                fee_ratio = fee_amount / wealth_before_trade

                if curr_count > 0:
                    gross_ret = float((target_amounts / wealth_before_trade * returns_filled[t]).sum())
                else:
                    gross_ret = 0.0

                net_ret = (1.0 - fee_ratio) * (1.0 + gross_ret) - 1.0
                wealth = wealth_before_trade * (1.0 + net_ret)

                group_gross_returns_np[t, g] = gross_ret
                fee_costs_np[t, g] = fee_ratio
                group_returns_np[t, g] = net_ret

                if curr_count > 0:
                    prev_end_amounts = target_amounts * (1.0 + returns_filled[t]) * (1.0 - fee_ratio)
                else:
                    prev_end_amounts = np.zeros(P, dtype=float)

        self._last_fee_costs_np = fee_costs_np  # 供 L-S 计算时使用
        self._last_group_gross_returns_np = group_gross_returns_np

        # 兼容原接口：构建 returns_dict[g][dt]
        returns_dict = {g: {index_list[t]: float(group_returns_np[t, g]) for t in range(T)} for g in range(n_groups)}

        # 预计算累积收益 (T, n_groups)，供调用方直接使用
        # 空组（某天无持仓）→ 收益为 0；inf 也置 0，防止 cumprod 链式溢出
        # r = -1（某品种跌100%）→ 1+(-1)=0，cumprod链式归零 → 同样置0
        bad = np.isnan(group_returns_np) | np.isinf(group_returns_np) | (group_returns_np <= -1.0)
        cum_rets_filled = np.where(bad, 0.0, group_returns_np)
        cumulative_returns_np = np.cumprod(1 + cum_rets_filled, axis=0)  # (T, n_groups)

        # ---------- 计算各组平均换手率 ----------
        # 换手率 = |本期持仓 △ 上期持仓| / 2 / 本期持仓数，若无持仓则为 0
        avg_turnover = np.zeros(n_groups, dtype=float)
        for g in range(n_groups):
            turnovers = []
            for t in range(1, T):
                prev = membership_np[t-1, g]
                curr = membership_np[t, g]
                prev_count = int(prev.sum())
                curr_count = int(curr.sum())
                if curr_count == 0 and prev_count == 0:
                    continue
                avg_count = (prev_count + curr_count) / 2.0
                if avg_count == 0:
                    continue
                changed = int((prev ^ curr).sum()) / 2.0
                turnovers.append(changed / avg_count)
            avg_turnover[g] = float(np.mean(turnovers)) if turnovers else 0.0

        # ---------- 汇总指标（向量化） ----------
        # 构建时间戳数组，用于日期过滤
        signal_times = pd.DatetimeIndex(index_list)   # already flat after _extract_signal_index
        _ref = signal_times[0] if T > 0 else pd.Timestamp('2000-01-01')
        mask_report = np.ones(T, dtype=bool)
        if start_date is not None:
            mask_report &= (signal_times >= _align_ts(pd.Timestamp(start_date), _ref))
        if end_date is not None:
            mask_report &= (signal_times <= _align_ts(pd.Timestamp(end_date), _ref))

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
                'Avg Turnover':  avg_turnover[idx],
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
                plot_mask &= (signal_times >= _align_ts(pd.Timestamp(_start_date), _ref))
            if _end_date is not None:
                plot_mask &= (signal_times <= _align_ts(pd.Timestamp(_end_date), _ref))
            plot_index = [index_list[t] for t in range(T) if plot_mask[t]]
            dates = plot_index
            for idx in range(n_groups):
                if plot_n_group_list is not None and idx not in plot_n_group_list:
                    continue
                rets = group_returns_np[plot_mask, idx]
                cumulative_returns = np.cumprod(1 + np.where(np.isnan(rets), 0.0, rets)) * 10000
                plt.plot(
                    [str(d.date()) for d in plot_index],
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
                ticks = [str(dates[i].date()) for i in tick_indices]
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

        # 存入 tester 的 per-factor 字典，供外部并发安全读取
        self.factor_reports[factor] = report_df
        return products_dict, returns_dict, report_df, cumulative_returns_np, index_list

    def test_by_group(self, factors: 'Optional[Factor|List[Factor]]' = None,
                      returns_col: FactorNextPeriodReturns = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED,
                      n_groups: int = 5, n_groups_name: Dict[int, str] = {},
                      time_range: Optional[Tuple] = None,
                      plot_remark_str: Optional[str] = None,
                      plot_flag: bool = False, save_plot: bool = True, plot_show: bool = True,
                      plot_n_group_list: Optional[List[int]] = None,
                      sift_volume_ratio: Optional[float] = None,
                      fee: float = 0.0, fee_map: dict = {}, **kwargs) -> Tuple[Any, Any, pd.DataFrame, np.ndarray, list]:
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
                fee=fee,
                fee_map=fee_map,
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