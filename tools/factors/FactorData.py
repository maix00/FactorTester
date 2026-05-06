# =============================================================================
# tools/factors/FactorData.py
# 因子数据抽象层
#
# FactorData = FactorExpr 的结构化去重存储。
#
# 四层架构中的第 2 层（数据层）：
#   Layer 1: FactorExpr — 纯数学表达式树（运算、求值、LaTeX、结构等价）
#   Layer 2: FactorData  — 结构化去重的中间数据存储  ← 本模块
#   Layer 3: Factor      — 持有 FactorData 引用 + 源表/对齐表
#   Layer 4: FactorTester — 调度器，驱动计算 & 收集结果
#
# 核心概念：
#   - FactorData 继承 UniqueObject，按表达式 _structural_hash() 全局去重
#     同一表达式跨 Factor / 跨进程共享存储，只算一次
#   - 本地 WeakValueDictionary（继承自 UniqueObject）+ StorageBackend（Redis/本地）
#     双层去重：同进程走弱引用缓存，跨进程走 StorageBackend.set_if_absent()
#   - backend 仅做存在性标记（value="1"），不存 DataFrame
#   - FactorData 纯存储，不负责对齐。对齐由 SignalAlign 表达式节点完成
#   - pandas 3.0 Copy-on-Write 已内置 view 语义，不需要手动管理对齐视图
#
# 数据流：
#   FactorExpr.evaluate() → DataFrame
#       ↓
#   FactorData(expr, source_table)  ← UniqueObject 去重（跨进程共享身份）
#   SignalAlign(expr, ...).evaluate() → 对齐后的 DataFrame (CoW)
# =============================================================================
from __future__ import annotations

from typing import Optional, TYPE_CHECKING, cast

import pandas as pd

from tools.base.UniqueObject import UniqueObject
from tools.factors import FactorExpr


# ═════════════════════════════════════════════════════════════════════════════
# FactorData — 结构化去重的中间因子数据
# ═════════════════════════════════════════════════════════════════════════════

class FactorData(UniqueObject):
    """
    因子中间数据容器 —— 按表达式结构去重，同一表达式跨 Factor / 跨进程共享。

    继承 UniqueObject：
      - name = structural_key（str），作为全局唯一标识
      - 本地 WeakValueDictionary 缓存（同进程快速路径）
      - StorageBackend（Redis / 本地）做跨进程 identity 协调
      - backend 仅做存在性标记（value="1"），不存 DataFrame

    用法：
      fd = FactorData(expr, source_table)            # 获取或创建（自动去重）
      view = fd.align('1d', basepoint='last')         # 创建对齐视图
      fd = FactorData.get_by_hash(structural_hash)    # 按 hash 查找已有实例
    """

    __slots__ = ('_source_table', '_expr_sk')

    def __new__(cls, expr: FactorExpr, alias: Optional[str] = None,
                *args, **kwargs):
        """预先计算 structural_key，传入 UniqueObject.__new__ 构造 2D key。"""
        if alias is None:
            if expr._is_intermediate and hasattr(expr, '_intermediate_name') and expr._intermediate_name is not None:
                from tools.factors import Factor
                if hasattr(expr, '_intermediate_factor') and expr._intermediate_factor is not None and isinstance(expr._intermediate_factor, Factor):
                    alias = f"{expr._intermediate_name}:{expr._intermediate_factor.alias}"
                else:
                    alias = expr._intermediate_name
            else:
                alias = 'AnonymousFactorData'
        name = f"{alias}:{expr._structural_hash()}"
        sk = expr._structural_key()
        return super().__new__(cls, name=kwargs.pop('name', name), alias=kwargs.pop('alias', alias), _structural_key=sk, *args, **kwargs)

    def __init__(self, expr: 'Optional[FactorExpr]' = None,
                 source_table: Optional[pd.DataFrame] = None, *args, **kwargs):
        """创建或复用 FactorData。"""
        if not hasattr(self, '_initialized'):
            # 首次初始化 —— name/alias 已在 __new__ 中设置
            self._initialized = True
            self._source_table = source_table
            # 保存表达式结构 key，供 _structural_key() 使用
            self._expr_sk = expr._structural_key() if expr is not None else None
        self._source_table = source_table if source_table is not None else pd.DataFrame()  # 确保 _source_table 不为 None   

    # ── 工厂方法 ──

    @classmethod
    def get_by_hash(cls, structural_hash: str) -> 'Optional[FactorData]':
        """按结构 hash 字符串查找已有 FactorData（遍历 name 匹配）。"""
        with cls._instances_lock:
            for (name, sk), inst in cls._instances.items():
                if name == structural_hash and inst is not None:
                    return cast('Optional[FactorData]', inst)
        return None

    @classmethod
    def clear_all(cls):
        """清空所有实例（测试用）。"""
        with cls._instances_lock:
            keys = list(cls._instances.keys())
            for key in keys:
                del cls._instances[key]
        with cls._alias_index_lock:
            cls._alias_index.clear()

    # ── 结构 key（覆盖 UniqueObject，用于 2D key 去重） ──

    def _structural_key(self):
        """返回表达式结构 key（与创建时传入的 expr._structural_key() 一致）。"""
        return getattr(self, '_expr_sk', None)
    
    def _structural_eq(self, other: 'FactorData') -> bool:
        """结构等价比较（基于表达式结构 key）。"""
        return self._structural_key() == other._structural_key()

    # ── 属性 ──

    @property
    def structural_hash(self) -> str:
        """结构哈希字符串（即 name，用于日志/调试）。"""
        return self.name

    @property
    def source_table(self) -> pd.DataFrame:
        """未对齐的原始数据。"""
        assert self._source_table is not None, "FactorData.source_table 不得为 None"
        return self._source_table

    @source_table.setter
    def source_table(self, value: pd.DataFrame):
        self._source_table = value

    def __repr__(self) -> str:
        h = self.name[:40] if self.name else '?'
        rows = len(self._source_table) if self._source_table is not None else 0
        return f"FactorData({h}..., rows={rows})"
