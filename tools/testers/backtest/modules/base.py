"""Re-exports the core field/module primitives. Real definitions live in
`tools.testers.backtest.engines.native.fields` — they had to move out of
this package because `modules/__init__.py` eagerly imports every concrete
module (fee.py, margin.py, ...), which would create a circular import the
moment any of those modules' `ExecutableModule.__init_subclass__` needs to
import `Flow` (flow.py needs FieldRef from here). Kept as a re-export so
existing `from .base import ExecutableModule` imports across the six
module files don't need to change.
"""

from tools.testers.backtest.engines.native.fields import (
    ExecutableModule,
    FieldDefinition,
    FieldRef,
    as_module_node,
)

__all__ = ["ExecutableModule", "FieldDefinition", "FieldRef", "as_module_node"]
