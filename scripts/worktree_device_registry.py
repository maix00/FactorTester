"""Compatibility import path for the Manager device registry."""

from server.manager.domain.devices import (
    DEVICE_REGISTRY_SCHEMA_VERSION,
    DeviceChallengeStore,
    DeviceRegistry,
    DeviceRegistryError,
    normalise_device_id,
    normalise_public_key,
)

__all__ = [
    "DEVICE_REGISTRY_SCHEMA_VERSION",
    "DeviceChallengeStore",
    "DeviceRegistry",
    "DeviceRegistryError",
    "normalise_device_id",
    "normalise_public_key",
]
