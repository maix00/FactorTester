"""Route matching for native federated-transfer endpoints on port 7997."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


_TRANSFER_PATH = re.compile(
    r"^/v1/transfers/([A-Za-z0-9._-]{1,128})/"
    r"(origin|producer|consumer|destination|upload)$"
)


@dataclass(frozen=True, slots=True)
class DataPlaneRoute:
    attempt_id: str
    action: str


def match_transfer_route(path: str) -> DataPlaneRoute | None:
    match = _TRANSFER_PATH.fullmatch(urlparse(path).path)
    if match is None:
        return None
    return DataPlaneRoute(attempt_id=match.group(1), action=match.group(2))


def method_allowed(action: str, method: str) -> bool:
    allowed = {
        "origin": {"GET", "HEAD"},
        "consumer": {"GET", "HEAD"},
        "producer": {"PUT"},
        "destination": {"PUT"},
        "upload": {"PUT"},
    }
    return method in allowed.get(action, set())
