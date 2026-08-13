"""Disjoint public and WireGuard-only routes for transfer data services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class DataPlaneSurface(StrEnum):
    CLIENT = "client"
    PEER = "peer"


_TRANSFER_PATH = re.compile(
    r"^/v1/transfers/([A-Za-z0-9._-]{1,128})/"
    r"(download|upload|origin|destination)$"
)


@dataclass(frozen=True, slots=True)
class DataPlaneRoute:
    attempt_id: str
    action: str


def match_transfer_route(
    path: str,
    *,
    surface: DataPlaneSurface,
) -> DataPlaneRoute | None:
    match = _TRANSFER_PATH.fullmatch(urlparse(path).path)
    if match is None:
        return None
    action = match.group(2)
    allowed = {
        DataPlaneSurface.CLIENT: {"download", "upload"},
        DataPlaneSurface.PEER: {"origin", "destination"},
    }[surface]
    if action not in allowed:
        return None
    return DataPlaneRoute(attempt_id=match.group(1), action=action)


def method_allowed(action: str, method: str) -> bool:
    allowed = {
        "download": {"GET", "HEAD"},
        "origin": {"GET", "HEAD"},
        "upload": {"PUT"},
        "destination": {"PUT"},
    }
    return method in allowed.get(action, set())
