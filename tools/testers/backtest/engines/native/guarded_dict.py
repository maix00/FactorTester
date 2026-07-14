"""Small guarded mapping used by flow-contract audit stores."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any


class GuardedDict(dict):
    """A dict that rejects direct mutation while store guards are enabled.

    Domain stores should mutate it through their named setter/publish methods,
    wrapping those mutations in ``unguarded_write()``.  This keeps step-mode
    contract audit from being bypassed by direct ``store.some_dict[key] = ...``.
    """

    def __init__(self, *args: Any, label: str = "guarded dict", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._guard_label = label
        self._guarded_writes_enabled = False
        self._guarded_write_depth = 0

    def set_guarded_writes_enabled(self, enabled: bool) -> None:
        self._guarded_writes_enabled = bool(enabled)

    @contextmanager
    def unguarded_write(self):
        self._guarded_write_depth += 1
        try:
            yield
        finally:
            self._guarded_write_depth -= 1

    def _check_write(self) -> None:
        if self._guarded_writes_enabled and self._guarded_write_depth <= 0:
            raise RuntimeError(
                f"{self._guard_label} is guarded during step/audit runs; "
                "write through the store's named setter/publish method so the "
                "flow-contract audit can record the declared output field."
            )

    def __setitem__(self, key: Any, value: Any) -> None:
        self._check_write()
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        self._check_write()
        super().__delitem__(key)

    def clear(self) -> None:
        self._check_write()
        super().clear()

    def pop(self, key: Any, default: Any = None) -> Any:
        self._check_write()
        if default is None:
            return super().pop(key)
        return super().pop(key, default)

    def popitem(self) -> tuple[Any, Any]:
        self._check_write()
        return super().popitem()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        self._check_write()
        return super().setdefault(key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._check_write()
        super().update(*args, **kwargs)
