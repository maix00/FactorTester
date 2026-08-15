"""Offline-first synchronization for Manager-owned account-domain metadata."""

__all__ = ["AccountDomainSyncService"]


def __getattr__(name: str):
    if name == "AccountDomainSyncService":
        from .service import AccountDomainSyncService

        return AccountDomainSyncService
    raise AttributeError(name)
