"""Manager-owned Research Graph catalog and user-file storage seam.

This adapter deliberately imports only the catalog pieces of the legacy
Research Graph package: immutable versions, localized presentations, YAML
export, and the owner-scoped user library.  It never imports branch,
evidence, trial-plan, or Agent runtime services.

The underlying SQLite tables remain compatible with the existing Flask
service during the migration.  The Manager is the new HTTP owner of these
catalog operations; the old service routes are kept only for released
clients that have not moved to the ``/api/catalog`` namespace yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import settings as Settings

from server.services.research_graph import active_pointer
from server.services.research_graph import presentations
from server.services.research_graph import user_graph_preferences
from server.services.research_graph import user_graphs
from server.services.research_graph import versions
from server.services.research_graph.presentation_contract import (
    normalize_graph_locale,
)
from server.services.research_graph.yaml_export import (
    graph_yaml_bytes,
    graph_yaml_filename,
)
from tools.data.sqlite.db import connect_sqlite


class ResearchGraphCatalog:
    """Expose only server-provided Graph catalog data to Manager routes."""

    def __init__(self, db_path: str | Path, *, server_id: str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.server_id = str(server_id or "local").strip() or "local"
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """Create catalog tables without initializing the research runtime."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect_sqlite(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_graph_versions (
                    graph_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    lifecycle TEXT NOT NULL,
                    parent_version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (graph_id, version),
                    UNIQUE (graph_id, content_hash)
                );
                CREATE TABLE IF NOT EXISTS active_research_graphs (
                    graph_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    activated_by TEXT NOT NULL,
                    activated_at REAL NOT NULL
                );
                """
            )
            presentations.create_schema(conn)
            user_graphs.create_schema(conn)

    def _assert_configured_database(self) -> None:
        """Prevent the compatibility functions from silently using another DB."""
        configured = Path(Settings.CACHE_DB_PATH).expanduser().resolve()
        if configured != self.db_path:
            raise RuntimeError(
                "Manager Graph catalog database differs from configured SQLite"
            )

    @staticmethod
    def _locale(value: object) -> str | None:
        raw = str(value or "").strip()
        return normalize_graph_locale(raw) if raw else None

    def list_versions(
        self, graph_id: str, *, locale: object = None,
    ) -> list[dict[str, Any]]:
        self._assert_configured_database()
        return versions.list_graph_versions(
            graph_id=str(graph_id), locale=self._locale(locale),
        )

    def active_graph(
        self, graph_id: str, *, locale: object = None,
    ) -> dict[str, Any] | None:
        self._assert_configured_database()
        return active_pointer.load_active_graph(
            graph_id=str(graph_id), locale=self._locale(locale),
        )

    def graph(self, graph_id: str, version: int) -> dict[str, Any] | None:
        self._assert_configured_database()
        return versions.load_graph(
            graph_id=str(graph_id), version=int(version),
        )

    def presentations(self, graph_id: str, version: int) -> list[dict[str, Any]]:
        self._assert_configured_database()
        return presentations.list_presentations(
            graph_id=str(graph_id), version=int(version),
        )

    def register_presentation(
        self,
        graph_id: str,
        version: int,
        presentation: dict[str, Any],
        *,
        actor: str,
    ) -> dict[str, Any]:
        self._assert_configured_database()
        graph = self.graph(graph_id, version)
        if graph is None:
            raise KeyError("graph version not found")
        return presentations.register_presentation(
            graph,
            presentation,
            actor=str(actor),
        )

    def presentation(
        self, graph_id: str, version: int, locale: object,
    ) -> dict[str, Any] | None:
        self._assert_configured_database()
        return presentations.load_presentation(
            graph_id=str(graph_id),
            version=int(version),
            locale=normalize_graph_locale(locale),
        )

    def yaml_download(
        self,
        graph_id: str,
        version: int,
        *,
        locale: object = None,
    ) -> tuple[bytes, str, dict[str, Any], dict[str, Any] | None]:
        graph = self.graph(graph_id, version)
        if graph is None:
            raise KeyError("research graph version not found")
        presentation = None
        normalized_locale = self._locale(locale)
        if normalized_locale is not None:
            presentation = self.presentation(graph_id, version, normalized_locale)
            if presentation is None:
                raise LookupError(
                    "research graph presentation is not published for locale "
                    f"{normalized_locale}"
                )
        return (
            graph_yaml_bytes(graph, presentation=presentation),
            graph_yaml_filename(graph, presentation=presentation),
            graph,
            presentation,
        )

    def register_graph(self, graph: dict[str, Any], *, actor: str) -> dict[str, Any]:
        self._assert_configured_database()
        return versions.register_graph(graph, actor=str(actor))

    def activate_graph(
        self, graph_id: str, version: int, *, actor: str,
    ) -> dict[str, Any]:
        self._assert_configured_database()
        return active_pointer.activate_graph(
            graph_id=str(graph_id),
            source_version=int(version),
            actor=str(actor),
        )

    def list_user_graphs(self, owner: str) -> list[dict[str, Any]]:
        self._assert_configured_database()
        return user_graphs.list_graphs(owner=str(owner))

    def upload_user_graph(
        self,
        *,
        owner: str,
        filename: str,
        raw_yaml: bytes | str,
        name: str = "",
    ) -> dict[str, Any]:
        self._assert_configured_database()
        return user_graphs.upload_graph(
            owner=str(owner),
            filename=str(filename),
            raw_yaml=raw_yaml,
            name=str(name),
        )

    def load_user_graph(
        self, owner: str, graph_file_id: str,
    ) -> dict[str, Any] | None:
        self._assert_configured_database()
        return user_graphs.load_graph_file(
            owner=str(owner), graph_file_id=str(graph_file_id),
        )

    def delete_user_graph(self, owner: str, graph_file_id: str) -> bool:
        self._assert_configured_database()
        return user_graphs.delete_graph(
            owner=str(owner), graph_file_id=str(graph_file_id),
        )

    def default_user_graph(self, owner: str) -> dict[str, Any] | None:
        self._assert_configured_database()
        return user_graph_preferences.get_default(owner=str(owner))

    def set_default_user_graph(
        self,
        *,
        owner: str,
        kind: str,
        graph_file_id: str = "",
        graph_id: str = "",
        version: int = 0,
    ) -> dict[str, Any] | None:
        self._assert_configured_database()
        return user_graph_preferences.set_default(
            owner=str(owner),
            kind=str(kind),
            graph_file_id=str(graph_file_id),
            graph_id=str(graph_id),
            version=int(version),
        )


__all__ = ["ResearchGraphCatalog"]
