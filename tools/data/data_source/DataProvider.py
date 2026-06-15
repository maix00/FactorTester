"""数据提供器元类与抽象基类。

层级：
  _DataProviderMeta           — 标记元类（所有 DataProvider 的基类元类）
  _DataMultipleProviderMeta   — 多实例注册表元类（继承自 _DataProviderMeta）
  DataProvider(ABC)           — 抽象基类，定义 sync() / ensure_schema() 契约
"""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from typing import Any, Dict


class _DataProviderMeta(ABCMeta):
    """数据提供器基类元类 — 纯标记，不携带注册逻辑。"""


class _DataMultipleProviderMeta(_DataProviderMeta):
    """
    数据多提供器元类 — 可为任意子类提供全局注册表。

    任一使用本元类的子类自动获得：
      - for ds in SubClass          遍历所有已注册的实例
      - ds in SubClass              判断某个实例是否已注册
      - SubClass['alias']           按别名查找
      - 默认实例管理：第一个被创建的实例自动成为默认

    不硬编码任何子类名；所有引用通过 cls 动态解析。
    """
    # 按子类隔离注册表，避免不同子类同名 alias 冲突。
    _sources_registry: Dict[type, Dict[str, Any]] = {}
    _default_sources: Dict[type, Any] = {}

    def _ensure_registry(cls):
        """为当前子类懒初始化独立注册表。"""
        if cls not in cls._sources_registry:
            cls._sources_registry[cls] = {}
        return cls._sources_registry[cls]

    def __iter__(cls):
        """for item in cls 语法支持。"""
        return iter(cls._ensure_registry().values())

    def __contains__(cls, item):
        """in 运算符支持。"""
        return item in cls._ensure_registry().values()

    def __getitem__(cls, name: str):
        """cls['alias'] 下标语法。"""
        return cls._ensure_registry()[name]

    def _register_source(cls, source):
        """将源注册到当前子类的独立字典中（若未重复注册）。"""
        reg = cls._ensure_registry()
        if source.alias not in reg:
            reg[source.alias] = source
        return source

    def get_default_source(cls):
        """获取当前子类的默认数据源。"""
        return cls._default_sources.get(cls)

    def set_default_source(cls, source):
        """设置当前子类的默认数据源。"""
        cls._default_sources[cls] = source
        return source


class DataProvider(ABC, metaclass=_DataProviderMeta):
    """
    数据提供器抽象基类。

    所有需要与 data.sqlite 交互的数据源（本地文件、线上同步等）
    继承此类并实现 sync() 和 ensure_schema()。

    属性：
        key  (str) : 唯一标识，如 "opencpt/products"
        label(str) : 可读名称，如 "OpenCTP品种列表"
    """

    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label

    @abstractmethod
    def ensure_schema(self, conn) -> None:
        """在给定 sqlite3.Connection 上建表/VIEW。"""
        ...

    @abstractmethod
    def sync(self, conn, refresh: bool = False) -> int:
        """同步数据到 data.sqlite，返回新增行数。"""
        ...
