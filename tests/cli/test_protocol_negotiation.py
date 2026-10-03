from __future__ import annotations

import pytest

from tools.cli.protocol import (
    CLIENT_PROTOCOL_CURRENT,
    CLIENT_PROTOCOL_MINIMUM,
    negotiate_protocol,
)


def _manifest(*, current: int = 1, minimum_client: int = 1) -> dict:
    return {
        "schema_version": 1,
        "protocol": {
            "name": "factortester-remote-research",
            "current": current,
            "minimum_client": minimum_client,
        },
        "capabilities": [
            {"id": "auth.session", "version": 1},
            {"id": "research.run", "version": 1},
        ],
    }


def test_protocol_negotiation_returns_only_requested_capabilities() -> None:
    result = negotiate_protocol(
        _manifest(),
        required_capabilities=("research.run",),
    )

    assert result == {
        "compatible": True,
        "client": {
            "minimum": CLIENT_PROTOCOL_MINIMUM,
            "current": CLIENT_PROTOCOL_CURRENT,
        },
        "server": {"minimum_client": 1, "current": 1},
        "capabilities": {"research.run": 1},
        "missing_capabilities": [],
    }


def test_protocol_negotiation_rejects_incompatible_server() -> None:
    with pytest.raises(ValueError, match="协议不兼容"):
        negotiate_protocol(_manifest(current=3, minimum_client=2))


def test_protocol_negotiation_rejects_missing_required_capability() -> None:
    with pytest.raises(ValueError, match="缺少所需能力"):
        negotiate_protocol(
            _manifest(),
            required_capabilities=("research.report-branch",),
        )
