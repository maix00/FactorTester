"""Compatibility contract for the semantic federation package split."""

from server.manager.domain import federation
from server.manager.domain.federation.announcer import FederationAnnouncer
from server.manager.domain.federation.config import FederationConfigStore
from server.manager.domain.federation.directory import FederationNodeDirectory
from server.manager.domain.federation.gateway import FederatedGateway
from server.manager.domain.federation.models import ServiceRoute
from server.manager.domain.federation.registry import FederatedServerRegistry
from server.manager.domain.federation.sync import FederationSyncWorker
from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.http.federation.capabilities import (
    FederationCapabilityRoutesMixin,
)
from server.manager.http.federation.jobs import FederationJobRoutesMixin
from server.manager.http.federation.registration import (
    FederationRegistrationRoutesMixin,
)
from server.manager.http.federation.service_proxy import (
    FederationServiceProxyRoutesMixin,
)
from server.manager.http.federation.sync import FederationSyncRoutesMixin
from server.manager.http.federation_routes import FederationRoutesMixin
from server.manager.state.federation_membership import (
    FederationMembershipStateMixin,
)
from server.manager.state.federation_settings import FederationSettingsStateMixin
from server.manager.state.routing import RoutingStateMixin


def test_federation_package_preserves_public_domain_exports() -> None:
    assert federation.FederationAnnouncer is FederationAnnouncer
    assert federation.FederationConfigStore is FederationConfigStore
    assert federation.FederationNodeDirectory is FederationNodeDirectory
    assert federation.FederatedGateway is FederatedGateway
    assert federation.FederatedServerRegistry is FederatedServerRegistry
    assert federation.FederationSyncWorker is FederationSyncWorker
    assert federation.ServiceRoute is ServiceRoute


def test_federation_http_facade_composes_semantic_route_modules() -> None:
    assert issubclass(FederationRoutesMixin, FederationRegistrationRoutesMixin)
    assert issubclass(FederationRoutesMixin, FederationSyncRoutesMixin)
    assert issubclass(FederationRoutesMixin, FederationJobRoutesMixin)
    assert issubclass(FederationRoutesMixin, FederationServiceProxyRoutesMixin)
    assert issubclass(FederationRoutesMixin, FederationCapabilityRoutesMixin)
    assert issubclass(FederationRoutesMixin, FederationAdminRoutesMixin)


def test_manager_state_domains_keep_membership_out_of_route_selection() -> None:
    assert "accept_federation_catalog" in FederationMembershipStateMixin.__dict__
    assert "update_federation_config" in FederationSettingsStateMixin.__dict__
    assert "accept_federation_catalog" not in RoutingStateMixin.__dict__
