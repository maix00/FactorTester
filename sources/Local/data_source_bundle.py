"""Local market-data bundle definitions.

The backtest layer should not know which concrete local providers currently
exist.  It asks this source-owned helper to expand a user-facing bundle such as
``Local`` into concrete ``DataProviderProductTS`` providers.
"""

from __future__ import annotations

from typing import Any

from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.providers.DataProviderProductTSBundle import DataProviderProductTSBundle
from tools.data.source_catalog import (
    historical_source_declaration,
    register_data_source,
)


def _local_members() -> tuple[Any, ...]:
    from sources.registry import installed_bundles

    bundle = next(item for item in installed_bundles() if item.bundle_id == "Local")
    providers = {str(source.key): source for source in DataProviderProductTS.all()}
    keys = [member.id for member in bundle.members if member.kind == "market_data"]
    missing = set(keys) - providers.keys()
    if missing:
        raise ValueError(f"Bundle members not activated: {sorted(missing)}")
    return tuple(providers[key] for key in keys)


LOCAL = DataProviderProductTSBundle(
    key="Local",
    label="Local",
    members=_local_members,
)

LOCAL_CATALOG_SOURCE = historical_source_declaration(
    key="Local",
    label="服务器本地历史数据",
    providers=lambda: LOCAL.members,
)
register_data_source(LOCAL_CATALOG_SOURCE)


def data_sources_for_bundle(key: str) -> tuple[Any, ...]:
    """Return concrete local data providers for a bundle key."""
    if key != "Local":
        return ()
    return LOCAL.members
