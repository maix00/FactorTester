"""Authentication sessions and owner-only Manager credentials."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from server.manager.config import (
    MANAGER_SESSION_CLEANUP_INTERVAL_SECONDS,
    MANAGER_SESSION_IDLE_TTL_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
)
from server.manager.storage.session_store import ManagerSessionStore
from server.manager.system import write_owner_only_once as _write_owner_only_once


class SessionStateMixin:
    """Own account sessions without coupling them to HTTP transport."""
    def login(self, *args, **kwargs):
        raise PermissionError("password login is retired; authenticate through Keycloak")

    def login_device(self, *args, **kwargs):
        raise PermissionError("device authentication must complete through Keycloak OIDC")

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







    @staticmethod
    def _alias_for_principal(principal: str) -> str:
        # Display identity comes from verified Keycloak claims at request time.
        return str(principal or "").strip()

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






    def session(self, token: str) -> dict[str, object] | None:
        from server.identity.user_session import keycloak_session, may_login_public_server

        identity = keycloak_session(token)
        if identity is not None:
            if bool(getattr(self, "public_server", False)) and not may_login_public_server(identity):
                return None
            return identity

        # Manager-minted local credentials exist only for the ephemeral Profile
        # Agent capability. They are never a browser, device, or user login.
        # Most request-facing callers are a ManagerState, but this mixin is
        # also used directly by identity tests and small adapters. Without an
        # Agent record, fail closed before touching the local session lock or
        # persistent session store.
        agent_sessions = getattr(self, "_agent_sessions", None)
        if not agent_sessions:
            return None
        now = time.time()
        token_hash = self._token_hash(token)
        with self._session_lock:
            self._cleanup_sessions_locked(now)
            record = self._sessions.get(token_hash)
            agent_record = agent_sessions.get(token_hash)
            if (record is None or agent_record is None or len(record) < 4
                    or str(record[3] or "") != "agent"
                    or float(record[2]) <= now):
                return None
            principal = str(record[0] or "").strip()
            if principal != str(agent_record.get("principal") or "").strip():
                return None
        return {
            "username": principal,
            "alias": principal,
            "role": "user",
            "capabilities": {"manager": False, "research": True},
            "authentication": "agent",
        }

    def session_allows_device_origin(self, token: str, origin: str) -> bool:
        # Device approval is an input to Keycloak OIDC; it does not mint a
        # second local account session.
        del token, origin
        return False

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
