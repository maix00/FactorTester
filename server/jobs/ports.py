"""Small helpers for the user-visible FactorTester listener port."""

from __future__ import annotations

import os
from collections.abc import Mapping


def detect_port(environ: Mapping[str, str] | None = None) -> int:
    request_values = environ or {}
    for raw in (
        request_values.get("SERVER_PORT"),
        os.environ.get("FACTORTESTER_VIBE_PORT"),
        os.environ.get("GTHT_SERVER_PORT"),
        os.environ.get("PORT"),
    ):
        try:
            port = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535:
            return port
    return 0
