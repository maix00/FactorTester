"""Compatibility facade for authenticated federation HTTP routes."""

from __future__ import annotations

from server.manager.http.federation.admin import FederationAdminRoutesMixin
from server.manager.http.federation.capabilities import (
    FederationCapabilityRoutesMixin,
)
from server.manager.http.federation.jobs import FederationJobRoutesMixin
from server.manager.http.federation.public_data import (
    FederationPublicDataRoutesMixin,
)
from server.manager.http.federation.registration import (
    FederationRegistrationRoutesMixin,
)
from server.manager.http.federation.service_proxy import (
    FederationServiceProxyRoutesMixin,
)
from server.manager.http.federation.sync import FederationSyncRoutesMixin


class FederationRoutesMixin(
    FederationRegistrationRoutesMixin,
    FederationSyncRoutesMixin,
    FederationJobRoutesMixin,
    FederationPublicDataRoutesMixin,
    FederationServiceProxyRoutesMixin,
    FederationCapabilityRoutesMixin,
    FederationAdminRoutesMixin,
):
    """Compose the stable federation route surface from focused adapters."""
