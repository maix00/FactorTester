from __future__ import annotations

import pytest

from server.services.agent_flow import authorization


def test_local_research_authority_requires_no_account_lookup(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: pytest.fail("ordinary path queried account store"),
    )

    authorization.require_execution_authority(
        username="alice",
        actor_role="researcher",
        authority_scope="local_research",
    )


@pytest.mark.parametrize(
    ("actor_role", "authority_scope"),
    [
        ("researcher", "server_backend_code"),
        ("backend_verifier", "server_backend_code"),
        ("implementation_agent", "server_backend_code"),
    ],
)
def test_backend_authority_rejects_ordinary_account(
    monkeypatch,
    actor_role: str,
    authority_scope: str,
) -> None:
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "alice", "role": "user"},
    )

    with pytest.raises(PermissionError, match="developer account"):
        authorization.require_execution_authority(
            username="alice",
            actor_role=actor_role,
            authority_scope=authority_scope,
        )


def test_backend_authority_accepts_keycloak_developer_role(monkeypatch) -> None:
    from flask import Flask, g

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "dev", "role": "developer"},
    )

    app = Flask(__name__)
    with app.test_request_context("/"):
        g.keycloak_user_session = {
            "username": "dev", "keycloak_roles": ("factor:develop",),
        }
        authorization.require_execution_authority(
            username="dev",
            actor_role="backend_verifier",
            authority_scope="server_backend_code",
        )
        authorization.require_resume_role(
            username="dev",
            role="server_maintenance",
        )


def test_backend_authority_rejects_stale_local_developer_role(monkeypatch) -> None:
    from flask import Flask, g

    monkeypatch.setenv("TRADERESEARCH_AUTH_MODE", "keycloak")
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "dev", "role": "developer"},
    )
    app = Flask(__name__)
    with app.test_request_context("/"):
        g.keycloak_user_session = {"username": "dev", "keycloak_roles": ()}
        with pytest.raises(PermissionError, match="developer account"):
            authorization.require_execution_authority(
                username="dev",
                actor_role="backend_verifier",
                authority_scope="server_backend_code",
            )


def test_maintenance_resume_rejects_ordinary_account(monkeypatch) -> None:
    monkeypatch.setattr(
        authorization,
        "get_account",
        lambda _username: {"username": "alice", "role": "user"},
    )

    with pytest.raises(PermissionError, match="developer account"):
        authorization.require_resume_role(
            username="alice",
            role="server_maintenance",
        )
