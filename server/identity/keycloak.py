"""Keycloak identity boundary: realm users, nested groups, organizations.

The HTTP adapter is intentionally thin; business code depends on this
interface so a fake adapter can drive permission tests without Keycloak.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Identity:
    username: str
    groups: tuple[str, ...] = ()
    organizations: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    attributes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    subject: str = ""
    display_name: str = ""
    enabled: bool = True


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
        self._token_expires_at = 0.0

    def _token(self) -> str:
        import time
        if self._token_value and self._token_expires_at > time.monotonic() + 30:
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
            payload = json.loads(response.read())
        self._token_value = str(payload["access_token"])
        self._token_expires_at = time.monotonic() + max(
            30, int(payload.get("expires_in") or 60),
        )
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
        display_name = " ".join(
            part for part in (str(raw.get("firstName") or "").strip(),
                              str(raw.get("lastName") or "").strip())
            if part
        )
        return Identity(
            username=str(raw.get("username") or ""),
            groups=tuple(groups),
            organizations=tuple(orgs),
            roles=tuple(raw.get("realmRoles") or ()),
            attributes={k: tuple(v) for k, v in (raw.get("attributes") or {}).items()},
            subject=str(raw.get("id") or ""),
            display_name=display_name or str(raw.get("username") or ""),
            enabled=raw.get("enabled") is True,
        )

    def user(self, username: str) -> Identity | None:
        raw = self.user_representation(username)
        if raw is None:
            return None
        user_id = str(raw.get("id") or "")
        groups = []
        for group in self._get(f"users/{user_id}/groups") or []:
            path = str(group.get("path") or "")
            if path:
                groups.append(path)
        orgs = self._organizations_for_user(user_id, str(raw.get("username") or ""))
        return self._identity(raw, groups, orgs)

    def user_representation(self, username: str) -> dict[str, Any] | None:
        """Return one exact Keycloak user representation without directory fan-out."""
        import urllib.parse

        query = urllib.parse.urlencode({"username": username, "exact": "true"})
        rows = self._get(f"users?{query}")
        if not isinstance(rows, list):
            raise RuntimeError("Keycloak user lookup returned an invalid result")
        matches = [
            row for row in rows
            if isinstance(row, dict) and str(row.get("username") or "") == str(username)
        ]
        if len(matches) > 1:
            raise LookupError("Keycloak username is ambiguous")
        if not matches:
            return None
        return matches[0]

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

    def _put(self, path: str, payload: Any) -> int:
        import json
        import urllib.request

        request = urllib.request.Request(
            f"{self.base_url}/admin/realms/{self.realm}/{path.lstrip('/')}",
            data=json.dumps(payload).encode(), method="PUT",
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return int(response.status)

    def group_representations(self) -> list[dict[str, Any]]:
        """Return the bounded, hierarchical Realm Group projection.

        This is an administrative UI/migration operation, never a request-path
        authorization check or a per-Bar operation.
        """
        return [row for row in self._all_groups() if isinstance(row, dict)]

    def update_group_attributes(
        self, group_path: str, updates: dict[str, list[str]],
    ) -> dict[str, Any]:
        """Merge a small set of attributes into one exact Realm Group.

        Existing group fields and unrelated attributes are preserved and the
        write is read back before success is returned.
        """
        path = str(group_path or "").strip()
        matches = [
            row for row in self.group_representations()
            if str(row.get("path") or "") == path
        ]
        if len(matches) != 1 or not str(matches[0].get("id") or ""):
            raise LookupError("Keycloak group is missing or ambiguous")
        group_id = str(matches[0]["id"])
        current = self._get(f"groups/{group_id}")
        if not isinstance(current, dict) or str(current.get("path") or "") != path:
            raise LookupError("Keycloak group changed during update")
        attributes = current.get("attributes")
        merged = dict(attributes) if isinstance(attributes, dict) else {}
        for key, values in updates.items():
            if not key or not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError("Keycloak group attributes must be string lists")
            merged[key] = list(values)
        self._put(f"groups/{group_id}", {**current, "attributes": merged})
        verified = self._get(f"groups/{group_id}")
        if not isinstance(verified, dict) or verified.get("attributes") != merged:
            raise RuntimeError("Keycloak group attribute update did not verify")
        return verified

    def user_id(self, username: str) -> str:
        """Resolve one exact Keycloak username or fail without guessing."""
        import urllib.parse

        query = urllib.parse.urlencode({"username": str(username), "exact": "true"})
        rows = self._get(f"users?{query}")
        matches = [row for row in rows or []
                   if isinstance(row, dict)
                   and str(row.get("username") or "") == str(username)]
        if len(matches) != 1 or not str(matches[0].get("id") or ""):
            raise LookupError(f"Keycloak user is missing or ambiguous: {username}")
        return str(matches[0]["id"])

    def user_by_identity_id(self, identity_id: str) -> dict[str, Any] | None:
        """Find one exact cross-Manager identity without username guessing.

        Keycloak's Admin API supports the ``q`` attribute query for custom
        user attributes. We still verify the returned attribute locally and
        reject ambiguity; the stable identity is the lookup key, while a
        username collision is never treated as proof that two users match.
        """
        selected = str(identity_id or "").strip()
        if not selected or len(selected) > 128:
            raise ValueError("stable identity ID is required")
        import urllib.parse

        query = urllib.parse.urlencode({"q": f"tr_identity_id:{selected}", "first": 0, "max": 3})
        rows = self._get("users?" + query)
        matches = [
            row for row in rows or ()
            if isinstance(row, dict)
            and selected in (row.get("attributes") or {}).get("tr_identity_id", ())
        ]
        if len(matches) > 1:
            raise LookupError("Keycloak stable identity ID is ambiguous")
        return matches[0] if matches else None

    def update_migrated_user(
        self, user_id: str, *, username: str, email: str = "",
        attributes: dict[str, tuple[str, ...]] | None = None,
        enabled: bool = True,
    ) -> None:
        """Idempotently update migration-owned fields without touching credentials."""
        import urllib.parse

        selected_id = str(user_id or "").strip()
        if not selected_id:
            raise ValueError("Keycloak user ID is required")
        current = self._get(f"users/{urllib.parse.quote(selected_id, safe='')}")
        if not isinstance(current, dict) or not str(current.get("id") or "") == selected_id:
            raise LookupError("Keycloak user is missing or changed")
        if str(current.get("username") or "") != str(username):
            raise ValueError("Keycloak username differs from the migration identity")
        current["enabled"] = bool(enabled)
        if email:
            current["email"] = email
        incoming = {key: list(values) for key, values in (attributes or {}).items()}
        previous = current.get("attributes")
        merged = dict(previous) if isinstance(previous, dict) else {}
        merged.update(incoming)
        current["attributes"] = merged
        self._put(f"users/{urllib.parse.quote(selected_id, safe='')}", current)

    def add_client_roles(self, username: str, client_id: str,
                         role_names: tuple[str, ...] | list[str]) -> list[str]:
        """Idempotently assign existing client roles to one exact user."""
        import urllib.parse

        rows = self._get("clients?" + urllib.parse.urlencode({"clientId": client_id}))
        clients = [row for row in rows or []
                   if isinstance(row, dict)
                   and str(row.get("clientId") or "") == client_id]
        if len(clients) != 1 or not str(clients[0].get("id") or ""):
            raise LookupError(f"Keycloak client is missing or ambiguous: {client_id}")
        client_uuid = str(clients[0]["id"])
        user_id = self.user_id(username)
        existing = self._get(f"users/{user_id}/role-mappings/clients/{client_uuid}")
        existing_names = {str(row.get("name") or "") for row in existing or []
                          if isinstance(row, dict)}
        assigned: list[str] = []
        for role_name in sorted(set(role_names)):
            if role_name in existing_names:
                continue
            encoded = urllib.parse.quote(role_name, safe="")
            role = self._get(f"clients/{client_uuid}/roles/{encoded}")
            if not isinstance(role, dict) or str(role.get("name") or "") != role_name:
                raise LookupError(f"Keycloak client role is missing: {role_name}")
            self._put(
                f"users/{user_id}/role-mappings/clients/{client_uuid}", [role],
            )
            assigned.append(role_name)
        return assigned

    def client_role_users(
        self, client_id: str, role_name: str, *, page_size: int = 500,
        max_users: int = 10_000,
    ) -> list[dict[str, Any]]:
        """List users with one exact client role using bounded pagination.

        This is used only for rare administrative policy transitions, never
        during authentication or a job's hot path. If the result exceeds the
        safety cap, callers must fail closed rather than infer an incomplete
        administrator set.
        """
        import urllib.parse

        if not 1 <= int(page_size) <= 1000 or not 1 <= int(max_users) <= 100_000:
            raise ValueError("invalid Keycloak role-user query bounds")
        clients = self._get("clients?" + urllib.parse.urlencode({"clientId": client_id}))
        matches = [row for row in clients or []
                   if isinstance(row, dict)
                   and str(row.get("clientId") or "") == client_id
                   and str(row.get("id") or "")]
        if len(matches) != 1:
            raise LookupError(f"Keycloak client is missing or ambiguous: {client_id}")
        client_uuid = str(matches[0]["id"])
        encoded_role = urllib.parse.quote(str(role_name), safe="")
        role = self._get(f"clients/{client_uuid}/roles/{encoded_role}")
        if not isinstance(role, dict) or str(role.get("name") or "") != role_name:
            raise LookupError(f"Keycloak client role is missing: {role_name}")

        users: dict[str, dict[str, Any]] = {}
        offset = 0
        while offset <= max_users:
            count = min(page_size, max_users + 1 - offset)
            rows = self._get(
                f"clients/{client_uuid}/roles/{encoded_role}/users?"
                + urllib.parse.urlencode({"first": offset, "max": count})
            )
            if not isinstance(rows, list):
                raise RuntimeError("Keycloak role-user response is invalid")
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("Keycloak role-user response is invalid")
                user_id = str(row.get("id") or "").strip()
                username = str(row.get("username") or "").strip()
                if not user_id or not username:
                    raise RuntimeError("Keycloak role-user response omitted identity")
                users[user_id] = row
            if len(users) > max_users:
                raise RuntimeError("Keycloak role-user result exceeded safety cap")
            if len(rows) < count:
                return sorted(users.values(), key=lambda row: str(row["username"]).casefold())
            offset += len(rows)
        raise RuntimeError("Keycloak role-user result exceeded safety cap")

    def user_group_paths(
        self, user_id: str, *, page_size: int = 500, max_groups: int = 5000,
    ) -> set[str]:
        """Return one user's bounded Realm Group memberships.

        Used only during an explicit organization-sync policy transition. This
        is deliberately not called by login, job, or per-Bar paths.
        """
        import urllib.parse

        selected_id = str(user_id or "").strip()
        if not selected_id or len(selected_id) > 512:
            raise ValueError("invalid Keycloak user id")
        if not 1 <= int(page_size) <= 1000 or not 1 <= int(max_groups) <= 100_000:
            raise ValueError("invalid Keycloak user-group query bounds")
        encoded_id = urllib.parse.quote(selected_id, safe="")
        result: set[str] = set()
        offset = 0
        while offset < max_groups:
            count = min(page_size, max_groups - offset)
            rows = self._get(
                f"users/{encoded_id}/groups?"
                + urllib.parse.urlencode({"first": offset, "max": count})
            )
            if not isinstance(rows, list):
                raise RuntimeError("Keycloak user-group response is invalid")
            for row in rows:
                if not isinstance(row, dict):
                    raise RuntimeError("Keycloak user-group response is invalid")
                path = str(row.get("path") or "").strip()
                if not path.startswith("/") or "//" in path:
                    raise RuntimeError("Keycloak returned an invalid group path")
                result.add(path.rstrip("/"))
            if len(result) > max_groups:
                raise RuntimeError("Keycloak user-group result exceeds its safety cap")
            if len(rows) < count:
                return result
            offset += count
        raise RuntimeError("Keycloak user-group result exceeds its safety cap")

    def create_user(self, *, username: str, email: str = "", groups: tuple[str, ...] = (),
                    attributes: dict[str, tuple[str, ...]] | None = None) -> str:
        import urllib.request

        body = {
            "username": username, "enabled": True,
            "requiredActions": ["UPDATE_PASSWORD"],
            "attributes": {key: list(value) for key, value in (attributes or {}).items()},
        }
        if email:
            body["email"] = email
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

    def set_user_attributes(self, user_id: str, attributes: dict[str, str]) -> None:
        import json
        import urllib.request

        users = self._get(f"users/{user_id}") or {}
        current = {k: list(v) if isinstance(v, list) else [v]
                   for k, v in (users.get("attributes") or {}).items()}
        current.update({k: [v] for k, v in attributes.items()})
        users["attributes"] = current
        request = urllib.request.Request(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}",
            data=json.dumps(users).encode(), method="PUT",
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if response.status not in {204, 200}:
                raise RuntimeError(f"user update failed: {response.status}")

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

    def _page(self, path: str, *, page_size: int = 100,
              max_items: int = 20_000) -> list[dict[str, Any]]:
        """Read one Keycloak collection with explicit pagination bounds."""
        import urllib.parse

        if not 1 <= int(page_size) <= 500 or not 1 <= int(max_items) <= 100_000:
            raise ValueError("invalid Keycloak directory page budget")
        result: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        for offset in range(0, max_items, page_size):
            count = min(page_size, max_items - offset)
            page_path = path + separator + urllib.parse.urlencode({
                "first": offset, "max": count,
            })
            rows = self._get(page_path)
            if not isinstance(rows, list):
                raise RuntimeError("Keycloak directory response is not a list")
            if any(not isinstance(row, dict) for row in rows):
                raise RuntimeError("Keycloak directory returned an invalid item")
            result.extend(rows)
            if len(rows) < count:
                return result
        raise RuntimeError("Keycloak directory exceeds its configured item limit")

    def _all_groups(self, parent: str = "", *, max_groups: int = 20_000) -> list[dict]:
        """Return a bounded Realm Group tree, paging every level."""
        result: list[dict[str, Any]] = []
        visited: set[str] = set()

        def walk(parent_id: str) -> None:
            endpoint = f"groups/{parent_id}/children" if parent_id else "groups"
            for item in self._page(endpoint, max_items=max_groups):
                group_id = str(item.get("id") or "").strip()
                path = str(item.get("path") or "").strip()
                if not group_id or not path:
                    raise RuntimeError("Keycloak returned a group without id/path")
                if group_id in visited:
                    continue
                visited.add(group_id)
                result.append(item)
                if len(result) > max_groups:
                    raise RuntimeError("Keycloak group tree exceeds its configured limit")
                walk(group_id)

        walk(parent)
        return result

    def group_tree_members(self, group_path: str, *,
                           max_groups: int = 4096,
                           max_users: int = 20_000) -> list[Identity]:
        """Return unique users directly assigned under a nested group path.

        This is a bounded administrative directory query for catalog/admin
        surfaces. It is not used for request authorization or market-data hot
        paths; object access is still decided by Keycloak FGAP.
        """
        root = "/" + "/".join(part for part in str(group_path).split("/") if part)
        if root != "/traderesearch" and not root.startswith("/traderesearch/"):
            raise ValueError("group path is outside the TradeResearch realm tree")
        groups = self._all_groups(max_groups=max_groups)
        selected = [row for row in groups
                    if (path := str(row.get("path") or "")) == root
                    or path.startswith(root + "/")]
        if not selected:
            return []
        users: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for group in selected:
            group_id = str(group["id"])
            path = str(group["path"])
            for raw in self._page(
                f"groups/{group_id}/members", max_items=max_users,
            ):
                username = str(raw.get("username") or "").strip()
                user_id = str(raw.get("id") or "").strip()
                if not username or not user_id:
                    raise RuntimeError("Keycloak group member omitted identity")
                existing = users.get(user_id)
                if existing is None:
                    users[user_id] = (raw, {path})
                else:
                    existing[1].add(path)
                if len(users) > max_users:
                    raise RuntimeError("Keycloak group membership exceeds its configured limit")
        return [
            self._identity(raw, sorted(paths), [])
            for _user_id, (raw, paths) in sorted(
                users.items(), key=lambda item: (
                    str(item[1][0].get("username") or "").casefold(), item[0],
                ),
            )
        ]

    def list_users(self, *, max_users: int = 20_000) -> list[Identity]:
        """List a bounded user directory for explicitly authorized admins."""
        rows = self._page("users", max_items=max_users)
        identities: list[Identity] = []
        for raw in rows:
            username = str(raw.get("username") or "").strip()
            if not username or not str(raw.get("id") or "").strip():
                raise RuntimeError("Keycloak user directory returned an invalid identity")
            identities.append(self._identity(raw, [], []))
        return identities

    def group_members(self, group_path: str) -> list[Identity]:
        target = next(
            (item for item in self._all_groups()
             if str(item.get("path") or "") == group_path),
            None,
        )
        if target is None:
            return []
        members = self._page(f"groups/{target['id']}/members")
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
    code_challenge: str = "",
) -> str:
    """Build the browser authorization-code URL for a Keycloak realm."""
    import urllib.parse

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if code_challenge:
        params.update({
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
    query = urllib.parse.urlencode(params)
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
            raw = response.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("OIDC token response exceeds budget")
        return json.loads(raw)

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
        raw = response.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError("OIDC userinfo response exceeds budget")
    return json.loads(raw)



def jwt_claims(token: str) -> dict:
    """Decode JWT claims; used only for tokens received directly from Keycloak."""
    import base64
    import json

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode()).decode())


def oidc_logout_url(
    *, base_url: str, realm: str, client_id: str,
    post_logout_redirect_uri: str = "", id_token_hint: str = "",
) -> str:
    import urllib.parse

    query = {"client_id": client_id}
    if post_logout_redirect_uri:
        query["post_logout_redirect_uri"] = post_logout_redirect_uri
    if id_token_hint:
        query["id_token_hint"] = id_token_hint
    return (
        f"{base_url.rstrip('/')}/realms/{realm.strip('/')}"
        f"/protocol/openid-connect/logout?{urllib.parse.urlencode(query)}"
    )


class ServiceOIDCClient(OIDCClient):
    """Keycloak service grants and introspection; no local JWT verifier."""
    def _token(self, form: dict) -> dict:
        import json
        import urllib.parse
        from urllib.request import Request
        from server.manager.domain.federation_transport import FederationTransport
        if self.client_secret:
            form = {**form, "client_secret": self.client_secret}
        request = Request(f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data=urllib.parse.urlencode(form).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with FederationTransport().open(request, timeout=self.timeout) as response:
            raw = response.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("OIDC response exceeds budget")
        return json.loads(raw)

    def client_credentials(self, *, scope: str = "") -> dict:
        return self._token({"grant_type": "client_credentials", "client_id": self.client_id,
                            **({"scope": scope} if scope else {})})

    def exchange_token(self, token: str, *, audience: str, scope: str = "") -> dict:
        return self._token({"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": self.client_id, "subject_token": token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": audience, **({"scope": scope} if scope else {})})

    def authorize(self, token: str, *, audience: str, resource_id: str,
                  scope: str, timeout: float | None = None) -> bool:
        """Ask Keycloak Authorization Services for one resource/scope decision.

        The user's verified access token is the bearer credential.  Do not use
        the Manager service account here: authorization must be evaluated for
        the requesting user.  Resource IDs are provisioned in Keycloak and are
        never synthesized from an application owner check.
        """
        import json
        import urllib.parse
        from urllib.error import HTTPError
        from urllib.request import Request
        from server.manager.domain.federation_transport import FederationTransport

        resource_id = str(resource_id or "").strip()
        scope = str(scope or "").strip()
        if not token or not resource_id or not scope or "#" in resource_id:
            return False
        request = Request(
            f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data=urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:uma-ticket",
                "audience": audience,
                "permission": f"{resource_id}#{scope}",
                "response_mode": "decision",
            }).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with FederationTransport().open(request, timeout=timeout or self.timeout) as response:
                raw = response.read(16 * 1024 + 1)
        except HTTPError as exc:
            if exc.code in {400, 401, 403}:
                return False
            raise
        if len(raw) > 16 * 1024:
            raise ValueError("Keycloak authorization response exceeds budget")
        result = json.loads(raw)
        return isinstance(result, dict) and result.get("result") is True

    def authorize_many(self, token: str, *, audience: str,
                       permissions: list[tuple[str, str, str]],
                       resource_format: str = "uri",
                       timeout: float | None = None) -> set[tuple[str, str]]:
        """Evaluate bounded resource/scope decisions in one UMA request per batch.

        Each permission is ``(resource, resource_name, scope)``.  Stable
        application URIs avoid a per-object Keycloak resource-ID lookup; the
        resource name lets ``response_mode=permissions`` map granted entries
        back to the requested URI.  No owner/role decision is made locally.
        """
        import json
        import urllib.parse
        from urllib.error import HTTPError
        from urllib.request import Request
        from server.manager.domain.federation_transport import FederationTransport

        if resource_format not in {"id", "uri"}:
            raise ValueError("Keycloak resource format must be id or uri")
        if len(permissions) > 256:
            raise ValueError("Keycloak authorization batch exceeds 256 permissions")
        normalized: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for resource, resource_name, scope in permissions:
            resource = str(resource or "").strip()
            resource_name = str(resource_name or "").strip()
            scope = str(scope or "").strip()
            if (not resource or not resource_name or not scope or "#" in resource
                    or "#" in scope or len(resource) > 2048
                    or len(resource_name) > 256 or len(scope) > 128):
                raise ValueError("invalid Keycloak authorization permission")
            key = (resource, scope)
            if key not in seen:
                normalized.append((resource, resource_name, scope))
                seen.add(key)
        if not token or not normalized:
            return set()

        # Keycloak accepts repeated `permission` form fields. Keep each
        # request small enough to avoid oversized URLs/bodies and response
        # payloads for large factor libraries.
        granted: set[tuple[str, str]] = set()
        for offset in range(0, len(normalized), 64):
            batch = normalized[offset:offset + 64]
            names_by_resource = {resource_name: resource for resource, resource_name, _ in batch}
            form: list[tuple[str, str]] = [
                ("grant_type", "urn:ietf:params:oauth:grant-type:uma-ticket"),
                ("audience", audience),
                ("permission_resource_format", resource_format),
                ("permission_resource_matching_uri", "false"),
                ("response_include_resource_name", "true"),
                ("response_mode", "permissions"),
            ]
            form.extend(
                ("permission", f"{resource}#{scope}")
                for resource, _name, scope in batch
            )
            request = Request(
                f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
                data=urllib.parse.urlencode(form).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            try:
                with FederationTransport().open(request, timeout=timeout or self.timeout) as response:
                    raw = response.read(64 * 1024 + 1)
            except HTTPError as exc:
                if exc.code == 403:
                    # All requested permissions in this batch were denied.
                    continue
                if exc.code == 401:
                    return set()
                raise
            if len(raw) > 64 * 1024:
                raise ValueError("Keycloak authorization response exceeds budget")
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError("Keycloak returned an invalid permissions response")
            scopes_by_resource = {
                resource_name: {scope for resource, name, scope in batch if name == resource_name}
                for resource_name in names_by_resource
            }
            for row in rows:
                if not isinstance(row, dict):
                    continue
                resource_name = str(row.get("rsname") or "")
                resource = names_by_resource.get(resource_name)
                scopes = row.get("scopes")
                if resource is None or not isinstance(scopes, list):
                    continue
                requested_scopes = scopes_by_resource.get(resource_name, set())
                granted.update(
                    (resource, str(scope)) for scope in scopes
                    if isinstance(scope, str) and scope in requested_scopes
                )
        return granted

    def introspect(self, token: str) -> dict:
        import json
        import urllib.parse
        from urllib.request import Request
        from server.manager.domain.federation_transport import FederationTransport
        request = Request(f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token/introspect",
            data=urllib.parse.urlencode({"token": token, "token_type_hint": "access_token",
                "client_id": self.client_id, "client_secret": self.client_secret}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with FederationTransport().open(request, timeout=self.timeout) as response:
            raw=response.read(128*1024+1)
        if len(raw)>128*1024:raise ValueError("OIDC response exceeds budget")
        return json.loads(raw)
