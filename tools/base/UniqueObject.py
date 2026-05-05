# =============================================================================
# tools/base/UniqueObject.py
# 唯一对象基类模块
#
# 提供全局唯一对象标识机制：同一类中 name 相同的实例会返回同一个对象（单例模式）。
# 所有核心业务对象（Product、DataSource、Factor、Parameter 等）均继承自此类。
#
# 对象命名规则：
#   - name = {alias}:{uuid}  —— 所有对象统一用 uuid，保证跨进程不可碰撞
#   - alias 是可选的可读别名，用于 search 查找已有实例
#
# 支持两种查找方式：
#   - search=True  创建时调用：按 alias 在同类的已有实例中查找并复用
#   - UniqueObject.get('ClassName:alias:uuid') 调试时调用：按 name 精确查找
#
# 支持可插拔存储后端（单机 / 分布式）：
#   - 默认使用弱引用字典（WeakValueDictionary）做本地缓存
#   - 通过 UniqueObject.set_backend(storage_backend) 切换到 Redis 等分布式后端
#   - 未设置后端时自动回退到 LocalStorageBackend
# =============================================================================
from abc import ABC
import threading
import uuid
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from tools.base.StorageBackend import StorageBackend

class UniqueObject(ABC):
    '''
    唯一对象基类。

    设计原则：
      - 以 (类名, name) 为 key，通过可插拔的 StorageBackend 实现跨进程/单机缓存。
      - name = {alias}:{uuid}，所有对象统一用 uuid，不再使用序列号。
      - 默认使用 WeakValueDictionary 本地缓存；可通过 set_backend() 切换到分布式后端。
    '''

    # ── 类级别存储后端（所有子类共享） ──
    _backend: 'ClassVar[Optional[StorageBackend]]' = None
    _backend_lock: 'ClassVar[threading.Lock]' = threading.Lock()

    # ── 本地弱引用缓存（始终保留，作为第一层查询加速 + 兜底） ──
    _instances: 'ClassVar[WeakValueDictionary]' = WeakValueDictionary()
    _instances_lock: 'ClassVar[threading.Lock]' = threading.Lock()

    # ── alias → instance 查找索引 ──
    _alias_index: 'ClassVar[Dict[str, WeakValueDictionary]]' = {}
    _alias_index_lock: 'ClassVar[threading.Lock]' = threading.Lock()

    name: str
    alias: str
    desc: str

    def __init_subclass__(cls, **kwargs):
        """每个子类自动维护独立的弱引用实例池、锁和别名索引，无需显式声明。"""
        super().__init_subclass__(**kwargs)
        cls._instances = WeakValueDictionary()
        cls._instances_lock = threading.Lock()
        cls._alias_index = {}
        cls._alias_index_lock = threading.Lock()

    # ── 后端管理 ──

    @classmethod
    def set_backend(cls, backend: 'StorageBackend') -> None:
        """设置全局存储后端（所有 UniqueObject 子类共享）。"""
        with cls._backend_lock:
            UniqueObject._backend = backend

    @classmethod
    def _ensure_backend(cls) -> 'StorageBackend':
        """确保后端已初始化；未设置时自动回退到 LocalStorageBackend。"""
        backend = UniqueObject._backend
        if backend is not None:
            return backend
        with cls._backend_lock:
            backend = UniqueObject._backend
            if backend is None:
                from tools.base.StorageBackend import LocalStorageBackend
                backend = LocalStorageBackend()
                UniqueObject._backend = backend
        return backend

    # ── 调试用查找 ──

    @classmethod
    def get(cls, name: str) -> 'Optional[UniqueObject]':
        """
        按 name 精确查找实例（调试/断点检查用）。

        支持三种格式：
          - 完整 name：'FactorTester:1628000000:a1b2c3d4...'
          - 简短 alias：'1628000000' → 在 _alias_index 中查找
          - 类限定：    'FactorTester:1628000000' → 先缩小到子类再查

        返回 None 若不存在或已被 GC。
        """
        instance = cls._instances.get(name)
        if instance is not None:
            return instance
        # 尝试作为 alias 查找
        with cls._alias_index_lock:
            if name in cls._alias_index:
                instances = list(cls._alias_index[name].values())
                if instances:
                    return instances[0]
        return None

    @classmethod
    def get_all(cls) -> 'List[Tuple[str, UniqueObject]]':
        """返回所有存活实例的 (name, instance) 列表（调试用）。"""
        with cls._instances_lock:
            return [(k, v) for k, v in cls._instances.items() if v is not None]

    # ── 实例创建 ──

    def __new__(cls, name: Optional[str] = None, alias: Optional[str] = None,
                search: bool = False, _local_only: bool = False, *args, **kwargs):
        """
        对象创建钩子。

        参数：
            name       : 对象唯一名称（None 时自动生成 {alias}:{uuid}）
            alias      : 可选别名，用于 search 查找
            search     : 若为 True，先在 _alias_index 中按 alias 查找已有实例
            _local_only : 若为 True，跳过全局注册和后端存储（用于临时/中间对象）
        """
        # search 模式：按 alias 查找已有实例
        if search and alias is not None:
            with cls._alias_index_lock:
                if alias in cls._alias_index:
                    for instance in cls._alias_index[alias].values():
                        if instance.__class__ is cls:
                            return instance

        # 若未指定 name，自动生成 {alias}:{uuid}
        if name is None:
            alias_part = alias if alias else cls.__name__
            name = f"{alias_part}:{uuid.uuid4().hex}"

        # _local_only：跳过全局缓存和后端存储
        if _local_only:
            return super().__new__(cls)

        # 第一层：本地弱引用缓存（同进程快速路径）
        with cls._instances_lock:
            if name in cls._instances:
                return cls._instances[name]

        # 第二层：后端原子创建（跨进程协调）
        backend = cls._ensure_backend()
        key = f"{cls.__name__}:{name}"
        backend.set_if_absent(key)

        # 无论是否创建成功，本进程都需要构造实例
        instance = super().__new__(cls)
        with cls._instances_lock:
            cls._instances[name] = instance
        instance.name = name
        instance.alias = alias if alias else name
        instance.desc = kwargs.pop('desc', '')
        return instance

    def __init__(self, name: Optional[str] = None, alias: Optional[str] = None,
                 desc: Optional[str] = None, search: bool = False,
                 _local_only: bool = False, *args, **kwargs):
        """仅在首次创建时初始化，防止复用已有实例时重复初始化。"""
        if not hasattr(self, '_initialized'):
            # self.name = name if name else f"{alias or self.__class__.__name__}:{uuid.uuid4().hex}"
            # self.alias = alias if alias else self.name
            # self.desc = desc if desc else self.__doc__[:80].strip() if self.__doc__ else ''
            self._initialized = True
            self._local_only = _local_only
            # 注册到 alias 索引（支持 search）；local_only 跳过
            if not _local_only:
                with self._alias_index_lock:
                    self._alias_index.setdefault(self.alias, WeakValueDictionary())[id(self)] = self

    def __reduce__(self):
        """pickle 序列化：仅保存 identity（类名 + name），反序列化时复用单例。"""
        return (self.__class__._reconstruct, (self.name,))

    @classmethod
    def _reconstruct(cls, name: str):
        """pickle 反序列化：通过 name 找回已有实例（单例缓存命中），或创建占位。"""
        # 尝试从缓存中找回已有实例
        with cls._instances_lock:
            existing = cls._instances.get(name)
        if existing is not None:
            return existing
        # 缓存中没有（新进程），创建占位实例（最小属性集）
        instance = cls.__new__(cls, name=name)
        instance.name = name
        instance.alias = name.split(':')[0] if ':' in name else name
        instance._initialized = True
        return instance

    def __str__(self):
        return self.name

    def __lt__(self, other):
        return self.name < other.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return self.name

    def delete(self):
        """从全局缓存和后端存储中移除该实例，使其可被垃圾回收。"""
        if getattr(self, '_local_only', False):
            return  # 本地临时对象，无需清理全局状态
        key = self.name
        cls = self.__class__
        backend_key = f"{cls.__name__}:{key}"
        with cls._instances_lock:
            cls._instances.pop(key, None)
        with cls._alias_index_lock:
            cls._alias_index.get(self.alias, {}).pop(id(self), None)
        try:
            backend = UniqueObject._backend
            if backend is not None:
                backend.delete(backend_key)
        except Exception:
            pass