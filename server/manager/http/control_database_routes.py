"""Super-administrator routes for one Manager's PostgreSQL connection."""

from __future__ import annotations

import json

from server.manager.http.responses import json_response
from server.manager.storage.control_db import ControlDatabaseError


class ControlDatabaseRoutesMixin:
    def _control_database_config(self) -> None:
        if not self._require_super_admin_session():
            return
        json_response(self, {
            "success": True,
            "config": self.state.control_database_status(),
        }, headers={"Cache-Control": "no-store"})

    def _update_control_database_config(self) -> None:
        if not self._require_super_admin_session():
            return
        try:
            value = self.state.update_control_database(
                self._json_body(64 * 1024),
            )
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 409)
            return
        except ControlDatabaseError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
            return
        except (TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        json_response(self, {
            "success": True,
            "config": value,
        }, headers={"Cache-Control": "no-store"})
