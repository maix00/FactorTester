"""Compatibility contract for the semantic federation package split."""

from server.manager.domain import federation
from server.manager.domain.federation.announcer import FederationAnnouncer
from server.manager.domain.federation.config import FederationConfigStore
from server.manager.domain.federation.gateway import FederatedGateway
from server.manager.domain.federation.models import ServiceRoute
from server.manager.domain.federation.registry import FederatedServerRegistry
from server.manager.domain.federation.sync import FederationSyncWorker


def test_federation_package_preserves_public_domain_exports() -> None:
    assert federation.FederationAnnouncer is FederationAnnouncer
    assert federation.FederationConfigStore is FederationConfigStore
    assert federation.FederatedGateway is FederatedGateway
    assert federation.FederatedServerRegistry is FederatedServerRegistry
    assert federation.FederationSyncWorker is FederationSyncWorker
    assert federation.ServiceRoute is ServiceRoute
