"""Report download policy: one Markdown renderer for every report channel."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http.client_research_routes import ClientResearchRoutesMixin
from server.manager.http.public_research_routes import PublicResearchRoutesMixin
from server.manager.services.research_export import markdown_export
from tools.cli.release.research_reporting.public_research.library import (
    PublicResearchLibrary,
)

OWNER = "GTHT@owner@1"


def _projection() -> dict:
    return {
        "schema_version": 2, "report_id": "report-one",
        "title": "固收/久期:研究", "generation": 1, "projection_hash": "hash",
        "assets": [],
        "components": [
            {"component_id": "intro", "kind": "chapter", "parent_id": None,
             "title": "引言", "body": "正文一句。", "content": None},
            {"component_id": "points", "kind": "list", "parent_id": "intro",
             "title": "", "body": "",
             "content": {"style": "bullet",
                         "items": [{"depth": 0, "text": "要点一"}]}},
            {"component_id": "table", "kind": "entry", "parent_id": "intro",
             "title": "数据表", "body": "",
             "content": {"columns": ["a", "b"], "rows": [["1", "2"]]}},
        ],
    }


class _BaseHandler:
    def __init__(self):
        self.headers: list[tuple] = []
        self.status: int | None = None
        self.wfile = BytesIO()

    def _session(self):
        return {"username": OWNER}

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        self.headers.append(args)

    def end_headers(self):
        pass


class _PublicHandler(PublicResearchRoutesMixin, _BaseHandler):
    pass


class _LocalHandler(ClientResearchRoutesMixin, _BaseHandler):
    pass


def test_markdown_export_renders_a_projection():
    raw, content_type, filename = markdown_export(_projection())
    text = raw.decode("utf-8")
    assert text.startswith("# 固收/久期:研究")
    assert "# 引言" in text
    assert "正文一句。" in text
    assert "- 要点一" in text
    assert "| a | b |" in text
    assert content_type == "text/markdown; charset=utf-8"
    # The title's separators are dropped from the download name.
    assert filename == "固收久期研究.md"


def test_markdown_export_refuses_pdf_for_the_client_renderer():
    with pytest.raises(NotImplementedError, match="客户端"):
        markdown_export(_projection(), "pdf")


def test_publication_export_route_streams_markdown(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    publication = library.sync({
        "report_id": "report-one", "owner_ref": OWNER,
        "projection": _projection(),
    })["publication_id"]
    handler = _PublicHandler()
    handler.state = SimpleNamespace(public_research=library)
    assert handler._get_public_research_routes(urlparse(
        f"/api/public-research/{publication}/export?format=md",
    ))
    assert handler.status == 200
    body = handler.wfile.getvalue().decode("utf-8")
    assert "# 引言" in body and "要点一" in body
    disposition = dict(handler.headers)["Content-Disposition"]
    assert disposition.startswith("attachment; ")
    assert "filename*=UTF-8''" in disposition


def test_publication_export_route_maps_pdf_to_501(tmp_path):
    library = PublicResearchLibrary(tmp_path / "public-research")
    publication = library.sync({
        "report_id": "report-one", "owner_ref": OWNER,
        "projection": _projection(),
    })["publication_id"]
    handler = _PublicHandler()
    handler.state = SimpleNamespace(public_research=library)
    assert handler._get_public_research_routes(urlparse(
        f"/api/public-research/{publication}/export?format=pdf",
    ))
    assert handler.status == 501


def test_local_export_route_uses_the_same_renderer():
    calls = []

    def local_research_report(principal, local_ref):
        calls.append((principal, local_ref))
        return _projection()

    handler = _LocalHandler()
    handler.state = SimpleNamespace(
        client_state=SimpleNamespace(local_research_report=local_research_report),
    )
    assert handler._get_client_research_routes(urlparse(
        "/api/client/research/report-1%3Amain/export?format=md",
    ))
    assert calls == [(OWNER, "report-1:main")]
    assert handler.status == 200
    assert "# 引言" in handler.wfile.getvalue().decode("utf-8")



