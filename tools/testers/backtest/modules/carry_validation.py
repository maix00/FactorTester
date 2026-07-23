from __future__ import annotations


def validate_carry_config(
    *,
    near_rank: int,
    far_rank: int,
    entry: float,
    exit_at: float,
    gross: float,
) -> None:
    if near_rank < 0 or far_rank <= near_rank:
        raise ValueError(
            "carry contract ranks require 0 <= near_rank < far_rank"
        )
    if entry <= 0 or exit_at < 0 or exit_at >= entry:
        raise ValueError(
            "carry thresholds require 0 <= exit_threshold < entry_threshold"
        )
    if gross <= 0 or gross > 1:
        raise ValueError("carry gross_weight must be in (0, 1]")
