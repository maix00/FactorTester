"""Public federation domain facade.

The package keeps the historical import surface while each responsibility
lives in a focused module.
"""

from .announcer import FederationAnnouncer
from .config import FEDERATION_CONFIG_SCHEMA_VERSION, FederationConfigStore
from .directory import FederationNodeDirectory
from .gateway import MAX_ENVELOPE_BYTES, FederatedGateway
from .models import (
    FederationError,
    ServiceRoute,
    TargetNotFound,
    TargetUnavailable,
)
from .registry import (
    DEFAULT_LEASE_SECONDS,
    REGISTRY_SCHEMA_VERSION,
    FederatedServerRegistry,
)
from .sync import FederationSyncWorker

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "FEDERATION_CONFIG_SCHEMA_VERSION",
    "MAX_ENVELOPE_BYTES",
    "REGISTRY_SCHEMA_VERSION",
    "FederatedGateway",
    "FederatedServerRegistry",
    "FederationAnnouncer",
    "FederationConfigStore",
    "FederationNodeDirectory",
    "FederationError",
    "FederationSyncWorker",
    "ServiceRoute",
    "TargetNotFound",
    "TargetUnavailable",
]
