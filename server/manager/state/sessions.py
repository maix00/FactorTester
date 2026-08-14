"""Authentication sessions and owner-only Manager credentials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time

from server.manager.config import (
    MANAGER_SESSION_REFRESH_WINDOW_SECONDS,
    MANAGER_SESSION_TTL_SECONDS,
)
from server.manager.system import write_owner_only_once as _write_owner_only_once


DEVICE_SESSION_HANDOFF_TTL_SECONDS = 120


class SessionStateMixin:
    """Own account sessions without coupling them to HTTP transport."""
    def login(self, username: str, password: str) -> tuple[str, str, str]:
        if self.control_store is None:
            # Keep the legacy helper's two-argument seam for local clients and
            # tests that replace the SQLite authenticator.
            principal, role = self._authenticate_credentials(username, password)
        else:
            principal, role = self._authenticate_credentials(
                username,
                password,
                control_store=self.control_store,
            )
        return self._issue_session(principal, role)

    def login_device(self, username: str) -> tuple[str, str, str]:
        """Issue a normal session after a registered device proves its key."""
        account = self.account_for_principal(username)
        if account is None or not bool(account.get("active", True)):
            raise PermissionError("device account is not active")
        role = self._role_for_account(account)
        return self._issue_session(str(account["username"]), role)

    def account_for_principal(self, username: str) -> dict[str, object] | None:
        principal = str(username or "").strip()
        if not principal:
            return None
        if self.control_store is not None:
            accounts = self.control_store.load_accounts()
        else:
            from tools.data.account_manage import accounts_lock, load_accounts
            with accounts_lock:
                accounts = load_accounts()
        return next(
            (dict(item) for item in accounts
             if str(item.get("username") or "") == principal),
            None,
        )

    def _issue_session(self, principal: str, role: str) -> tuple[str, str, str]:
        token = secrets.token_urlsafe(32)
        with self._session_lock:
            self._sessions[self._token_hash(token)] = (
                principal, role, time.time() + MANAGER_SESSION_TTL_SECONDS,
            )
            self._save_sessions()
        return token, principal, role

    def register(self, alias: str, password: str, organization_id: str = "") -> tuple[str, str, str, str]:
        from tools.data.account_manage import (
            DEFAULT_ORGANIZATION_ID, DEFAULT_ORGANIZATION_NAME,
            ROLE_SUPER_ADMIN, ROLE_USER, accounts_lock, hash_password,
            list_organizations_with_default, load_accounts,
            next_account_username, root_level_id_for_org, save_accounts,
        )
        alias = str(alias or "").strip()
        password = str(password or "")
        if not alias or not password:
            raise ValueError("用户名和密码不能为空")
        if not re.fullmatch(r"[A-Za-z0-9_\u4e00-\u9fff]{1,32}", alias):
            raise ValueError("用户名只能包含字母、数字、下划线或汉字，且不超过32字符")
        if len(password) < 6:
            raise ValueError("密码至少6位")
        organization_id = str(organization_id or DEFAULT_ORGANIZATION_ID).strip()
        org = next((item for item in list_organizations_with_default() if item.get("id") == organization_id), None)
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
        return full_name, role, alias, organization_id

    def session(self, token: str) -> dict[str, object] | None:
        now = time.time()
        with self._session_lock:
            token_hash = self._token_hash(token)
            session = self._sessions.get(token_hash)
            if session is None:
                return None
            principal, role, expires_at = session
            if expires_at <= now:
                self._sessions.pop(token_hash, None)
                self._save_sessions()
                return None
            if expires_at - now <= MANAGER_SESSION_REFRESH_WINDOW_SECONDS:
                expires_at = now + MANAGER_SESSION_TTL_SECONDS
                self._sessions[token_hash] = (principal, role, expires_at)
                self._save_sessions()
            return {
                "username": principal,
                "role": role,
                "capabilities": {
                    "manager": role == "super_admin",
                    "research": True,
                },
            }

    def session_principal(self, token: str) -> str | None:
        session = self.session(token)
        return str(session["username"]) if session else None

    def logout(self, token: str) -> None:
        with self._session_lock:
            self._sessions.pop(self._token_hash(token), None)
            self._save_sessions()

    def issue_device_handoff(
        self,
        principal: str,
        role: str,
        *,
        target_origin: str,
    ) -> str:
        """Create a one-use session handoff for another trusted origin.

        Browser storage remains origin-scoped.  The handoff carries no private
        key and no session token in the URL; it only allows the target origin
        to mint its own normal session after the source origin already proved
        the registered device key.
        """
        owner = str(principal or "").strip()
        account_role = str(role or "").strip()
        target = str(target_origin or "").strip().rstrip("/")
        if not owner or not account_role or not target:
            raise ValueError("device handoff fields are invalid")
        ticket = secrets.token_urlsafe(32)
        now = time.time()
        with self._session_lock:
            handoffs = getattr(self, "_device_handoffs", {})
            handoffs = {
                digest: value for digest, value in handoffs.items()
                if float(value.get("expires_at") or 0) > now
            }
            handoffs[self._token_hash(ticket)] = {
                "principal": owner,
                "role": account_role,
                "target_origin": target,
                "expires_at": now + DEVICE_SESSION_HANDOFF_TTL_SECONDS,
            }
            self._device_handoffs = handoffs
        return ticket

    def redeem_device_handoff(
        self,
        ticket: object,
        *,
        target_origin: str,
    ) -> tuple[str, str, str]:
        """Consume a source-origin handoff and mint a target-origin session."""
        target = str(target_origin or "").strip().rstrip("/")
        now = time.time()
        with self._session_lock:
            handoffs = getattr(self, "_device_handoffs", {})
            digest = self._token_hash(str(ticket or ""))
            value = handoffs.get(digest)
            handoffs = {
                key: item for key, item in handoffs.items()
                if float(item.get("expires_at") or 0) > now
            }
            if (
                value is not None
                and float(value.get("expires_at") or 0) > now
                and str(value.get("target_origin") or "") == target
            ):
                handoffs.pop(digest, None)
            self._device_handoffs = handoffs
        if (
            value is None
            or float(value.get("expires_at") or 0) <= now
            or str(value.get("target_origin") or "") != target
        ):
            raise PermissionError("device handoff is expired or target is invalid")
        principal = str(value.get("principal") or "")
        role = str(value.get("role") or "")
        token, principal, role = self._issue_session(principal, role)
        return token, principal, role

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _load_sessions(self) -> dict[str, tuple[str, str, float]]:
        try:
            payload = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return {}
        now = time.time()
        sessions: dict[str, tuple[str, str, float]] = {}
        for token_hash, value in (payload.get("sessions") or {}).items():
            if not isinstance(value, dict):
                continue
            expires_at = float(value.get("expires_at") or 0)
            if re.fullmatch(r"[0-9a-f]{64}", str(token_hash)) and expires_at > now:
                sessions[str(token_hash)] = (
                    str(value.get("principal") or ""),
                    str(value.get("role") or ""),
                    expires_at,
                )
        return sessions

    def _save_sessions(self) -> None:
        payload = {
            "schema_version": 1,
            "sessions": {
                token_hash: {
                    "principal": value[0],
                    "role": value[1],
                    "expires_at": value[2],
                }
                for token_hash, value in self._sessions.items()
            },
        }
        self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".sessions-", suffix=".json", dir=self.sessions_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.sessions_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

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
