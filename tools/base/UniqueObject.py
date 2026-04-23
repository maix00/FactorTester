# =============================================================================
# tools/base/UniqueObject.py
# 唯一对象基类模块
#
# 提供全局唯一对象标识机制：同一类中 name 相同的实例会返回同一个对象（单例模式）。
# 所有核心业务对象（Product、DataSource、Factor、Parameter 等）均继承自此类。
# =============================================================================
from abc import ABC
import threading
from typing import Any
from weakref import WeakValueDictionary

class UniqueObject(ABC):
    '''
    唯一对象基类。

    设计原则：
      - 以 (name, 类名) 为键，使用弱引用字典 _instances 全局缓存实例。
      - 同一类中 name 相同的对象只会被创建一次，后续调用 __new__ 直接返回缓存实例。
      - 弱引用确保当外部无强引用时，实例可被垃圾回收，避免内存泄漏。

    直接子类：SerialObject, Product, CNFutures, Factor, Parameter, DataSource, DataMeta 等。
    '''

    # 弱引用实例字典，键为 (name, 类名)，保证同类同名对象全局唯一
    _instances = WeakValueDictionary()
    # 保护 _instances 读写的类级别锁
    _instances_lock = threading.Lock()

    def __new__(cls, name: str, *args, **kwargs):
        """对象创建钩子：若同名实例已存在则直接返回，否则新建并注册。"""
        key = (name, cls.__name__)
        with cls._instances_lock:
            if key in cls._instances:
                return cls._instances[key]
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return instance
    
    def __init__(self, name: str, *args, **kwargs):
        """仅在首次创建时初始化，防止复用已有实例时重复初始化。"""
        if not hasattr(self, '_initialized'):
            self.name = name           # 全局唯一名称，作为身份标识
            if not hasattr(self, 'alias'):
                self.alias = name      # 用于显示的别名，默认与 name 相同
            self._initialized = True   # 标记已初始化，防止重入

    def __reduce__(self):
        """pickle 序列化支持：反序列化时通过 (类, (name,)) 重建实例。"""
        return (self.__class__, (self.name,))

    def __str__(self):
        """字符串表示直接返回 name。"""
        return self.name
        
    def __lt__(self, other):
        """按 name 字典序比较，支持排序操作。"""
        return self.name < other.name

    def __eq__(self, other):
        """相等性判断：name 相同即视为同一对象。"""
        return self.name == other.name

    def __hash__(self):
        """哈希值基于 name，支持作为字典键或集合元素。"""
        return hash(self.name)
    
    def __repr__(self):
        """repr 与 str 一致，均返回 name。"""
        return self.name
    
    def delete(self):
        """从全局缓存中移除该实例，使其可被垃圾回收。"""
        key = (self.name, self.__class__.__name__)
        self._instances.pop(key, None)