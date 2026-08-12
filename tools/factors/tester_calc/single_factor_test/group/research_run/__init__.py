"""Page-independent preparation and execution of grouped research runs."""

from .execution import execute_group_run_spec
from .preparation import prepare_group_run_spec


__all__ = ["execute_group_run_spec", "prepare_group_run_spec"]
