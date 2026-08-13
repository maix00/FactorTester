"""Shared federation payload builders for integration tests."""

from __future__ import annotations

def federation_registration(
    server_id: str,
    *,
    latency_ms: float,
    load: float,
    port: int = 8000,
    online: bool = True,
) -> dict[str, object]:
    return {
        "server_id": server_id,
        "role": "main",
        "branch": "main",
        "revision": "abc123",
        "endpoint": f"http://{server_id}:7998",
        "proxy_token": f"proxy-{server_id}",
        "latency_ms": latency_ms,
        "load": {"load": load, "active_jobs": 1, "queue_depth": 2},
        "ports": [{
            "port": port,
            "branch": "main",
            "online": online,
            "load": {"load": load, "active_jobs": 1, "queue_depth": 2},
        }],
    }
