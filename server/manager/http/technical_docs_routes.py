"""Public technical-document read API."""

from urllib.parse import unquote

from server.manager.http.responses import json_response


class TechnicalDocsRoutesMixin:
    def _get_technical_docs_routes(self, parsed) -> bool:
        if parsed.path == "/docs" or parsed.path.startswith("/docs/"):
            return self._get_session_and_shell_routes(parsed)
        if parsed.path == "/api/docs/index":
            return self._send_technical_docs(lambda: self.state.technical_docs.index())
        prefix = "/api/docs/pages/"
        if parsed.path.startswith(prefix):
            slug = unquote(parsed.path.removeprefix(prefix)).strip("/")
            return self._send_technical_docs(lambda: self.state.technical_docs.page(slug))
        return False

    def _send_technical_docs(self, load) -> bool:
        try:
            payload = load()
        except KeyError:
            json_response(self, {"success": False, "error": "document not found"}, 404)
        except (OSError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
        else:
            json_response(self, payload, headers={"Cache-Control": "public, max-age=60"})
        return True
