# =============================================================================
# tools/factors/FactorTester.py
# 因子测试器 -- 纯粹的任务调度薄封装。
#
# 实际状态（products/factors/results 缓存等）在 FactorTesterState
# （factor_tester_state.py），实际任务逻辑在 factor_tester_tasks.py（IC/
# 因子评估等）和 backtester.py（分组回测）。FactorTester 自己只剩三件事：
#   - __new__/身份（UniqueNameObject，供 runtime_state.register_page_object/
#     get_page_object 做跨请求复用，不能动）
#   - __init__ 建 self.state
#   - dispatch(task_name, **kwargs) 按任务名转发给对应处理函数
# 加一层显式属性转发（products/results/...），因为 tools/factors/Factors.py、
# tools/factors/FactorFamily.py 等核心因子求值代码会直接读
# `_active_tester.get()` 拿到的 tester 实例的这些属性（duck typing），这些
# 调用点跟 issue-114 无关，不在这次改造范围内，转发层保证它们不用改。
# 用显式 @property 而不是 __getattr__/__setattr__ 魔法：UniqueNameObject.
# __new__/__init__ 会在 self.state 存在之前就对 self 做普通属性赋值
# （name/alias），__setattr__ 拦截会在那个时间点访问还不存在的 self.state，
# 显式属性没有这个时序问题。
# =============================================================================
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, Sequence
from weakref import WeakValueDictionary

from tools.data.types import UniqueNameObject

from tools.factors import factor_tester_tasks as _tasks
from tools.factors.factor_tester_state import FactorTesterState

if TYPE_CHECKING:
    from tools.data.account_manage import User
    from tools.data.types import DataTime
    from tools.factors.FactorTester import FactorTester
    from tools.products.Product import Product

# ── 运行时上下文：活跃 FactorTester 与用户前缀 ──
# 由 FactorTester / FactorFamily.test() 设置，Factor / ProductDataView 读取
_active_tester: ContextVar[Optional['FactorTester']] = ContextVar('_active_tester', default=None)
_active_user_prefix: ContextVar[str] = ContextVar('_active_user_prefix', default='$COMMON')


def _signal_time(obj: Any) -> Any:
    """从索引项中提取最末一级时间戳（兼容 tuple 多级索引和单值索引）。"""
    return obj[-1] if isinstance(obj, tuple) else obj


def _align_ts(lhs: Any, rhs: Any) -> Any:
    """将 lhs 时区对齐到 rhs；若任一非 Timestamp 则原样返回 lhs。"""
    import pandas as pd
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


def _align_ts_to_index(ts: Any, idx: Any) -> Any:
    """将时间戳的时区规整到 DatetimeIndex，避免 tz-aware/naive 比较错误。"""
    from tools.data.types import DataIndex
    return DataIndex(idx).tz_align(ts)


def _forward(attr_name: str) -> property:
    """生成一个转发到 self.state.{attr_name} 的可读可写 property。"""
    def getter(self):
        return getattr(self.state, attr_name)

    def setter(self, value):
        setattr(self.state, attr_name, value)

    return property(getter, setter)


class FactorTester(UniqueNameObject):
    _instances = WeakValueDictionary()

    # task_name -> handler(state, **kwargs)。新增任务只在这里加一行，
    # FactorTester 类本身不为任何任务写专门方法。
    _TASK_HANDLERS: ClassVar[dict[str, Callable]] = {
        "calc_factor": _tasks.calc_factor,
        "resolve_factor": _tasks.resolve_factor,
        "get_result": _tasks.get_result,
        "discard_result": _tasks.discard_result,
        "update_time_range": _tasks.update_time_range,
        "sift_product": _tasks.sift_product,
        "sift_product_by_empty_data": _tasks.sift_product_by_empty_data,
        "sift_product_by_volumes": _tasks.sift_product_by_volumes,
        "ic_stats": _tasks.ic_stats,
        "delete": _tasks.delete,
    }

    # 属性转发表 -- 外部代码（Factors.py/FactorFamily.py/server 路由）直接
    # 读写的全部 FactorTesterState 字段，逐一显式声明，不用 __getattr__ 魔法。
    products = _forward("products")
    all_products = _forward("all_products")
    factors = _forward("factors")
    results = _forward("results")
    start_dt = _forward("start_dt")
    end_dt = _forward("end_dt")
    start_date = _forward("start_date")
    end_date = _forward("end_date")
    group_calendar_freq = _forward("group_calendar_freq")
    selected_paths = _forward("selected_paths")
    sift_product_by_empty_data_bool = _forward("sift_product_by_empty_data_bool")
    sync_signal_index = _forward("sync_signal_index")
    sync_signal_index_replaced = _forward("sync_signal_index_replaced")
    last_group_factor = _forward("last_group_factor")
    logger = _forward("logger")
    user = _forward("user")
    label = _forward("label")
    product_group = _forward("product_group")
    product_group_template_id = _forward("product_group_template_id")
    selection_source_type = _forward("selection_source_type")
    selection_source_key = _forward("selection_source_key")
    product_selection = _forward("product_selection")
    account = _forward("account")
    _page_uuid = _forward("_page_uuid")

    def __new__(cls, alias: Optional[str] = None, *args, user=None, **kwargs):
        core_alias = alias if alias else cls.__name__
        if user is not None:
            user_name = getattr(user, 'alias', str(user))
            core_alias = f"{user_name}:{core_alias}"
        name = f"{cls.__name__}:{core_alias}:{uuid.uuid4().hex}"
        kwargs.pop('name', None)
        instance = super().__new__(cls, name=name, alias=core_alias, **kwargs)
        # 在 __new__ 中直接设置 name，防止 __init__ 调用 super().__init__(alias=...)
        # 时因未传 name 而被 UniqueObject.__init__ 覆盖
        instance.name = name
        return instance

    def __init__(
        self, products: Sequence["Product"], alias: Optional[str] = None,
        start_dt: Optional["DataTime"] = None, end_dt: Optional["DataTime"] = None,
        group_calendar_freq: Optional[Any] = None, user: Optional["User"] = None,
    ):
        if not hasattr(self, '_initialized'):
            super().__init__(name=self.name, alias=alias)
            self.state = FactorTesterState(
                products, alias=alias, start_dt=start_dt, end_dt=end_dt,
                group_calendar_freq=group_calendar_freq, user=user,
            )

    def dispatch(self, task_name: str, **kwargs: Any) -> Any:
        if task_name == "backtest" and "backtest" not in self._TASK_HANDLERS:
            from tools.testers.backtest.engines.native.backtester import run_backtest_task
            FactorTester._TASK_HANDLERS["backtest"] = run_backtest_task
        handler = self._TASK_HANDLERS[task_name]
        return handler(self.state, **kwargs)

    # ── Thin one-line delegators, kept as real methods (not dispatch-only) ──
    # tools/factors/Factors.py and tools/factors/FactorFamily.py -- the core
    # factor-evaluation machinery used everywhere, not just single_factor_test
    # routes -- call these directly on whatever `_active_tester.get()`
    # returns via duck typing. Rewriting that (unrelated to issue-114, used
    # repo-wide) is out of scope here, so these four stay real methods;
    # everything else routes through dispatch().
    def _get_result(self, factor: Any) -> Any:
        return _tasks.get_result(self.state, factor)

    def discard_result(self, factor: Any, *, clear_factor: bool = True) -> None:
        _tasks.discard_result(self.state, factor, clear_factor=clear_factor)

    def calc_factor(
        self, factors: Any, parallel: bool = True, max_workers: int = 4,
        warmup_window: Any = None,
    ) -> None:
        _tasks.calc_factor(
            self.state, factors, parallel=parallel, max_workers=max_workers,
            warmup_window=warmup_window,
        )

    def resolve_factor(self, factor_alias: str) -> Any:
        return _tasks.resolve_factor(self.state, factor_alias)


def get_factor_tester(start_dt: Optional["DataTime"] = None, end_dt: Optional["DataTime"] = None) -> FactorTester:
    """创建包含全部品种的 FactorTester 实例（便捷工厂函数）。"""
    from settings import get_all_products
    return FactorTester(products=get_all_products(), start_dt=start_dt, end_dt=end_dt)
