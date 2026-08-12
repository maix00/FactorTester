"""Category-partitioned cross-sectional transformations."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def eligibility_mask(mask: Any, template: pd.DataFrame) -> pd.DataFrame:
    if isinstance(mask, pd.DataFrame):
        aligned = mask.reindex(index=template.index, columns=template.columns)
    elif isinstance(mask, pd.Series):
        aligned = pd.DataFrame(
            np.broadcast_to(mask.reindex(template.index).to_numpy()[:, None], template.shape),
            index=template.index, columns=template.columns,
        )
    else:
        aligned = pd.DataFrame(bool(mask), index=template.index, columns=template.columns)
    return aligned.fillna(False).astype(bool)


def ordinal_rank(x: pd.DataFrame, mask: Any, *, ascending: bool) -> pd.DataFrame:
    eligible = x.where(eligibility_mask(mask, x))
    columns = sorted(eligible.columns, key=str)
    return eligible.loc[:, columns].rank(axis=1, method="first", ascending=ascending, na_option="keep").reindex(columns=x.columns)


def zscore(x: pd.DataFrame) -> pd.DataFrame:
    mean = x.mean(axis=1)
    std = x.std(axis=1)
    result = x.sub(mean, axis=0).div(std.replace(0, np.nan), axis=0)
    constant_rows = std.eq(0)
    if constant_rows.any():
        values = x.loc[constant_rows]
        result.loc[constant_rows] = values.where(values.isna(), 0.0)
    return result


def apply_group_transform(op: str, x: pd.DataFrame, mask: Any, category: Any) -> pd.DataFrame:
    eligible = eligibility_mask(mask, x)
    result = pd.DataFrame(np.nan, index=x.index, columns=x.columns, dtype=float)
    for label in category.categories:
        members = pd.Series(
            [category.is_in_category(label, product) for product in x.columns],
            index=x.columns, dtype=bool,
        )
        grouped = x.where(eligible & members)
        if op == "cs_group_rank":
            transformed = grouped.rank(axis=1, pct=True) - 0.5
        elif op == "cs_group_zscore":
            transformed = zscore(grouped)
        elif op == "cs_group_demean":
            transformed = grouped.sub(grouped.mean(axis=1), axis=0)
        else:
            raise ValueError(f"Unknown group cross-sectional op: {op}")
        result.loc[:, members] = transformed.loc[:, members]
    return result
