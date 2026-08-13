"""Federation errors and immutable service-route contracts."""

from __future__ import annotations

from dataclasses import dataclass

class FederationError(RuntimeError):
    """Base class for federation failures."""


class TargetUnavailable(FederationError):
    """A registered target is offline or cannot be reached."""


class TargetNotFound(FederationError):
    """No registered target matches the requested selector."""


@dataclass(frozen=True, slots=True)
class ServiceRoute:
    """One routable FactorTester service endpoint."""

    server_id: str
    role: str
    branch: str
    revision: str
    port: int
    features: tuple[str, ...] = ()
    endpoint: str = ""
    peer_control_endpoint: str = ""
    peer_data_endpoint: str = ""
    proxy_token: str = ""
    remote: bool = False
    online: bool = True
    load: float = 0.0
    active_jobs: int = 0
    queue_depth: int = 0
    latency_ms: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "server_id": self.server_id,
            "role": self.role,
            "branch": self.branch,
            "revision": self.revision,
            "port": self.port,
            "features": list(self.features),
            "endpoint": self.endpoint,
            "remote": self.remote,
            "online": self.online,
            "load": self.load,
            "active_jobs": self.active_jobs,
            "queue_depth": self.queue_depth,
            "latency_ms": self.latency_ms,
        }

