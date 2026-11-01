"""HTTP route adapters for device identity and Manager network information."""

from __future__ import annotations

import base64
import json
import sys
from typing import Any

from server.manager.domain.device_clients import describe_client, observed_ip
from server.manager.domain.devices import (
    DeviceRegistryError,
)
from server.manager.http.responses import json_response
from server.manager.storage.control_db import (
    ControlDatabaseError,
)


class DeviceNetworkRoutesMixin:
    """Route methods for device discovery and server endpoint presentation.

    ``runtime.Handler`` supplies the authentication/transport helpers and
    ``state`` attribute.  Keeping this as a Mixin is an incremental seam: the
    existing Handler remains the single dispatcher while this route family
    gains its own module and focused test surface.
    """

    state: Any

    def _device_request_metadata(self) -> dict[str, str]:
        client = describe_client(
            user_agent=self.headers.get("User-Agent", ""),
            client_hint=self.headers.get("X-FactorTester-Client", ""),
        )
        return {
            **client,
            "enrollment_ip": observed_ip(self._client_ip()),
        }

    def _server_network_info(self) -> None:
        session = self._session()
        if (
            session is None
            and self._visitor_mode() is None
            and not self._is_private_lan_client()
            and not self._is_swift_network_discovery_request()
        ):
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        host = self.headers.get("Host", "").strip()
        scheme = "https" if self._is_secure_transport() else "http"
        request_endpoint = f"{scheme}://{host}" if host else ""
        json_response(self, {
            "success": True,
            **self.state.server_network_info(request_endpoint=request_endpoint),
        }, headers={"Cache-Control": "no-store"})

    def _device_list(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        # Personal settings always use account scope, including super admins.
        # Server-wide administration has dedicated /api/admin/access-control APIs.
        owner = str(session["username"])
        try:
            from server.identity.keycloak_device import may_use_devices
            from server.manager.domain.devices import _public_record
            records = self.state.device_registry.authorization_records(username=owner)
            allowed = may_use_devices(token=self._bearer_token(), session=session,
                                      server_id=self.state.server_id, records=records)
            # A registry mutation during the remote Keycloak request must not
            # turn an obsolete key decision into a current device status.
            current = self.state.device_registry.authorization_records(username=owner)
            def identity(rows):
                if any(type(row.get('enabled')) is not bool or row.get('username') != owner for row in rows):
                    raise DeviceRegistryError('invalid device registry binding')
                return sorted((str(row['device_id']), str(row['username']), row['enabled'],
                               str(row['source_server_id']), json.dumps(row['public_key'], sort_keys=True)) for row in rows)
            if identity(records) != identity(current):
                raise DeviceRegistryError('device registry changed during authorization check')
            devices = sorted(({**_public_record(row), 'keycloak_authorized': row['device_id'] in allowed}
                              for row in current), key=lambda row: (str(row.get('device_name') or ''), str(row['device_id'])))
            public_device_total_count = len(allowed)
            public_user_count = 1 if allowed else 0
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device list failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (PermissionError, DeviceRegistryError, ValueError, KeyError, TypeError):
            json_response(self, {"success": False, "error": "device authorization could not be verified"}, 503)
            return
        except Exception:
            json_response(self, {"success": False, "code": "keycloak_authorization_unavailable",
                                 "error": "Keycloak authorization is unavailable"}, 503)
            return
        json_response(self, {
            "success": True,
            "devices": devices,
            "public_device_count": public_device_total_count,
            "public_device_total_count": public_device_total_count,
            "public_user_count": public_user_count,
            "registered_device_count": sum(bool(row['enabled']) for row in current),
            "count_basis": "current_keycloak_use",
            "server_id": self.state.server_id,
            "public_server": bool(getattr(self.state, "public_server", False)),
            "device_policy": (
                "public_auto_login_allowlist"
                if bool(getattr(self.state, "public_server", False))
                else "organization_device_auto_login"
            ),
            **self.state.device_registry.backend_status(),
        }, headers={"Cache-Control": "private, no-store"})

    def _device_summary(self) -> None:
        session = self._session()
        owner = ""
        scope = "server"
        if session is not None:
            from server.identity.server_admission import current_manager_role
            # A stale legacy role label must not retain administrator scope.
            # The unauthenticated aggregate remains available for compliance.
            if not current_manager_role(session, "admin_console:manage"):
                owner = str(session.get("username") or "").strip()
                if not owner:
                    json_response(self, {"success": False, "error": "verified user identity required"}, 403)
                    return
                scope = "account"
        try:
            total_count = self.state.device_registry.public_device_total_count(
                username=owner,
            )
            user_count = (
                (1 if total_count else 0)
                if owner
                else self.state.device_registry.public_user_count()
            )
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device summary failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        json_response(self, {
            "success": True,
            "public_device_count": total_count,
            "public_device_total_count": total_count,
            "public_user_count": user_count,
            "count_basis": "enabled_device_records",
            "scope": scope,
            **self.state.device_registry.backend_status(),
        }, headers={"Cache-Control": "no-store"})

    def _device_enroll(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "device enrollment requires HTTPS outside private LAN",
            }, 400)
            return
        if not self._may_enroll_device(session):
            json_response(self, {
                "success": False,
                "error": "Keycloak public-server login permission is required to enroll this device",
                "code": "public_server_login_required",
            }, 403)
            return
        try:
            payload = self._json_body(64 * 1024)
            username = str(session["username"])
            device_id = str(payload.get("device_id") or "")
            public_key = payload.get("public_key")
            binding = self.state.device_registry.key_binding(username=username, device_id=device_id)
            changed = False
            if binding is not None:
                from server.manager.domain.devices import _public_record, normalise_public_key
                if binding.get("public_key") != normalise_public_key(public_key):
                    raise DeviceRegistryError("device cannot be re-enrolled with this identity or key")
                if not binding.get("enabled"):
                    device = self.state.device_registry.retry_enrollment(username=username, device_id=device_id, public_key=public_key)
                    changed = True
                else:
                    device = _public_record(binding)
            else:
                device = self.state.device_registry.enroll(
                    username=username, device_id=device_id, public_key=public_key,
                    device_name=str(payload.get("device_name") or ""),
                    **self._device_request_metadata(),
                )
                changed = True
            # Registration is explicit: a verified signature alone must never
            # create an authorization grant. A failed grant leaves the local
            # record disabled until the user deliberately registers again.
            try:
                from server.identity.keycloak_device import register_device
                register_device(session=session, server_id=self.state.server_id,
                                device_id=str(payload.get("device_id") or ""),
                                public_key=payload.get("public_key"))
            except Exception:
                if changed:
                    self.state.device_registry.revoke(device_id, username=username, public_key=public_key)
                raise
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device enrollment failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except Exception:
            json_response(self, {"success": False, "code": "keycloak_authorization_unavailable",
                                 "error": "Keycloak authorization is unavailable"}, 503)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        }, 201)

    def _may_enroll_device(self, session: dict[str, object]) -> bool:
        """Keep public login permission separate from internal device policy."""
        if not bool(getattr(self.state, "public_server", False)):
            # Organization-internal Managers do not inherit the public
            # server's role gate or its per-user auto-login allowlist.
            return True
        from server.identity.user_session import may_login_public_server
        return may_login_public_server(session)

    def _device_revoke(self) -> None:
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return
        try:
            payload = self._json_body(16 * 1024)
            device_id = str(payload.get("device_id") or "")
            records = self.state.device_registry.list(
                username=str(session["username"]),
                include_disabled=True,
            )
            record = next(
                (item for item in records if item.get("device_id") == device_id
                 and item.get("source_server_id") == self.state.server_id),
                None,
            )
            if record is None:
                raise PermissionError("device was not found")
            binding = self.state.device_registry.key_binding(username=str(session["username"]), device_id=device_id)
            if binding is None:
                raise PermissionError("device key was not found")
            from server.identity.keycloak_device import revoke_device
            revoke_device(session=session, server_id=self.state.server_id, device_id=device_id,
                          public_key=binding.get("public_key"))
            device = self.state.device_registry.revoke(device_id, username=str(session["username"]),
                                                       public_key=binding.get("public_key"))
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device revoke failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
            return
        except Exception:
            json_response(self, {"success": False, "code": "keycloak_authorization_unavailable",
                                 "error": "Keycloak authorization is unavailable"}, 503)
            return
        json_response(self, {
            "success": True,
            "device": device,
            "sync": self.state.device_registry.backend_status(),
        })

    def _device_challenge(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "HTTPS is required for device authentication",
            }, 400)
            return
        challenge_id, challenge = self.state.device_challenges.issue()
        json_response(self, {
            "success": True,
            "challenge_id": challenge_id,
            "challenge": base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("="),
            "expires_in": int(self.state.device_challenges.ttl_seconds),
        }, headers={"Cache-Control": "no-store"})

    def _device_verify(self) -> None:
        if not self._has_secure_ui_transport():
            json_response(self, {
                "success": False,
                "error": "HTTPS is required for device authentication",
            }, 400)
            return
        try:
            payload = self._json_body(64 * 1024)
            challenge = self.state.device_challenges.consume(
                payload.get("challenge_id"),
            )
            record = self.state.device_registry.verify(
                device_id=str(payload.get("device_id") or ""),
                public_key=payload.get("public_key"),
                challenge=challenge,
                signature=payload.get("signature"),
                last_seen_ip=observed_ip(self._client_ip()),
            )
            ticket = self.state.device_challenges.issue_device_login_ticket(
                username=str(record.get("username") or ""),
                device_id=str(record.get("device_id") or ""),
                origin=self._request_origin(),
                public_key=record.get("public_key"),
            )
            from server.identity.manager_oidc import _safe_next_path
            from urllib.parse import urlencode
            next_path = _safe_next_path(str(payload.get("next") or "/app"))
            login_url = "/auth/oidc/start?" + urlencode({
                "next": next_path,
                "device_ticket": ticket,
            })
            json_response(self, {
                "success": True,
                "requires_keycloak": True,
                "login_url": login_url,
                "device_id": record.get("device_id"),
            }, headers={"Cache-Control": "no-store"})
            return
        except ControlDatabaseError as exc:
            sys.stderr.write(f"[manager] device verification failed: {exc}\n")
            json_response(self, {
                "success": False,
                "error": "device registry is unavailable",
            }, 503)
            return
        except (
            DeviceRegistryError,
            PermissionError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            sys.stderr.write(
                f"[manager] device verification rejected: {type(exc).__name__}\n"
            )
            json_response(self, {
                "success": False,
                "error": "device is not approved",
            }, 403)
            return
