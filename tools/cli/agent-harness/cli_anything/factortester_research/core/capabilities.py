"""Stable public facade for capability contracts and node-local resolution."""

from .capability_predicates import evaluate_capability_predicate
from .capability_registry import (
    capability_descriptor,
    load_builtin_capability_registry,
    validate_capability_registry,
)
from .capability_resolution import resolve_graph_capabilities

__all__ = [
    "capability_descriptor",
    "evaluate_capability_predicate",
    "load_builtin_capability_registry",
    "resolve_graph_capabilities",
    "validate_capability_registry",
]
