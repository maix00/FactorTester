"""Public technical-document read API."""

from urllib.parse import parse_qs, unquote

from server.manager.http.responses import json_response


class TechnicalDocsRoutesMixin:
    def _get_technical_docs_routes(self, parsed) -> bool:
        if parsed.path == "/docs" or parsed.path.startswith("/docs/"):
            return self._get_session_and_shell_routes(parsed)
        if parsed.path == "/api/docs/index":
            return self._send_technical_docs(lambda: self.state.technical_docs.index())
        if parsed.path == "/api/docs/test-fields":
            return self._send_test_field_catalog(parsed)
        prefix = "/api/docs/pages/"
        if parsed.path.startswith(prefix):
            slug = unquote(parsed.path.removeprefix(prefix)).strip("/")
            return self._send_technical_docs(lambda: self.state.technical_docs.page(slug))
        return False

    def _send_test_field_catalog(self, parsed) -> bool:
        """Serve a paged projection generated from registered test fields."""
        values = parse_qs(parsed.query, keep_blank_values=True)
        query = str(values.get("query", [""])[0] or "").strip().casefold()
        application = str(values.get("application", [""])[0] or "").strip()
        role = str(values.get("role", [""])[0] or "").strip().lower()
        client = str(values.get("client", ["web"])[0] or "web").strip().lower()
        try:
            page = max(1, int(values.get("page", ["1"])[0] or 1))
            page_size = min(
                100, max(1, int(values.get("page_size", ["20"])[0] or 20)),
            )
        except (TypeError, ValueError):
            json_response(
                self,
                {"success": False, "error": "invalid field catalog paging"},
                400,
            )
            return True
        if role not in {"", "setting", "run"}:
            json_response(
                self,
                {"success": False, "error": "invalid field catalog role"},
                400,
            )
            return True
        if client not in {"web", "swift", "cli"}:
            json_response(
                self,
                {"success": False, "error": "invalid field catalog client"},
                400,
            )
            return True

        def load() -> dict[str, object]:
            fields = self.state.technical_docs.test_field_catalog(client=client)
            filtered = [
                field for field in fields
                if (not application or str(field.get("application")) == application)
                and (not role or str(field.get("role")) == role)
                and (
                    not query
                    or query in " ".join(
                        str(field.get(key) or "")
                        for key in (
                            "application", "role", "field_path", "key", "label",
                            "module", "tab_label",
                        )
                    ).casefold()
                )
            ]
            filtered.sort(key=lambda item: (
                str(item.get("application") or ""),
                str(item.get("role") or ""),
                str(item.get("key") or ""),
            ))
            total = len(filtered)
            total_pages = max(1, (total + page_size - 1) // page_size)
            current_page = min(page, total_pages)
            start = (current_page - 1) * page_size
            return {
                "success": True,
                "schema_version": 1,
                "source": "registered-test-settings",
                "client": client,
                "page": current_page,
                "page_size": page_size,
                "total": total,
                "applications": sorted({
                    str(field.get("application") or "") for field in fields
                } - {""}),
                "clients": ["web", "swift", "cli"],
                "roles": ["setting", "run"],
                "fields": filtered[start:start + page_size],
            }

        return self._send_technical_docs(load)

    def _send_technical_docs(self, load) -> bool:
        try:
            payload = load()
        except KeyError:
            json_response(self, {"success": False, "error": "document not found"}, 404)
        except (ImportError, OSError, ValueError) as exc:
            json_response(self, {"success": False, "error": str(exc)}, 503)
        else:
            json_response(self, payload, headers={"Cache-Control": "public, max-age=60"})
        return True
