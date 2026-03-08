from abc import ABC
from weakref import WeakValueDictionary
from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal
import pandas as pd

class UniqueObject(ABC):
    _instances = WeakValueDictionary()

    def __new__(cls, name: str, *args, **kwargs):
        # Create a unique key that includes the class type
        key = (name, cls.__name__)
        # Check if an instance with this name and class already exists
        if key in cls._instances:
            return cls._instances[key]
        
        # Create a new instance if it doesn't exist
        instance = super().__new__(cls)
        cls._instances[key] = instance
        return instance
    
    def __init__(self, name: str):
        # Only initialize if this is a new instance (not already initialized)
        if not hasattr(self, '_initialized'):
            self.name = name
            self._initialized = True

    def __reduce__(self):
        return (self.__class__, (self.name,))

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
    
    def get(self, attr_name: str) -> Any:
        if hasattr(self, attr_name):
            attr_value = getattr(self, attr_name)
            if attr_value is not None:
                return attr_value
            else:
                raise AttributeError(f"{self.__class__.__name__} has no attribute {attr_name}")
        else:
            raise AttributeError(f"{self.__class__.__name__} has no attribute {attr_name}")
        
    def set(self, **kwargs) -> None:
        for attr_name, value in kwargs.items():
            setattr(self, attr_name, value)
    
class SerialObject(UniqueObject):
    _instance_count: int = -1
    _serial_map: Dict[int, SerialObject] = {}
    _type_alias_owners: Dict[str, type] = {}

    @classmethod
    def _get_family_root(cls):
        if getattr(cls, '_override_family_root', False):
            return cls
        for base in cls.__mro__:
            if SerialObject in base.__bases__:
                return base
            if base is SerialObject:
                break
        return SerialObject

    def __new__(cls, type_alias: str, alias: Optional[str] = None, *args, **kwargs):

        if type_alias in cls._type_alias_owners:
            owner = cls._type_alias_owners[type_alias]
            if not issubclass(cls, owner):
                raise ValueError(f"type_alias '{type_alias}' is already used by {owner.__name__} family")
        else:
            cls._type_alias_owners[type_alias] = cls._get_family_root()

        cls._instance_count += 1
        name = f"{type_alias}@{cls._instance_count}"
        name = name if alias is None else f"{name}:{alias}"
        instance = super().__new__(cls, name=name)
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            self.serial_number = self._instance_count
            name = f"{type_alias}@{self.serial_number}"
            self.alias = alias or name
            name = name if alias is None else f"{name}:{alias}"
            super().__init__(name=name)
            self._set_serial_map(self.serial_number, self)

    @classmethod
    def _set_serial_map(cls, serial_number: int, instance: SerialObject):
        cls._serial_map[serial_number] = instance
    
    @classmethod
    def _get_by_serial(cls, serial_number: int) -> Optional[SerialObject]:
        return cls._serial_map.get(serial_number)
    
    def __class_getitem__(cls, key):
        if isinstance(key, int):
            item = cls._get_by_serial(key)
            if item is not None:
                return item
            else:
                raise KeyError(f"No instance with serial number {key} found in {cls.__name__} family")
        raise TypeError(f"Invalid key type: {type(key).__name__}. Expected int for serial number lookup.")
