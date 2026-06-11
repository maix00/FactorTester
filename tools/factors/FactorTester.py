# =============================================================================
# tools/factors/FactorTester.py
# 因子测试器模块
#
# FactorTester 负责驱动因子的量化分析流程，包括：
#   - 品种管理（全量 / 按成交量筛选 / 按空数据过滤）
#   - calc_factor  : 批量计算各 Factor 的信号表
#   - ic_stats / calc_factor : 因子计算与 IC 分析
#
# 辅助函数：
#   get_factor_tester : 一键创建包含全部品种的 FactorTester 实例
# =============================================================================
import os
import uuid
import logging
import threading
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime
from weakref import WeakValueDictionary
from contextvars import ContextVar
from typing import TYPE_CHECKING, Optional, Sequence, Tuple, Callable, Any, Set, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from tools.factors import Factor, FactorFamily
from tools.factors.FactorRunResult import FactorRunResult
from tools.products.Product import Product
from tools import UniqueObject, DataColumn, DataFreq
from tools.base.User import User
from tools.factors.Parameters import StartCalcPointParam, FactorNextPeriodReturns

from Settings import get_all_products, logger_dir_path_default

if TYPE_CHECKING:
    from tools.factors.FactorTester import FactorTester

# ── 运行时上下文：活跃 FactorTester 与用户前缀 ──
# 由 FactorTester / FactorFamily.test() 设置，Factor / DataMeta 读取
_active_tester: ContextVar[Optional['FactorTester']] = ContextVar('_active_tester', default=None)
_active_user_prefix: ContextVar[str] = ContextVar('_active_user_prefix', default='$COMMON')

def _signal_time(obj: Any) -> Any:
    """从索引项中提取最末一级时间戳（兼容 tuple 多级索引和单值索引）。"""
    return obj[-1] if isinstance(obj, tuple) else obj


def _align_ts(lhs: Any, rhs: Any) -> Any:
    """将 lhs 时区对齐到 rhs；若任一非 Timestamp 则原样返回 lhs。"""
    rhs = _signal_time(rhs)
    if not isinstance(rhs, pd.Timestamp):
        try:
            rhs = pd.Timestamp(rhs)
        except Exception:
            return lhs
    if isinstance(lhs, pd.Timestamp) and isinstance(rhs, pd.Timestamp):
        if lhs.tzinfo is None and rhs.tzinfo is not None:
            return lhs.tz_localize(rhs.tz)
        if lhs.tzinfo is not None and rhs.tzinfo is None:
            return lhs.tz_localize(None)
        if lhs.tzinfo is not None and rhs.tzinfo is not None:
            return lhs.tz_convert(rhs.tz)
    return lhs


def _align_ts_to_index(ts: Any, idx: pd.Index) -> pd.Timestamp:
    """将时间戳的时区规整到 DatetimeIndex，避免 tz-aware/naive 比较错误。"""
    ts = pd.Timestamp(ts)
    idx = _extract_signal_index(idx)
    if idx.tz is None:
        return ts.tz_localize(None) if ts.tzinfo is not None else ts
    if ts.tzinfo is None:
        return ts.tz_localize(idx.tz)
    return ts.tz_convert(idx.tz)


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
    _allowed_group_calendar_freqs = (DataFreq.MIN1, DataFreq.MIN5, DataFreq.DAY1)

    def __new__(cls, alias: Optional[str] = None, *args, user=None, **kwargs):
        core_alias = alias if alias else cls.__name__
        # 将 user name 嵌入 alias，避免不同用户的同名 tester 冲突
        if user is not None:
            user_name = getattr(user, 'alias', str(user))
            core_alias = f"{user_name}:{core_alias}"
        # 显式构造 name = FactorTester:{user_prefix}:{core_alias}:{uuid}
        name = f"{cls.__name__}:{core_alias}:{uuid.uuid4().hex}"
        kwargs.pop('name', None)
        instance = super().__new__(cls, name=name, alias=core_alias, **kwargs)
        # 在 __new__ 中直接设置 name，防止 __init__ 调用 super().__init__(alias=...)
        # 时因未传 name 而被 UniqueObject.__init__ 覆盖
        instance.name = name
        return instance

    def __init__(self, products: Sequence[Product],
                 alias: Optional[str] = None,
                 time_range: Optional[Tuple] = None,
                 group_calendar_freq: Optional[Any] = None,
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
            # 传入 name=self.name 防止 UniqueObject.__init__ 重新生成 name
            # （name 已在 __new__ 中格式化为 FactorTester:{user_prefix}:{core_alias}:{uuid}）
            super().__init__(name=self.name, alias=alias)
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
            self.group_calendar_freq = DataFreq(group_calendar_freq or DataFreq.MIN1)
            self.selected_paths: list = []     # 提交时选取的路径列表（前端显示用）
            self.sift_product_by_empty_data_bool = False  # 记录是否已执行空数据过滤
            self.factors = []
            # 信号同步索引缓存（per-run，避免跨并发请求共享）
            self.sync_signal_index: Optional[pd.Index] = None
            self.sync_signal_index_replaced: Optional[pd.Index] = None
            self._sync_lock = threading.Lock()
            # Factor 计算结果（keyed by Factor 实例） — 所有 per-run 状态集中在此
            self.results: Dict['Factor', FactorRunResult] = {}
            self._results_lock = threading.RLock()
            self.last_group_factor: Optional['Factor'] = None
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
                if f.family is not None:
                    for param in list(f.family.params):
                        if not param.alias.startswith('$'):
                            try:
                                param.delete()
                            except Exception:
                                pass
                f.clear()
                f.delete()
            except Exception:
                pass
        # 清空 per-factor 缓存
        with self._results_lock:
            for result in self.results.values():
                result.clear_caches()
            self.results.clear()
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

    def _get_result(self, factor: 'Factor') -> FactorRunResult:
        """获取或创建 factor 对应的 FactorRunResult（公用的访问入口）。"""
        with self._results_lock:
            if factor not in self.results:
                self.results[factor] = FactorRunResult(factor=factor)
            return self.results[factor]

    def discard_result(self, factor: 'Factor', *, clear_factor: bool = True) -> None:
        """释放不再可达的 factor 运行结果及其中间表。"""
        with self._results_lock:
            result = self.results.pop(factor, None)
        if result is not None:
            result.clear_caches()
        if self.last_group_factor is factor:
            self.last_group_factor = None
        if clear_factor:
            factor.clear()

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
            desc = f'Calculate {len(factors)} factors for {len(self.products)} products'
            # 捕获当前 context 中 _active_tester 的值，在每个 worker 线程里手动设置
            token = _active_tester.get()
            def _calc_one(factor: Factor) -> None:
                _active_tester.set(token)
                factor.evaluate(self.products)
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
                factor.evaluate(self.products)

    def ic_stats(self, ic_series: pd.Series) -> pd.Series:
        """计算 IC 序列的汇总统计量。"""
        from tools.factors.tests.single_factor_test.ic import ic_stats
        return ic_stats(ic_series)

    def resolve_factor(self, factor_alias: str) -> Optional['Factor']:
        """Resolve factor by alias or name within this tester."""
        return next(
            (f for f in self.factors if f.alias == factor_alias or f.name == factor_alias),
            None,
        )

    @classmethod
    def allowed_group_calendar_freqs(cls) -> tuple[DataFreq, ...]:
        return tuple(DataFreq(freq) for freq in cls._allowed_group_calendar_freqs)

    def collect_group_factor_freqs(self, factor_aliases: List[str]) -> List[DataFreq]:
        freqs: list[DataFreq] = []
        for factor_alias in factor_aliases:
            factor = self.resolve_factor(str(factor_alias))
            if factor is None:
                continue
            try:
                factor_freq = factor.freq
            except Exception:
                factor_freq = None
            if factor_freq is None:
                continue
            freqs.append(DataFreq(factor_freq))
        return freqs

    @classmethod
    def resolve_group_calendar_freq_from_factor_freqs(
        cls,
        factor_freqs: Sequence[DataFreq],
        requested: Optional[Any] = None,
    ) -> DataFreq:
        allowed = cls.allowed_group_calendar_freqs()
        if not factor_freqs:
            if requested in (None, '', 'auto', 'AUTO'):
                return DataFreq.MIN1
            calendar_freq = DataFreq(requested)
            if str(calendar_freq) not in {str(freq) for freq in allowed}:
                raise ValueError(
                    "group_calendar_freq 只允许 "
                    f"{[str(freq) for freq in allowed]}，收到 {calendar_freq}"
                )
            return calendar_freq

        def _is_compatible(candidate: DataFreq) -> bool:
            base_ns = candidate.value.value
            return base_ns > 0 and all(freq.value.value > 0 and freq.value.value % base_ns == 0 for freq in factor_freqs)

        if requested in (None, '', 'auto', 'AUTO'):
            for candidate in reversed(allowed):
                if _is_compatible(candidate):
                    return candidate
            raise ValueError(
                "参与测试的因子频率无法映射到允许的 group_calendar_freq "
                f"{[str(freq) for freq in allowed]}"
            )

        calendar_freq = DataFreq(requested)
        if str(calendar_freq) not in {str(freq) for freq in allowed}:
            raise ValueError(
                "group_calendar_freq 只允许 "
                f"{[str(freq) for freq in allowed]}，收到 {calendar_freq}"
            )
        if not _is_compatible(calendar_freq):
            raise ValueError(
                f"group_calendar_freq={calendar_freq} 不能整除参与测试的全部因子频率 "
                f"{[str(freq) for freq in factor_freqs]}"
            )
        return calendar_freq

    def resolve_group_calendar_freq(self, factor_aliases: List[str], requested: Optional[Any] = None) -> DataFreq:
        """Resolve effective group calendar frequency for these factors."""
        setting = self.group_calendar_freq if requested is None else requested
        factor_freqs = self.collect_group_factor_freqs(factor_aliases)
        return self.resolve_group_calendar_freq_from_factor_freqs(factor_freqs, setting)

    def build_group_calendar_index(self, factor_aliases: List[str], requested_calendar_freq: Optional[Any] = None) -> pd.Index:
        """Build a dense shared signal calendar for group testing within this tester."""
        from typing import cast
        from tools.factors.tests.single_factor_test.group.core import (
            align_table_for_group,
            get_factor_table_for_group,
        )

        calendar_freq = self.resolve_group_calendar_freq(factor_aliases, requested_calendar_freq)
        indices: list[pd.DatetimeIndex] = []

        for factor_alias in factor_aliases:
            factor = self.resolve_factor(str(factor_alias))
            if factor is None:
                continue
            result = self._get_result(factor)
            raw_returns = getattr(result, 'returns', None)
            if not isinstance(raw_returns, pd.DataFrame) or raw_returns.empty:
                continue
            try:
                table_src = get_factor_table_for_group(self, factor)
                returns_src = align_table_for_group(factor, raw_returns)
            except Exception:
                continue
            table_idx = _extract_signal_index(cast(pd.DataFrame, table_src).index)
            returns_idx = _extract_signal_index(cast(pd.DataFrame, returns_src).index)
            idx = pd.DatetimeIndex(table_idx.intersection(returns_idx)).dropna()
            if len(idx) == 0:
                continue
            indices.append(idx)
        merged = self.merge_group_calendar_indices(indices)
        if len(merged) == 0:
            return merged
        merged_idx = pd.DatetimeIndex(merged).sort_values()
        start = merged_idx[0]
        end = merged_idx[-1]
        return pd.date_range(start=start, end=end, freq=calendar_freq.value)

    @staticmethod
    def merge_group_calendar_indices(indices: Sequence[pd.Index]) -> pd.Index:
        """Merge signal calendars across factors or testers into one dense shared index."""
        cleaned: list[pd.DatetimeIndex] = []
        tz_kinds: set[str] = set()
        tz_values: set[str] = set()

        for idx in indices:
            if len(idx) == 0:
                continue
            dt_idx = pd.DatetimeIndex(idx).dropna()
            if len(dt_idx) == 0:
                continue
            cleaned.append(dt_idx)
            if dt_idx.tz is None:
                tz_kinds.add('naive')
            else:
                tz_kinds.add('aware')
                tz_values.add(str(dt_idx.tz))

        if not cleaned:
            return pd.Index([])

        same_tz = len(tz_kinds) == 1 and (('naive' in tz_kinds) or len(tz_values) == 1)
        if same_tz:
            merged = cleaned[0]
            for dt_idx in cleaned[1:]:
                merged = merged.union(dt_idx)
            return pd.DatetimeIndex(merged).sort_values().unique()

        utc_values: list[pd.Timestamp] = []
        for dt_idx in cleaned:
            for value in dt_idx:
                ts = pd.Timestamp(value)
                utc_values.append(ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC'))
        return pd.DatetimeIndex(utc_values).sort_values().unique()

def get_factor_tester(time_range: Optional[Any] = None) -> FactorTester:
    """
    创建包含全部品种的 FactorTester 实例（便捷工厂函数）。

    参数：
        time_range : (start, end) 测试时间区间，None 则不设置

    返回：
        FactorTester 实例
    """
    return FactorTester(products=get_all_products(), time_range=time_range)
