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
        orgs = self._organizations_for_user(user_id, str(raw.get("username") or ""))
        return self._identity(raw, groups, orgs)

    def _post(self, path: str, payload: Any) -> tuple[int, str]:
        import json
        import urllib.request

        request = urllib.request.Request(
            f"{self.base_url}/admin/realms/{self.realm}/{path.lstrip('/')}",
            data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise ValueError("Keycloak user already exists") from exc
            raise

    def create_user(self, *, username: str, email: str = "", groups: tuple[str, ...] = (),
                    attributes: dict[str, tuple[str, ...]] | None = None) -> str:
        import urllib.request

        body = {
            "username": username, "enabled": True,
            "email": email or f"{username}@invalid.local",
            "requiredActions": ["UPDATE_PASSWORD"],
            "attributes": {key: list(value) for key, value in (attributes or {}).items()},
        }
        status, location = self._post("users", body)
        if status not in {201, 204}:
            raise RuntimeError(f"user create failed: {status}")
        user_id = location.rstrip("/").rsplit("/", 1)[-1]
        for group in groups:
            target = next(
                (item for item in self._all_groups()
                 if str(item.get("path") or "") == group),
                None,
            )
            if target is None:
                raise ValueError(f"group not found: {group}")
            request = urllib.request.Request(
                f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}/groups/{target['id']}",
                data=b"{}", method="PUT",
                headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
            )
            urllib.request.urlopen(request, timeout=self.timeout).close()
        return user_id

    def _organizations_for_user(self, user_id: str, username: str) -> list[str]:
        """Keycloak 26 has no /users/{id}/organizations; scan org members."""
        try:
            organizations = self._get("organizations") or []
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 404}:
                return []
            raise
        names = []
        for organization in organizations:
            org_id = str(organization.get("id") or "")
            if not org_id:
                continue
            try:
                members = self._get(f"organizations/{org_id}/members") or []
            except urllib.error.HTTPError as exc:
                if exc.code in {403, 404}:
                    continue
                raise
            if any(str(item.get("username") or "") == username for item in members):
                names.append(str(organization.get("name") or organization.get("alias") or ""))
        return [name for name in names if name]

    def add_organization_member(self, organization: str, user_id: str) -> None:
        import json
        import urllib.request

        orgs = self._get("organizations") or []
        target = next((item for item in orgs if item.get("name") == organization), None)
        if target is None:
            raise ValueError(f"organization not found: {organization}")
        request = urllib.request.Request(
            f"{self.base_url}/admin/realms/{self.realm}/organizations/{target['id']}/members",
            data=json.dumps(str(user_id)).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status not in {201, 204}:
                raise RuntimeError(f"organization member add failed: {response.status}")

    def _all_groups(self, parent: str = "") -> list[dict]:
        path = f"groups/{parent}/children" if parent else "groups"
        rows = self._get(path) or []
        result = []
        for item in rows:
            result.append(item)
            result.extend(self._all_groups(str(item.get("id") or "")))
        return result

    def group_members(self, group_path: str) -> list[Identity]:
        target = next(
            (item for item in self._all_groups()
             if str(item.get("path") or "") == group_path),
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


def oidc_authorization_url(
    *, base_url: str, realm: str, client_id: str, redirect_uri: str,
    state: str, scope: str = "openid profile email",
) -> str:
    """Build the browser authorization-code URL for a Keycloak realm."""
    import urllib.parse

    query = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return (
        f"{base_url.rstrip('/')}/realms/{realm.strip('/')}"
        f"/protocol/openid-connect/auth?{query}"
    )


class OIDCClient:
    """Authorization-code token exchange for browser/Swift sessions."""

    def __init__(self, base_url: str, realm: str, client_id: str,
                 *, client_secret: str = "", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm.strip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

    def _token(self, form: dict[str, str]) -> dict:
        import json
        import urllib.parse
        import urllib.request

        if self.client_secret:
            form = {**form, "client_secret": self.client_secret}
        request = urllib.request.Request(
            f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def exchange_code(self, code: str, redirect_uri: str, *,
                      code_verifier: str = "") -> dict:
        form = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": self.client_id,
        }
        if code_verifier:
            form["code_verifier"] = code_verifier
        return self._token(form)

    def refresh(self, refresh_token: str) -> dict:
        return self._token({
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": self.client_id,
        })


def oidc_userinfo(*, base_url: str, realm: str, access_token: str,
                  timeout: float = 10.0) -> dict:
    import json
    import urllib.request

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/realms/{realm.strip('/')}/protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())
