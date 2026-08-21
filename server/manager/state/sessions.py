"""Authentication sessions and owner-only Manager credentials."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sys
import threading
import time

from server.manager.config import (
    MANAGER_SESSION_CLEANUP_INTERVAL_SECONDS,
    MANAGER_SESSION_IDLE_TTL_SECONDS,
    MANAGER_SESSION_REFRESH_WINDOW_SECONDS,
    MANAGER_SESSION_TOUCH_INTERVAL_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
)
from server.manager.domain.organization_scope import (
    default_managed_organization,
    organization_descriptor,
    validate_alias,
)
from server.manager.storage.control_db import ControlDatabaseError
from server.manager.storage.local_accounts import LocalAccountStore
from server.manager.storage.session_store import ManagerSessionStore
from server.manager.system import write_owner_only_once as _write_owner_only_once


class SessionStateMixin:
    """Own account sessions without coupling them to HTTP transport."""
    def login(
        self,
        username: str,
        password: str,
        *,
        authentication: str = "password",
        origin: str = "",
    ) -> tuple[str, str, str]:
        if self.control_store is None:
            # Keep the legacy helper's two-argument seam for local clients and
            # tests that replace the SQLite authenticator.
            principal, role = self._authenticate_credentials(username, password)
        else:
            local = LocalAccountStore()
            try:
                local.sync_pending(self.control_store)
            except ControlDatabaseError:
                # The normal authority attempt below will fail in the same
                # way, after which the just-created local account can log in.
                pass
            try:
                principal, role = self._authenticate_credentials(
                    username,
                    password,
                    control_store=self.control_store,
                )
            except ControlDatabaseError:
                # PostgreSQL is authoritative.  During an outage, use only
                # the account rows already present in this Manager's existing
                # SQLite database; no account/device cache is created here.
                principal, role = self._authenticate_credentials(
                    username,
                    password,
                    control_store=LocalAccountStore(),
                )
        return self._issue_session(
            principal,
            role,
            alias=self._alias_for_principal(principal),
            authentication=authentication,
            origin=origin,
        )

    def login_device(
        self,
        username: str,
        *,
        origin: str = "",
    ) -> tuple[str, str, str]:
        """Issue an origin-bound session after a registered device proves its key."""
        if self.control_store is None:
            account = self.account_for_principal(username)
        else:
            account = self._account_for_principal_from(self.control_store, username)
        if account is None or not bool(account.get("active", True)):
            raise PermissionError("device account is not active")
        role = self._role_for_account(account)
        return self._issue_session(
            str(account["username"]),
            role,
            alias=str(account.get("alias") or account["username"]),
            authentication="device",
            origin=origin,
        )

    def issue_agent_session(
        self,
        principal: str,
        profile_id: str,
        claim_id: str,
    ) -> dict[str, str]:
        """Issue an ephemeral, non-admin session for one server Profile Agent."""
        owner = str(principal or "").strip()
        profile = str(profile_id or "").strip()
        claim = str(claim_id or "").strip()
        if not owner or not profile or not claim:
            raise PermissionError("Agent session identity is incomplete")
        token, _, _ = self._issue_session(
            owner,
            "user",
            alias=self._alias_for_principal(owner),
            authentication="agent",
        )
        with self._session_lock:
            sessions = getattr(self, "_agent_sessions", None)
            if sessions is None:
                sessions = self._agent_sessions = {}
            sessions[self._token_hash(token)] = {
                "principal": owner,
                "profile_id": profile,
                "claim_id": claim,
            }
        return {
            "token": token,
            "principal": owner,
            "profile_id": profile,
            "claim_id": claim,
        }

    def agent_session_matches(
        self,
        token: str,
        profile_id: str,
        claim_id: str,
    ) -> bool:
        """Validate the Profile/claim headers attached by the CLI."""
        value = str(token or "").strip()
        if not value or self.session_authentication(value) != "agent":
            return False
        expected_profile = str(profile_id or "").strip()
        expected_claim = str(claim_id or "").strip()
        with self._session_lock:
            record = getattr(self, "_agent_sessions", {}).get(
                self._token_hash(value),
            )
        return bool(
            record
            and hmac.compare_digest(str(record.get("profile_id") or ""), expected_profile)
            and hmac.compare_digest(str(record.get("claim_id") or ""), expected_claim)
        )

    def revoke_agent_session(self, token: str) -> None:
        """Invalidate one ephemeral Agent capability and its local session."""
        value = str(token or "").strip()
        if not value:
            return
        with self._session_lock:
            sessions = getattr(self, "_agent_sessions", None)
            if sessions is not None:
                sessions.pop(self._token_hash(value), None)
        self.logout(value)

    def account_for_principal(self, username: str) -> dict[str, object] | None:
        principal = str(username or "").strip()
        if not principal:
            return None
        if self.control_store is not None:
            return self._account_for_principal_from(self.control_store, principal)
        else:
            from tools.data.account_manage import accounts_lock, load_accounts
            with accounts_lock:
                accounts = load_accounts()
        return next(
            (dict(item) for item in accounts
             if str(item.get("username") or "") == principal),
            None,
        )

    def public_visitor_login_account(
        self,
        username: str,
    ) -> dict[str, object] | None:
        """Resolve one explicitly allowlisted account for visitor login.

        Visitor login is intentionally narrower than normal Manager login:
        the submitted identifier must resolve to exactly one account, that
        account must be named by the deployment allowlist.  The allowlist may
        include an active administrator when a super-admin explicitly grants
        that access; the account's normal role and capabilities are preserved.
        References are compared case-sensitively so an alias cannot silently
        resolve to another account.  An empty or invalid allowlist fails
        closed.
        """
        value = str(username or "").strip()
        central_accounts = self._central_public_visitor_accounts()
        if central_accounts is not None:
            # An empty central result is authoritative: removing the last
            # row must not resurrect an old deployment environment variable.
            candidates = [
                dict(account)
                for account in central_accounts
                if value and value in self._account_login_references(account)
            ]
        else:
            allowlist = tuple(
                str(item or "").strip()
                for item in getattr(self, "public_visitor_login_allowlist", ())
                if str(item or "").strip()
            )
            if not value or not allowlist:
                return None
            accounts = self._public_visitor_accounts()
            candidates = [
                dict(account)
                for account in accounts
                if value in self._account_login_references(account)
                and any(
                    reference in self._account_login_references(account)
                    for reference in allowlist
                )
            ]
        if len(candidates) != 1:
            # This includes duplicate aliases and role changes made after a
            # deployment allowlist was written.  Do not reveal which account
            # caused the ambiguity to an unauthenticated visitor.
            return None
        account = candidates[0]
        if not bool(account.get("active", True)):
            return None
        return account

    def _central_public_visitor_accounts(
        self,
    ) -> list[dict[str, object]] | None:
        """Read the PostgreSQL visitor policy when its API is available.

        ``None`` means the configured store is unavailable or is an older
        local/test adapter without the policy API.  An empty list is a valid
        central result and remains authoritative.
        """
        store = getattr(self, "control_store", None)
        reader = getattr(store, "public_visitor_login_accounts", None)
        if not callable(reader):
            return None
        try:
            return [
                dict(item)
                for item in reader(
                    server_id=str(getattr(self, "server_id", "") or ""),
                )
            ]
        except (ControlDatabaseError, OSError, RuntimeError, TypeError, ValueError):
            return None

    def _public_visitor_accounts(self) -> list[dict[str, object]]:
        """Read the account authority, falling back to existing local SQLite."""
        if self.control_store is not None:
            try:
                return [dict(item) for item in self.control_store.load_accounts()]
            except ControlDatabaseError:
                # Public visitor login must retain the same local-account
                # outage behavior as normal password login.
                pass
        return [dict(item) for item in LocalAccountStore().load_accounts()]

    @staticmethod
    def _account_login_references(account: dict[str, object]) -> tuple[str, ...]:
        """Return exact canonical, organization+alias, and alias references."""
        references: list[str] = []
        for value in (account.get("username"), account.get("alias")):
            normalized = str(value or "").strip()
            if normalized and normalized not in references:
                references.append(normalized)
        organization = str(account.get("organization_id") or "").strip()
        alias = str(account.get("alias") or "").strip()
        if organization and alias:
            organization_alias = f"{organization}@{alias}"
            if organization_alias not in references:
                references.append(organization_alias)
        return tuple(references)

    @staticmethod
    def _account_for_principal_from(
        store: object,
        principal: str,
    ) -> dict[str, object] | None:
        accounts = store.load_accounts()
        return next(
            (
                dict(item) for item in accounts
                if str(item.get("username") or "") == principal
            ),
            None,
        )

    def _alias_for_principal(self, principal: str) -> str:
        """Resolve the UI alias without making it an auth dependency.

        The alias is presentation metadata.  A session must still be usable
        when PostgreSQL is unavailable, so a failed central lookup falls back
        to this Manager's existing local account table and finally to the
        canonical principal itself.
        """
        value = str(principal or "").strip()
        if not value:
            return ""
        stores = []
        if self.control_store is not None:
            stores.append(self.control_store)
            stores.append(LocalAccountStore())
        else:
            stores.append(None)
        for store in stores:
            try:
                account = (
                    self._account_for_principal_from(store, value)
                    if store is not None
                    else self.account_for_principal(value)
                )
            except ControlDatabaseError:
                continue
            if account is not None:
                return str(account.get("alias") or value).strip() or value
        return value

    def _issue_session(
        self,
        principal: str,
        role: str,
        *,
        alias: str = "",
        authentication: str = "password",
        origin: str = "",
    ) -> tuple[str, str, str]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._session_lock:
            token_hash = self._token_hash(token)
            session = (
                principal,
                role,
                now + MANAGER_SESSION_TTL_SECONDS,
                str(authentication or "password"),
                str(origin or "").strip().rstrip("/"),
                str(alias or principal).strip() or str(principal),
                now,
                now,
            )
            self._sessions[token_hash] = session
            self._session_store().upsert(token_hash, session, now=now)
        return token, principal, role

    def register(self, alias: str, password: str, organization_id: str = "") -> tuple[str, str, str, str]:
        if self.control_store is not None:
            result = self._register_with_control_outbox(
                alias, password, organization_id,
            )
            self._initialize_registered_profile(result[0])
            return result
        from tools.data.account_manage import (
            DEFAULT_ORGANIZATION_NAME,
            ROLE_SUPER_ADMIN,
            ROLE_USER,
            accounts_lock,
            hash_password,
            list_organizations_with_default,
            load_accounts,
            next_account_username,
            root_level_id_for_org,
            save_accounts,
        )
        alias = validate_alias(alias)
        password = str(password or "")
        if not password:
            raise ValueError("用户名和密码不能为空")
        if len(password) < 6:
            raise ValueError("密码至少6位")
        organization_id = self._registration_organization(organization_id)
        organizations = list_organizations_with_default()
        organizations = self._with_managed_organization_descriptors(organizations)
        org = next((item for item in organizations if item.get("id") == organization_id), None)
        if not org:
            raise ValueError("机构不存在")
        with accounts_lock:
            accounts = load_accounts()
            full_name = next_account_username(accounts, organization_id, alias)
            salt = secrets.token_hex(16)
            role = ROLE_SUPER_ADMIN if not accounts else ROLE_USER
            accounts.append({
                "username": full_name, "alias": alias, "salt": salt,
                "hash": hash_password(password, salt), "role": role,
                "is_admin": role == ROLE_SUPER_ADMIN,
                "organization_id": organization_id,
                "organization_name": org.get("name") or DEFAULT_ORGANIZATION_NAME,
                "level_id": root_level_id_for_org(organization_id),
                "parent_username": "",
            })
            save_accounts(accounts)
        result = (full_name, role, alias, organization_id)
        self._initialize_registered_profile(full_name)
        return result

    def _initialize_registered_profile(self, principal: str) -> None:
        initializer = getattr(
            getattr(self, "client_state", None),
            "ensure_self_profile",
            None,
        )
        if not callable(initializer):
            return
        try:
            initializer(principal)
        except (
            AttributeError, ConnectionError, OSError, RuntimeError,
            TypeError, ValueError,
        ) as exc:
            # Account registration has already committed. The owner's first
            # Profile-directory read retries this idempotent initialization.
            sys.stderr.write(
                f"[manager] reserved self Profile initialization pending: {exc}\n"
            )

    def _register_with_control_outbox(
        self,
        alias: str,
        password: str,
        organization_id: str = "",
    ) -> tuple[str, str, str, str]:
        """Register locally when PG is down and push it on a later request."""
        from tools.data.account_manage import (
            DEFAULT_ORGANIZATION_NAME,
            ROLE_USER,
            hash_password,
            root_level_id_for_org,
        )

        alias = validate_alias(alias)
        password = str(password or "")
        if not password:
            raise ValueError("用户名和密码不能为空")
        if len(password) < 6:
            raise ValueError("密码至少6位")

        local = LocalAccountStore()
        try:
            local.sync_pending(self.control_store)
        except ControlDatabaseError:
            pass
        accounts = local.load_accounts()
        try:
            organizations = [
                dict(item) for item in self.control_store.load_organizations()
            ]
        except ControlDatabaseError:
            organizations = local.organizations()
        organizations = self._with_managed_organization_descriptors(organizations)
        organization_id = self._registration_organization(organization_id)
        org = next(
            (item for item in organizations
             if str(item.get("id") or "") == organization_id),
            None,
        )
        if not org:
            raise ValueError("机构不存在")
        full_name = local.unique_registration_username(
            organization_id, alias, accounts,
        )
        salt = secrets.token_hex(16)
        # A disconnected Manager must never bootstrap a new super-admin from
        # an unverified local registration.  The account can be promoted by
        # the central administration path after synchronization.
        role = ROLE_USER
        account = {
            "username": full_name,
            "alias": alias,
            "salt": salt,
            "hash": hash_password(password, salt),
            "role": role,
            "is_admin": False,
            "is_developer": False,
            "organization_id": organization_id,
            "organization_name": str(org.get("name") or DEFAULT_ORGANIZATION_NAME),
            "level_id": root_level_id_for_org(organization_id),
            "parent_username": "",
            "active": True,
        }
        local.add_pending_account(account)
        try:
            self.control_store.create_account(account)
        except ControlDatabaseError:
            # Keep both the local account and its outbox row for a future
            # request after the central database becomes reachable.
            pass
        except (TypeError, ValueError) as exc:
            local.remove_account(full_name)
            raise ValueError(str(exc)) from exc
        else:
            local.remove_pending(full_name)
        return full_name, role, alias, organization_id

    def _registration_organization(self, organization_id: str) -> str:
        requested = str(organization_id or "").strip()
        managed = tuple(getattr(self, "managed_organizations", ()) or ())
        if not managed:
            raise ValueError("Manager没有配置可管理的机构")
        selected = requested or default_managed_organization(managed)
        if selected not in managed:
            raise ValueError("此 Manager 不管理该机构")
        return selected

    def _with_managed_organization_descriptors(
        self,
        organizations: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        result = [dict(item) for item in organizations]
        known = {str(item.get("id") or "") for item in result}
        for organization_id in tuple(getattr(self, "managed_organizations", ()) or ()):
            if organization_id not in known:
                result.append(organization_descriptor(organization_id))
        return result

    def session(self, token: str) -> dict[str, object] | None:
        now = time.time()
        with self._session_lock:
            self._cleanup_sessions_locked(now)
            token_hash = self._token_hash(token)
            session = self._sessions.get(token_hash)
            if session is None:
                return None
            principal, role, expires_at = session[:3]
            if expires_at <= now:
                self._sessions.pop(token_hash, None)
                self._session_store().delete(token_hash)
                return None
            created_at = self._session_timestamp(session, 6, now)
            last_seen_at = self._session_timestamp(session, 7, now)
            refreshed = expires_at - now <= MANAGER_SESSION_REFRESH_WINDOW_SECONDS
            touched = now - last_seen_at >= MANAGER_SESSION_TOUCH_INTERVAL_SECONDS
            if refreshed or touched or len(session) < 8:
                expires_at = now + MANAGER_SESSION_TTL_SECONDS
                if not refreshed:
                    expires_at = float(session[2])
                session = (
                    principal,
                    role,
                    expires_at,
                    str(session[3] if len(session) >= 4 else "password"),
                    str(session[4] if len(session) >= 5 else "").strip().rstrip("/"),
                    str(session[5] if len(session) >= 6 else "").strip(),
                    created_at,
                    now,
                )
                self._sessions[token_hash] = session
                self._session_store().upsert(token_hash, session, now=now)
        return {
            "username": principal,
            "alias": (
                str(session[5] or "").strip()
                if len(session) >= 6 else ""
            ) or self._alias_for_principal(principal),
            "role": role,
            "capabilities": {
                "manager": role == "super_admin",
                "research": True,
            },
        }

    def session_allows_device_origin(self, token: str, origin: str) -> bool:
        """Allow only a device-authenticated session on its issuing origin.

        Password sessions and legacy sessions created before origin metadata was
        introduced intentionally fail closed on a public device-gated Manager.
        The private key remains origin-local; this only binds the resulting
        HttpOnly session cookie to the origin that completed the challenge.
        """
        if self.session(token) is None:
            return False
        expected_origin = str(origin or "").strip().rstrip("/")
        if not expected_origin:
            return False
        with self._session_lock:
            value = self._sessions.get(self._token_hash(token))
            if value is None or len(value) < 5:
                return False
            authentication = str(value[3] or "")
            session_origin = str(value[4] or "").strip().rstrip("/")
        return (
            authentication in {"device", "visitor-password"}
            and session_origin == expected_origin
        )

    def session_principal(self, token: str) -> str | None:
        session = self.session(token)
        return str(session["username"]) if session else None

    def session_authentication(self, token: str) -> str:
        """Return the authentication method for a live session.

        HTTP routes use this narrow accessor for policy decisions such as the
        allowlisted visitor-device exemption.  The public session payload does
        not expose the method to callers, so it cannot be forged through JSON.
        """
        if self.session(token) is None:
            return ""
        with self._session_lock:
            value = self._sessions.get(self._token_hash(token))
            if value is None or len(value) < 4:
                return ""
            return str(value[3] or "")

    def logout(self, token: str) -> None:
        with self._session_lock:
            token_hash = self._token_hash(token)
            self._sessions.pop(token_hash, None)
            sessions = getattr(self, "_agent_sessions", None)
            if sessions is not None:
                sessions.pop(token_hash, None)
            self._session_store().delete(token_hash)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _session_timestamp(
        session: tuple[object, ...],
        index: int,
        fallback: float,
    ) -> float:
        try:
            return float(session[index])
        except (IndexError, TypeError, ValueError, OverflowError):
            return fallback

    def _session_store(self) -> ManagerSessionStore:
        """Return the Manager-owned store without creating a central dependency."""
        return self.session_store

    def _cleanup_sessions_locked(self, now: float) -> None:
        next_cleanup = float(getattr(self, "_session_cleanup_at", 0) or 0)
        if now < next_cleanup:
            return
        self._session_cleanup_at = now + MANAGER_SESSION_CLEANUP_INTERVAL_SECONDS
        self._session_store().cleanup(
            now=now,
            idle_ttl=MANAGER_SESSION_IDLE_TTL_SECONDS,
        )
        # The in-memory cache mirrors the durable rows loaded at startup.  A
        # cleanup may remove a row that was not touched by this process since
        # startup, so drop expired/idle entries from the cache as well.
        self._sessions = {
            token_hash: value
            for token_hash, value in self._sessions.items()
            if self._session_timestamp(value, 2, 0) > now
            and now - self._session_timestamp(value, 7, now)
            <= MANAGER_SESSION_IDLE_TTL_SECONDS
        }
        sessions = getattr(self, "_agent_sessions", None)
        if sessions is not None:
            sessions = {
                token_hash: value
                for token_hash, value in sessions.items()
                if token_hash in self._sessions
            }
            self._agent_sessions = sessions

    def _load_sessions(self) -> dict[str, tuple[object, ...]]:
        records = self._session_store().load(
            now=time.time(),
            idle_ttl=MANAGER_SESSION_IDLE_TTL_SECONDS,
        )
        # Agent sessions are intentionally process-bound.  The Agent child
        # cannot outlive a Manager restart, so never resurrect its bearer from
        # the durable ordinary-session table.
        return {
            token_hash: value
            for token_hash, value in records.items()
            if str(value[3] if len(value) >= 4 else "") != "agent"
        }

    def _save_sessions(self) -> None:
        self._session_store().replace(self._sessions)

    def submit_action(self, operation, label: str) -> None:
        """Run one already-authorized operation after its HTTP receipt."""
        def run() -> None:
            try:
                operation()
            except Exception as exc:
                sys.stderr.write(f"[manager] async action {label} failed: {exc}\n")

        threading.Thread(
            target=run,
            name=f"manager-action-{hashlib.sha256(label.encode()).hexdigest()[:8]}",
            daemon=True,
        ).start()

    def capability_token(self) -> str:
        if not self.capability_path.exists():
            _write_owner_only_once(self.capability_path, secrets.token_hex(32))
        self.capability_path.chmod(0o600)
        value = self.capability_path.read_text(encoding="ascii").strip()
        if not value:
            raise RuntimeError("manager capability token is empty")
        return value
    def federation_proxy_token(self) -> str:
        """Return the token accepted by this Manager's federation proxy."""
        if not self.federation_proxy_path.exists():
            _write_owner_only_once(
                self.federation_proxy_path,
                secrets.token_urlsafe(48),
            )
        self.federation_proxy_path.chmod(0o600)
        value = self.federation_proxy_path.read_text(encoding="ascii").strip()
        if not value:
            raise RuntimeError("federation proxy token is empty")
        return value
