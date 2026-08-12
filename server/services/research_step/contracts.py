"""Public facade for compact, ephemeral Research Step contracts."""

from .inspect import build_inspect_contract
from .prepare import build_prepare_contract
from tools.cli.protocols.research_step import validate_prepare_contract

__all__ = [
    "build_inspect_contract",
    "build_prepare_contract",
    "validate_prepare_contract",
]
