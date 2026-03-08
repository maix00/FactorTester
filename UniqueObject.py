from abc import ABC
from weakref import WeakValueDictionary
from typing import Callable, List, Dict, Optional, Sequence, Set, Tuple, Any, Literal

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
    
class SerialObject(UniqueObject):
    _instance_count: int = -1
    _serial_map: Dict[int, SerialObject] = {}
    _used_type_aliases = WeakValueDictionary()

    def __new__(cls, type_alias: str, alias: Optional[str] = None, *args, **kwargs):
        cls._instance_count += 1
        name = type_alias + '@' + str(cls._instance_count)
        name = name if alias is None else name + ':' + alias
        instance = super().__new__(cls, name=name)
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            self.serial_number = self._instance_count
            name = type_alias + '@' + str(self.serial_number)
            self.alias = alias or name
            name = name if alias is None else name + ':' + alias
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
                raise KeyError
        raise TypeError