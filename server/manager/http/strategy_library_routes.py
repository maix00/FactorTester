"""HTTP routes for the canonical Strategy library domain."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response
from server.services.strategy_library import StrategyLibraryService


STRATEGY_LIBRARY_PREFIX = "/api/strategy-library"


class StrategyLibraryRoutesMixin:
    """Keep Strategy CRUD out of the product/factor catalog dispatcher."""

    def _strategy_library_service(self) -> StrategyLibraryService:
        return self.state.strategy_library

    def _serve_strategy_library(self, parsed, *, method: str) -> bool:
        if not parsed.path.startswith(STRATEGY_LIBRARY_PREFIX):
            return False
        session = self._session()
        if session is None:
            json_response(self, {"success": False, "error": "login required"}, 401)
            return True
        principal = str(session.get("username") or "").strip()
        parts = [unquote(item) for item in parsed.path.split("/") if item]
        # api / strategy-library / strategies / ...
        if len(parts) < 3 or parts[:3] != ["api", "strategy-library", "strategies"]:
            json_response(self, {"success": False, "error": "strategy library route not found"}, 404)
            return True
        try:
            service = self._strategy_library_service()
            if method == "GET":
                value = self._strategy_library_get(
                    service, parts[3:], principal,
                    parse_qs(parsed.query, keep_blank_values=True),
                )
                json_response(self, value)
                return True
            payload = (
                {key: values[0] for key, values in parse_qs(
                    parsed.query, keep_blank_values=True,
                ).items() if values}
                if method == "DELETE" else self._json_body(2 * 1024 * 1024)
            )
            value, status = self._strategy_library_write(
                service, method, parts[3:], principal, payload,
            )
            json_response(self, value, status)
            return True
        except PermissionError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 403)
        except KeyError as exc:
            json_response(self, {"success": False, "error": str(exc)}, 404)
        except (TypeError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 400)
        except (OSError, RuntimeError) as exc:
            json_response(self, {"success": False, "error": "strategy library is unavailable"}, 503)
        return True

    @staticmethod
    def _strategy_library_get(
        service: StrategyLibraryService,
        tail: list[str],
        principal: str,
        query: dict[str, list[str]],
    ) -> dict:
        if not tail:
            return service.list(
                principal=principal,
                scope=str(query.get("scope", ["mine"])[0] or "mine"),
                page=int(query.get("page", [1])[0] or 1),
                limit=int(query.get("limit", [20])[0] or 20),
                query=str(query.get("query", [""])[0] or ""),
            )
        strategy_ref = tail[0]
        if len(tail) == 1:
            return service.get(strategy_ref, principal=principal)
        if tail[1] == "revisions":
            if len(tail) == 2:
                value = service.get(strategy_ref, principal=principal)
                return {
                    "success": True,
                    "strategy_ref": strategy_ref,
                    "revisions": value["strategy"]["revisions"],
                }
            if len(tail) == 3:
                return service.get_revision(strategy_ref, tail[2], principal=principal)
        if tail[1] == "shares" and len(tail) == 2:
            return service.shares(strategy_ref, principal=principal)
        raise KeyError("strategy library route not found")

    @staticmethod
    def _strategy_library_write(
        service: StrategyLibraryService,
        method: str,
        tail: list[str],
        principal: str,
        payload: dict,
    ) -> tuple[dict, int]:
        if method == "POST" and not tail:
            return service.create(payload, principal=principal), 201
        if not tail:
            raise KeyError("strategy library route not found")
        strategy_ref = tail[0]
        if method in {"PATCH", "PUT"} and len(tail) == 1:
            return service.update(strategy_ref, payload, principal=principal), 200
        if method == "DELETE" and len(tail) == 1:
            return service.delete(strategy_ref, principal=principal), 200
        if len(tail) == 2 and tail[1] == "visibility" and method in {"PATCH", "PUT"}:
            return service.update(
                strategy_ref, {"visibility": payload.get("visibility")},
                principal=principal,
            ), 200
        if len(tail) == 2 and tail[1] == "shares" and method == "POST":
            target = payload.get("principal_ref") or payload.get("username")
            return service.grant(strategy_ref, str(target or ""), principal=principal), 200
        if len(tail) == 3 and tail[1] == "shares" and method == "DELETE":
            return service.revoke(strategy_ref, tail[2], principal=principal), 200
        raise KeyError("strategy library route not found")
