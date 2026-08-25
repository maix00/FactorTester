from __future__ import annotations

import threading
import uuid
from abc import ABC
from copy import deepcopy
from weakref import WeakValueDictionary

from .object_identity import identity_registry


class UniqueNameObject(ABC):
    """同 name 同实例的去重基类。"""

    name: str
    alias: str

    def __init_subclass__(cls, **kwargs):
        """每个子类独立实例池和锁。"""
        super().__init_subclass__(**kwargs)
        cls._instances = WeakValueDictionary()
        cls._instances_lock = threading.Lock()
        ref_prefix = cls.__dict__.get("ref_prefix", "")
        if ref_prefix:
            identity_registry.register_class(ref_prefix, cls)

    def __new__(
        cls,
        name: str | None = None,
        alias: str | None = None,
        frozen_identity: object | None = None,
        **kwargs,
    ):
        identity = None
        if frozen_identity is not None:
            identity = identity_registry.require(
                frozen_identity, expected_class=cls,
            )
            if name not in {None, "", identity["ref"]}:
                raise ValueError("name conflicts with frozen ref")
            if alias not in {None, "", identity["alias"]}:
                raise ValueError("alias conflicts with frozen alias")
            name = identity["ref"]
            alias = identity["alias"]
        key = name or (alias or cls.__name__) + ':' + uuid.uuid4().hex
        with cls._instances_lock:
            if key in cls._instances:
                instance = cls._instances[key]
                if identity is not None and getattr(
                    instance, "frozen_identity", identity,
                ) != identity:
                    raise ValueError("object_ref is bound to a different frozen identity")
                return instance
            instance = super().__new__(cls)
            cls._instances[key] = instance
        instance.name = key
        instance.alias = alias or key
        if identity is not None:
            instance.owner_ref = identity["owner_ref"]
            instance.frozen_identity = identity
        return instance

    def __init__(self, *args, **kwargs):
        del args, kwargs
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

    def serialize(self) -> dict:
        """Return the validated frozen record for a persisted object."""
        identity = getattr(self, "frozen_identity", None)
        if identity is None:
            raise ValueError("transient UniqueNameObject cannot be serialized")
        return deepcopy(identity_registry.require(identity, expected_class=type(self)))

    @classmethod
    def deserialize(cls, value: object, **kwargs):
        """Resolve the registered class and reuse the object identified by ref."""
        identity = identity_registry.require(value)
        object_class = identity_registry.class_for_ref(identity["ref"])
        if cls is not UniqueNameObject and not issubclass(object_class, cls):
            raise ValueError(
                f"frozen identity resolves to {object_class.__name__}, not {cls.__name__}"
            )
        return object_class.from_frozen_identity(identity, **kwargs)

    @classmethod
    def from_frozen_identity(cls, value: object, **kwargs):
        """Construct simple persisted classes; complex classes override hydration."""
        return cls(frozen_identity=identity_registry.require(
            value, expected_class=cls,
        ), **kwargs)

    @classmethod
    def get_all(cls) -> list[tuple[str, UniqueNameObject]]:
        """返回该子类所有已注册实例的 (name, instance) 列表。"""
        with cls._instances_lock:
            return list(cls._instances.items())
