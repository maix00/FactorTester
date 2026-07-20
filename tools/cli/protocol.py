"""Deterministic client/server protocol negotiation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


PROTOCOL_NAME = "factortester-remote-research"
CLIENT_PROTOCOL_MINIMUM = 1
CLIENT_PROTOCOL_CURRENT = 1


def negotiate_protocol(
    manifest: dict[str, Any],
    *,
    required_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    if manifest.get("schema_version") != 1:
        raise ValueError("服务器协议清单 schema_version 不受支持")
    protocol = manifest.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("name") != PROTOCOL_NAME:
        raise ValueError("服务器协议名称不受支持")

    server_current = _positive_int(protocol.get("current"), "server current")
    server_minimum_client = _positive_int(
        protocol.get("minimum_client"),
        "server minimum_client",
    )
    compatible = (
        CLIENT_PROTOCOL_CURRENT >= server_minimum_client
        and server_current >= CLIENT_PROTOCOL_MINIMUM
    )
    if not compatible:
        raise ValueError(
            "客户端与服务器协议不兼容："
            f"client={CLIENT_PROTOCOL_MINIMUM}..{CLIENT_PROTOCOL_CURRENT}, "
            f"server={server_minimum_client}..{server_current}"
        )

    available = _capability_versions(manifest.get("capabilities"))
    requested = tuple(dict.fromkeys(str(item) for item in required_capabilities))
    missing = [item for item in requested if item not in available]
    if missing:
        raise ValueError(f"服务器缺少所需能力: {', '.join(missing)}")
    selected = available if not requested else {
        item: available[item] for item in requested
    }
    return {
        "compatible": True,
        "client": {
            "minimum": CLIENT_PROTOCOL_MINIMUM,
            "current": CLIENT_PROTOCOL_CURRENT,
        },
        "server": {
            "minimum_client": server_minimum_client,
            "current": server_current,
        },
        "capabilities": selected,
        "missing_capabilities": [],
    }


def _capability_versions(value: Any) -> dict[str, int]:
    if not isinstance(value, list):
        raise ValueError("服务器协议清单 capabilities 格式错误")
    out: dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("服务器协议清单 capability 格式错误")
        capability_id = str(item.get("id") or "")
        if not capability_id or capability_id in out:
            raise ValueError("服务器协议清单 capability ID 无效或重复")
        out[capability_id] = _positive_int(
            item.get("version"),
            f"capability {capability_id}",
        )
    return out


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是正整数") from exc
    if parsed < 1:
        raise ValueError(f"{field} 必须是正整数")
    return parsed
