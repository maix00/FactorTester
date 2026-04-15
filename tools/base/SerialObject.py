from typing import Dict, Optional
from weakref import WeakValueDictionary

from tools.base.UniqueObject import UniqueObject

class SerialObject(UniqueObject):
    _single_use_count = -1
    _instance_count_dict: Dict[str, int] = {}
    _serial_map_dict: Dict[str, WeakValueDictionary] = {}
    _type_alias_owners: Dict[str, type] = {}
    _type_alias: str = 'SO'

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

    def __new__(cls, type_alias: str, alias: Optional[str] = None, search: bool = False, single_use: bool = False, *args, **kwargs):

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
            name = f"{type_alias}@SU@{cls._single_use_count}"
        else:
            if type_alias in cls._instance_count_dict:
                cls._instance_count_dict[type_alias] += 1
            else:
                cls._instance_count_dict[type_alias] = 0
            name = f"{type_alias}@{cls._instance_count_dict[type_alias]}"
            name = name if alias is None else f"{name}:{alias}"
        instance = super().__new__(cls, name=name)
        return instance

    def __init__(self, type_alias: str, alias: Optional[str] = None, single_use: bool = False, *args, **kwargs):
        if not hasattr(self, '_initialized'):
            if single_use:
                name = f"{type_alias}@SU@{self._single_use_count}"
            else:
                self.serial_number = self._instance_count_dict[type_alias]
                name = f"{type_alias}@{self.serial_number}"
            self.alias = alias or name
            name = name if alias is None else f"{name}:{alias}"
            super().__init__(name=name)
            if not single_use:
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