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


def permission_subjects(identity: Identity) -> tuple[str, ...]:
    """Subjects checked by PermissionStore, most specific first."""
    return (
        user_subject(identity.username),
        *(group_subject(path) for path in identity.groups),
        *(organization_subject(name) for name in identity.organizations),
    )


class KeycloakAdminAdapter:
    """Thin Keycloak Admin REST adapter; network calls are injectable."""

    def __init__(
        self, base_url: str, realm: str, *, client_id: str = "admin-cli",
        client_secret: str = "", username: str = "", password: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm.strip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token_value = ""

    def _token(self) -> str:
        if self._token_value:
            return self._token_value
        import json
        import urllib.parse
        import urllib.request

        form = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        request = urllib.request.Request(
            f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data=urllib.parse.urlencode(form).encode(), method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            self._token_value = str(json.loads(response.read())["access_token"])
        return self._token_value

    def _get(self, path: str) -> object:
        import json
        import urllib.request

        request = urllib.request.Request(
            f"{self.base_url}/admin/realms/{self.realm}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self._token()}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def _identity(self, raw: dict, groups: list[str], orgs: list[str]) -> Identity:
        return Identity(
            username=str(raw.get("username") or ""),
            groups=tuple(groups),
            organizations=tuple(orgs),
            roles=tuple(raw.get("realmRoles") or ()),
            attributes={k: tuple(v) for k, v in (raw.get("attributes") or {}).items()},
        )

    def user(self, username: str) -> Identity | None:
        import urllib.parse

        query = urllib.parse.urlencode({"username": username, "exact": "true"})
        rows = self._get(f"users?{query}")
        if not isinstance(rows, list) or not rows:
            return None
        raw = rows[0]
        user_id = str(raw.get("id") or "")
        groups = []
        for group in self._get(f"users/{user_id}/groups") or []:
            path = str(group.get("path") or "")
            if path:
                groups.append(path)
        orgs = [
            str(item.get("name") or "")
            for item in (self._get(f"users/{user_id}/organizations") or [])
            if item.get("name")
        ]
        return self._identity(raw, groups, orgs)

    def group_members(self, group_path: str) -> list[Identity]:
        groups = self._get("groups")
        target = next(
            (item for item in groups if str(item.get("path") or "") == group_path),
            None,
        )
        if target is None:
            return []
        members = self._get(f"groups/{target['id']}/members") or []
        return [self._identity(item, [group_path], []) for item in members]

    def organization_members(self, organization: str) -> list[Identity]:
        orgs = self._get("organizations") or []
        target = next((item for item in orgs if item.get("name") == organization), None)
        if target is None:
            return []
        members = self._get(f"organizations/{target['id']}/members") or []
        return [self._identity(item, [], [organization]) for item in members]
