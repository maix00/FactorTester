"""Parquet layout shared by China-futures minute-data writers."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


MINUTE_ROW_GROUP_SIZE = 50_000


def write_minute_parquet(frame: pd.DataFrame, path: str | Path) -> None:
    """Atomically write minute data with row groups that support row pruning."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    frame.to_parquet(
        temporary,
        index=False,
        row_group_size=MINUTE_ROW_GROUP_SIZE,
    )
    os.replace(temporary, target)
