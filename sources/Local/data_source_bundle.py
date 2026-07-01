"""Local market-data bundle definitions.

The backtest layer should not know which concrete local providers currently
exist.  It asks this source-owned helper to expand a user-facing bundle such as
``Local`` into concrete ``DataProviderProductTS`` providers.
"""

from __future__ import annotations

from typing import Any

from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.providers.DataProviderProductTSBundle import DataProviderProductTSBundle


def _local_members() -> tuple[Any, ...]:
    return tuple(
        source for source in DataProviderProductTS.all()
        if source is not LOCAL and str(getattr(source, "key", "")).startswith("Local")
    )


LOCAL = DataProviderProductTSBundle(
    key="Local",
    label="Local",
    members=_local_members,
)


def data_sources_for_bundle(key: str) -> tuple[Any, ...]:
    """Return concrete local data providers for a bundle key."""
    if key != "Local":
        return ()
    return LOCAL.members
