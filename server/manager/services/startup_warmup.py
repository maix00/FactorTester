"""Build the projections a first visitor would otherwise pay for.

After a deploy or a restart every per-account projection is cold: the shared
research list (federated), the report catalog scope and the factor library
overview each take hundreds of milliseconds to build, so the first visitor of
every account pays that cost.  The manager builds them once in a background
thread after the listener is up.  A failure is reported and never affects
startup or any later request.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

DEFAULT_DELAY_SECONDS = 1.5


def _enabled() -> bool:
    raw = str(os.environ.get("FACTORTESTER_STARTUP_WARMUP") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def principal_refs() -> list[str]:
    """Every account whose projections are worth warming."""
    try:
        from tools.data.account_manage import load_accounts

        accounts = load_accounts() or []
    except Exception:
        return []
    values: list[str] = []
    for account in accounts:
        username = str((account or {}).get("username") or "").strip()
        if username and username not in values:
            values.append(username)
    return values


def _timed(label: str, action: Callable[[], Any], log: Callable[[str], None]) -> float:
    started = time.perf_counter()
    try:
        action()
    except Exception as exc:
        log(f"startup warmup {label} failed: {exc}")
        return -1.0
    return time.perf_counter() - started


def _first_service(candidates: list[Any], method: str) -> Any:
    for candidate in candidates:
        if callable(getattr(candidate, method, None)):
            return candidate
    return None


def warm_caches(
    state: Any,
    *,
    principals: list[str] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    """Build the cold projections once; return per-step durations in seconds."""
    research = _first_service(
        [getattr(state, "federated_public_data", None),
         getattr(state, "public_research", None)],
        "list_visible",
    )
    catalog = _first_service(
        [getattr(state, "research_catalog", None)], "list_reports_for_scope",
    )
    # The factor catalog follows the same reader the catalog route picks.
    factors = _first_service(
        [getattr(state, "federated_public_data", None),
         getattr(state, "client_state", None)],
        "factor_library",
    )
    viewers: list[str | None] = [None]
    for principal in principals if principals is not None else principal_refs():
        name = str(principal or "").strip()
        if name and name not in viewers:
            viewers.append(name)
    timings: dict[str, float] = {}
    for viewer in viewers:
        label = viewer or "visitor"
        if research is not None:
            timings[f"research:{label}"] = _timed(
                f"research:{label}",
                lambda: research.list_visible(viewer),
                log,
            )
        if catalog is not None:
            timings[f"catalog:{label}"] = _timed(
                f"catalog:{label}",
                lambda: catalog.list_reports_for_scope(viewer=viewer, scope="all"),
                log,
            )
        if factors is not None and viewer:
            timings[f"factors:{viewer}"] = _timed(
                f"factors:{viewer}",
                lambda: factors.factor_library(viewer),
                log,
            )
    return timings


def start_warmup(
    state: Any,
    *,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    log: Callable[[str], None] = print,
) -> threading.Thread | None:
    """Warm in one daemon thread so the listener answers immediately."""
    if not _enabled():
        log("startup warmup disabled by environment")
        return None

    def run() -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            timings = warm_caches(state, log=log)
        except Exception as exc:  # never let warmup break the listener
            log(f"startup warmup failed: {exc}")
            return
        detail = ", ".join(
            f"{key}={'failed' if value < 0 else f'{value * 1000:.0f}ms'}"
            for key, value in timings.items()
        )
        log(f"startup warmup: {detail}")

    thread = threading.Thread(target=run, name="startup-warmup", daemon=True)
    thread.start()
    return thread


__all__ = ["principal_refs", "start_warmup", "warm_caches"]
