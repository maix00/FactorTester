"""Bounded concurrent reads for peer capability catalogs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Iterable
from typing import Any

from .models import ServiceRoute


def load_peer_capability_snapshots(
    routes: Iterable[ServiceRoute],
    loader: Callable[[ServiceRoute], dict[str, Any] | None],
    *,
    max_workers: int = 8,
) -> dict[str, dict[str, Any] | None]:
    """Load one snapshot per server concurrently without failing the catalog."""
    selected = list(routes)
    if not selected:
        return {}
    results: dict[str, dict[str, Any] | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(selected), max_workers)) as pool:
        futures = {pool.submit(loader, route): route for route in selected}
        for future in as_completed(futures):
            route = futures[future]
            try:
                value = future.result()
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                value = None
            results[route.server_id] = value
    return results
