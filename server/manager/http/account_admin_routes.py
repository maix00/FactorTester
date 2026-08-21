"""Super-admin user, organization, and hierarchy administration routes."""

from __future__ import annotations

import sys
from urllib.parse import unquote, urlparse

from server.manager.http.responses import json_response
from server.manager.services.account_admin import (
    AccountAdministrationError,
    AccountAdministrationService,
)
from server.manager.storage.control_db import ControlDatabaseError


class AccountAdministrationRoutesMixin:
    """Expose the old user-hierarchy capability on the Manager boundary."""

    def _account_admin_service(self) -> AccountAdministrationService | None:
        if not self._require_super_admin_session():
            return None
        store = getattr(self.state, "control_store", None)
        if store is None:
            json_response(self, {
                "success": False,
                "error": "central control database is not configured",
            }, 503)
            return None
        initializer = getattr(
            getattr(self.state, "client_state", None),
            "ensure_self_profile",
            None,
        )
        return AccountAdministrationService(
            store,
            profile_initializer=initializer if callable(initializer) else None,
        )

    def _admin_account_directory(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        try:
            value = service.snapshot()
        except (ControlDatabaseError, OSError, RuntimeError, TypeError, ValueError) as exc:
            sys.stderr.write(f"[manager] account directory read failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "control_database": {
                "backend": "postgresql",
                "authoritative": True,
                "local_sqlite_mirror": True,
            },
            **value,
        }, headers={"Cache-Control": "no-store"})

    def _admin_create_user(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        try:
            account = service.create_user(self._json_body(64 * 1024))
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] account create failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        except (AccountAdministrationError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "user": account}, 201)

    def _admin_update_user(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        prefix = "/api/admin/users/"
        target = unquote(urlparse(self.path).path[len(prefix):])
        session = self._session() or {}
        try:
            account = service.update_user(
                target,
                self._json_body(64 * 1024),
                current_username=str(session.get("username") or ""),
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] account update failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        except (AccountAdministrationError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "user": account})

    def _admin_create_organization(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        try:
            organization = service.create_organization(self._json_body(32 * 1024))
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] organization create failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        except (AccountAdministrationError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "organization": organization}, 201)

    def _admin_create_level(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        try:
            level = service.create_level(self._json_body(32 * 1024))
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] level create failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        except (AccountAdministrationError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "level": level}, 201)

    def _admin_update_level(self) -> None:
        service = self._account_admin_service()
        if service is None:
            return
        prefix = "/api/admin/levels/"
        target = unquote(urlparse(self.path).path[len(prefix):])
        try:
            level = service.update_level(target, self._json_body(32 * 1024))
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] level update failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "central account directory is unavailable",
            }, 503)
            return
        except (AccountAdministrationError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {"success": True, "level": level})
