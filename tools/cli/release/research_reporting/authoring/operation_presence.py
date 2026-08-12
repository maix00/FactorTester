"""In-memory reservations layered over point lookups for one operation batch."""

from __future__ import annotations

from collections.abc import Callable


class OperationPresence:
    def __init__(
        self, *, component_exists: Callable[[str], bool],
        binding_exists: Callable[[str], bool], asset_exists: Callable[[str], bool],
    ) -> None:
        self._component_exists = component_exists
        self._binding_exists = binding_exists
        self._asset_exists = asset_exists
        self.components: set[str] = set()
        self.bindings: set[str] = set()
        self.assets: set[str] = set()

    def component(self, value: str) -> bool:
        return value in self.components or self._component_exists(value)

    def binding(self, value: str) -> bool:
        return value in self.bindings or self._binding_exists(value)

    def asset(self, value: str) -> bool:
        return value in self.assets or self._asset_exists(value)

    def add_component(self, value: str) -> None:
        self.components.add(value)

    def add_binding(self, value: str) -> None:
        self.bindings.add(value)

    def add_asset(self, value: str) -> None:
        self.assets.add(value)
