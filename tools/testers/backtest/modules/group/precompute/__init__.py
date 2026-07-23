"""Group intent precompute adapters."""

from .apply import apply_precomputed_target_intents
from .coordinator import precompute_group_target_intents

__all__ = ["apply_precomputed_target_intents", "precompute_group_target_intents"]
