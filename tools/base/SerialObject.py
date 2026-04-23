# =============================================================================
# tools/base/SerialObject.py
# 序列号对象基类模块
#
# 在 UniqueObject 基础上增加「类型别名 + 序列号」机制：
#   - 每个 type_alias（如 'F'、'FF'、'P'）维护独立计数器，产生形如 F@0、F@1 的唯一名称。
#   - single_use 模式下使用全局递增计数器，不在 serial_map 中注册，适用于临时对象。
#   - 支持通过 Cls[N] 下标语法按序列号快速检索实例。
# =============================================================================
import threading
from typing import Dict, Optional
from weakref import WeakValueDictionary

from tools.base.UniqueObject import UniqueObject

class SerialObject(UniqueObject):
    # 保护计数器的类级别锁（所有子类共享，保证跨线程序列号唯一性）
    _counter_lock = threading.Lock()
    # 一次性（single_use）对象的全局计数器，从 -1 开始递增
    _single_use_count = -1
    # 各 type_alias 的实例计数器，键为 type_alias，值为当前最大序列号
    _instance_count_dict: Dict[str, int] = {}
    # 各 type_alias 的序列号→实例弱引用映射，支持 Cls[N] 快速查找
    _serial_map_dict: Dict[str, WeakValueDictionary] = {}
    # 记录每个 type_alias 的注册来源类，防止跨类族重用同一别名
    _type_alias_owners: Dict[str, type] = {}
    # 当前类的 type_alias（创建时动态写入）
    _type_alias: str = 'SO'
    # __new__ 传递给 __init__ 的序列号暂存（实例级，仅在初始化期间有效）
    _pending_serial: int

    @classmethod
    def _get_family_root(cls):
        """
        获取继承链中最近的「直接继承 SerialObject 的子类」，作为同族对象的注册根。
        若子类设置了 _override_family_root = True，则以该子类自身为根。
        """
        if getattr(cls, '_override_family_root', False):
            return cls
        for base in cls.__mro__:
            if SerialObject in base.__bases__:
                return base
            if base is SerialObject:
                break
        return SerialObject

    def __new__(cls, type_alias: str, alias: Optional[str] = None, search: bool = False, single_use: bool = False, *args, **kwargs):

        with cls._counter_lock:
            if type_alias in cls._type_alias_owners:
                owner = cls._type_alias_owners[type_alias]
                if not issubclass(cls, owner):
                    raise ValueError(f"type_alias '{type_alias}' is already used by {owner.__name__} family")
            else:
                cls._type_alias_owners[type_alias] = cls._get_family_root()
                owner = cls

            owner._type_alias = type_alias
            cls._type_alias = type_alias

            if search and type_alias in cls._serial_map_dict:
                for instance in cls._serial_map_dict[type_alias].values():
                    if instance.alias == alias and instance.__class__ is cls:
                        assert isinstance(instance, cls)
                        return instance

            if single_use:
                cls._single_use_count += 1
                serial = cls._single_use_count
                name = f"{type_alias}@SU@{serial}"
            else:
                if type_alias in cls._instance_count_dict:
                    cls._instance_count_dict[type_alias] += 1
                else:
                    cls._instance_count_dict[type_alias] = 0
                serial = cls._instance_count_dict[type_alias]
                name = f"{type_alias}@{serial}"
                name = name if alias is None else f"{name}:{alias}"
        instance = super().__new__(cls, name=name)
        if not hasattr(instance, '_initialized'):
            instance._pending_serial = serial
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, single_use: bool = False, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            serial = self._pending_serial
            if single_use:
                name = f"{type_alias}@SU@{serial}"
            else:
                self.serial_number = serial
                name = f"{type_alias}@{self.serial_number}"
            self.alias = alias or name
            name = name if alias is None else f"{name}:{alias}"
            super().__init__(name=name)
            if not single_use:
                with self._counter_lock:
                    self._serial_map_dict.setdefault(type_alias, WeakValueDictionary())[self.serial_number] = self

    def __reduce__(self):
        return (self.__class__, (self.alias,))
    
    def __class_getitem__(cls, key):
        if isinstance(key, int):
            type_alias = cls._type_alias
            if type_alias in cls._serial_map_dict and key in cls._serial_map_dict[type_alias]:
                item = cls._serial_map_dict[type_alias][key]
                assert isinstance(item, cls)
                return item
            else:
                raise KeyError(f"No instance with serial number {key} found in {cls.__name__} family")
        raise TypeError(f"Invalid key type: {type(key).__name__}. Expected int for serial number lookup.")
    
    def delete(self):
        type_alias = self._type_alias
        serial_number = getattr(self, 'serial_number', None)
        if serial_number is not None and type_alias in self._serial_map_dict and serial_number in self._serial_map_dict[type_alias]:
            del self._serial_map_dict[type_alias][serial_number]
        super().delete()