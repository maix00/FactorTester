"""Bundle provider for product time-series data sources."""

from __future__ import annotations

from typing import Any, Callable

from tools.data.types.time_freq import DataFreq

from .DataProviderProductTS import DataProviderProductTS


class DataProviderProductTSBundle(DataProviderProductTS):
    """A user-facing bundle that resolves to concrete product time-series sources.

    Bundles are selectable like data sources, but they do not read files
    directly.  For a given product/frequency pair they choose the first concrete
    member that can serve the request.
    """

    def __init__(
        self,
        key: str,
        *,
        members: Callable[[], tuple[Any, ...]] | tuple[Any, ...],
        label: str | None = None,
    ) -> None:
        self._members = members
        super().__init__(
            key=key,
            data_freq="0",
            get_object_path=lambda _object: "",
            if_object_is_in_source=lambda _object: False,
            label=label or key,
        )

    @property
    def members(self) -> tuple[Any, ...]:
        if callable(self._members):
            return tuple(self._members())
        return tuple(self._members)

    def resolve_for_product(self, product: Any, freq: Any) -> Any | None:
        target_freq = DataFreq(freq)
        for source in self.members:
            if DataFreq(getattr(source, "freq", None)) == target_freq and product in source:
                return source
        return None

    def __contains__(self, obj: Any) -> bool:
        return False

    def supports_product(self, obj: Any) -> bool:
        for member in self.members:
            checker = getattr(member, "supports_product", None)
            if bool(checker(obj) if callable(checker) else obj in member):
                return True
        return False
