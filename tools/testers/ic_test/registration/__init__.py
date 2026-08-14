"""Semantic registration slices for the IC authoring manifest."""

from .analysis_fields import register_analysis_fields
from .core_fields import register_core_fields
from .results import register_result_contracts
from .shell import register_authoring_shell

__all__ = [
    "register_analysis_fields",
    "register_authoring_shell",
    "register_core_fields",
    "register_result_contracts",
]
