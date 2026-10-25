"""Keycloak identity boundary: realm users, nested groups, organizations.

The HTTP adapter is intentionally thin; business code depends on this
interface so a fake adapter can drive permission tests without Keycloak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Identity:
    username: str
    groups: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    attributes: dict[str, tuple[str, ...]] = field(default_factory=dict)


class KeycloakAdapter(Protocol):
    def user(self, username: str) -> Identity | None: ...
    def group_members(self, group_path: str) -> list[Identity]: ...
    def organization_members(self, organization: str) -> list[Identity]: ...


class InMemoryKeycloak:
    """Deterministic adapter used by tests and migration dry-runs."""

    def __init__(self, users: list[Identity] | None = None) -> None:
        self._users = {user.username: user for user in users or []}

    def user(self, username: str) -> Identity | None:
        return self._users.get(username)

    def group_members(self, group_path: str) -> list[Identity]:
        path = group_path.strip("/")
        return [
            user for user in self._users.values()
            if any(group.strip("/") == path or group.strip("/").startswith(path + "/")
                   for group in user.groups)
        ]

    def organization_members(self, organization: str) -> list[Identity]:
        return [
            user for user in self._users.values()
            if organization in user.organizations
        ]


def user_subject(username: str) -> str:
    return f"user:{username}"


def group_subject(path: str) -> str:
    return f"group:{path.strip('/')}"


def organization_subject(name: str) -> str:
    return f"org:{name.strip()}"
