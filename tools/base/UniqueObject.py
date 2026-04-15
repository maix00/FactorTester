from abc import ABC
from typing import Any
from weakref import WeakValueDictionary

class UniqueObject(ABC):
    '''
        唯一对象基类：每个实例根据其 name 属性唯一标识，且同一类的实例之间 name 不重复。
        子类：SerialObject, Product, CNFutures, Factor, Parameter, DataSource, DataMeta 等。
    '''

    _instances = WeakValueDictionary()

    def __new__(cls, name: str, *args, **kwargs):
        key = (name, cls.__name__)
        if key in cls._instances:
            return cls._instances[key]
        
        instance = super().__new__(cls)
        cls._instances[key] = instance
        return instance
    
    def __init__(self, name: str, *args, **kwargs):
        # Only initialize if this is a new instance (not already initialized)
        if not hasattr(self, '_initialized'):
            self.name = name
            if not hasattr(self, 'alias'):
                self.alias = name
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
    
    def delete(self):
        key = (self.name, self.__class__.__name__)
        self._instances.pop(key, None)