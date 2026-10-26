"""Parameters owned by the public factor API (no FactorTester dependency)."""

from __future__ import annotations

from typing import Any


class Parameter:
    def __init__(self, alias: str, default_value: Any = None, typ: Any = None):
        self.alias = str(alias)
        self.default_value = default_value
        self.typ = typ

    @property
    def value(self) -> Any:
        return self.default_value


class TypeParam(Parameter):
    def __init__(self, alias: str, default_value: Any = None,
                 typ: type | tuple[type, ...] | None = None):
        super().__init__(alias, default_value, typ or type(default_value))


class FactorParam(Parameter):
    pass
