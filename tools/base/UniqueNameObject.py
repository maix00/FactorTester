# =============================================================================
# tools/base/UniqueNameObject.py
# 别名去重基类
#
# 最小化抽象：同 name 同实例。无 search/structural_key/alias_index/delete。
#
# 使用：
#   class MyClass(UniqueNameObject):
#       def __init__(self, name=None, alias=None, **kwargs):
#           super().__init__(name=name, alias=alias, **kwargs)
# =============================================================================
from __future__ import annotations

import threading
import uuid
from abc import ABC
from weakref import WeakValueDictionary


class UniqueNameObject(ABC):
    """同 name 同实例的去重基类。"""

    name: str
    alias: str

    def __init_subclass__(cls, **kwargs):
        """每个子类独立实例池和锁。"""
        super().__init_subclass__(**kwargs)
        cls._instances = WeakValueDictionary()
        cls._instances_lock = threading.Lock()

    def __new__(cls, name: str | None = None, alias: str | None = None, **kwargs):
        key = name or (alias or cls.__name__) + ':' + uuid.uuid4().hex
        with cls._instances_lock:
            if key in cls._instances:
                return cls._instances[key]
            instance = super().__new__(cls)
            cls._instances[key] = instance
        instance.name = key
        instance.alias = alias or key
        return instance

    def __init__(self, **kwargs):
        if not hasattr(self, '_initialized'):
            self._initialized = True

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name

    def __lt__(self, other) -> bool:
        return self.name < other.name

    def __eq__(self, other) -> bool:
        if type(self) is not type(other):
            return False
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
