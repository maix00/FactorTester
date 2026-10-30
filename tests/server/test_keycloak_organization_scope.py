from __future__ import annotations

import pytest

from server.manager.domain.organization_scope import (
    configured_managed_organizations,
)


@pytest.mark.parametrize("public_server,server_role", [(False, "feat"), (True, "main")])
def test_unconfigured_manager_has_no_synthetic_organization(
    public_server: bool, server_role: str,
) -> None:
    assert configured_managed_organizations(
        public_server=public_server,
        server_role=server_role,
        environment={},
    ) == ()


def test_manager_organization_scope_uses_only_explicit_deployment_ids() -> None:
    assert configured_managed_organizations(
        public_server=True,
        server_role="main",
        environment={"FACTORTESTER_MANAGED_ORGANIZATIONS": "org-a,org-b,org-a"},
    ) == ("org-a", "org-b")


