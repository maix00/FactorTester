"""Report download policy: one Markdown renderer for every report channel."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from server.manager.http.client_research_routes import ClientResearchRoutesMixin
from server.manager.http.public_research_routes import (
    PublicResearchRoutesMixin,
    _publication_identity,
)
from server.manager.services.research_export import (
    document_identity,
    front_matter,
    markdown_export,
)
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
        "profile_ref": "maxb", "branch_ref": "maxb-main",
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
    # The download says which branch it is and who wrote it.
    assert "- 分支：maxb-main" in body
    assert "- 作者：owner（profile: maxb）" in body
    assert "- 导出时间：" in body
    assert "报告版本 1" in body and "内容指纹" in body
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
        return {**_projection(), "profile_id": "maxa", "local_ref": local_ref}

    handler = _LocalHandler()
    handler.state = SimpleNamespace(
        client_state=SimpleNamespace(local_research_report=local_research_report),
    )
    assert handler._get_client_research_routes(urlparse(
        "/api/client/research/report-1%3Amain/export?format=md",
    ))
    assert calls == [(OWNER, "report-1:main")]
    assert handler.status == 200
    body = handler.wfile.getvalue().decode("utf-8")
    assert "# 引言" in body
    # The client copy names its branch, its owner and the profile that wrote it.
    assert "- 分支：main" in body
    assert "- 作者：owner（profile: maxa）" in body






def test_front_matter_carries_branch_author_time_and_versions():
    identity = document_identity(
        branch="maxb-main", owner="GTHT@MaxJJW@392452984564", profile="maxb",
        generation=12, revision="rev-7",
        projection_hash="667c08b03149f6ae5327c86d7f94d041",
        report_id="report:v1:OW3A", exported_at="2026-09-15T12:05:00+08:00",
    )
    assert front_matter(identity) == [
        "- 分支：maxb-main",
        "- 作者：MaxJJW（profile: maxb）",
        "- 导出时间：2026-09-15T12:05:00+08:00",
        "- 报告版本 12 · 分支版本 rev-7 · 内容指纹 667c08b03149"
        " · 报告 ID report:v1:OW3A",
    ]


def test_front_matter_degrades_when_identity_is_partial():
    # An unbound client profile still names the profile that wrote the branch.
    lines = front_matter(document_identity(profile="maxa"))
    assert lines[0] == "- 作者 profile：maxa"
    assert lines[1].startswith("- 导出时间：")
    # A document exported without identity keeps the plain report.
    raw, _, _ = markdown_export(_projection())
    assert raw.decode("utf-8").startswith("# 固收/久期:研究\n\n# 引言")


def test_markdown_export_writes_the_front_matter_below_the_title():
    raw, _, _ = markdown_export(
        _projection(),
        identity=document_identity(
            branch="maxb-main", owner="GTHT@MaxJJW@392452984564",
            profile="maxb", generation=2, exported_at="2026-09-15T12:05:00+08:00",
        ),
    )
    lines = raw.decode("utf-8").splitlines()
    assert lines[0] == "# 固收/久期:研究"
    assert lines[2] == "- 分支：maxb-main"
    assert lines[3] == ""
    assert "正文一句。" in raw.decode("utf-8")





def test_publication_identity_prefers_the_branch_registration():
    def branch_identity(publication_id):
        assert publication_id == "pub-1"
        return {
            "branch_id": "maxb-main", "principal_ref": "GTHT@MaxJJW@392452984564",
            "profile_ref": "maxb", "revision": "rev-7", "report_id": "report:v1:O",
        }

    def publication_metadata(_publication_id, _viewer=None):
        # The publication record alone names the publisher, not the writer.
        return {
            "owner_ref": "GTHT@other@9", "profile_ref": "other",
            "branch_ref": "other", "generation": 99,
        }

    identity = _publication_identity(
        SimpleNamespace(publication_metadata=publication_metadata),
        "pub-1",
        {"generation": 3, "projection_hash": "abc", "report_id": "report:v1:O"},
        SimpleNamespace(report_branch_identity=branch_identity),
    )
    assert identity["branch"] == "maxb-main"
    assert identity["owner"] == "GTHT@MaxJJW@392452984564"
    assert identity["profile"] == "maxb"
    assert identity["revision"] == "rev-7"
    # The exported content version wins over the record's own generation.
    assert identity["generation"] == 3


def test_publication_identity_falls_back_to_the_record():
    identity = _publication_identity(
        SimpleNamespace(publication_metadata=lambda _id, _viewer=None: {
            "owner_ref": "GTHT@owner@1", "profile_ref": "maxb", "branch_ref": "main",
        }),
        "pub-2",
        {"generation": 1, "report_id": "report:v1:P"},
    )
    assert identity["branch"] == "main"
    assert identity["owner"] == "GTHT@owner@1"
    assert identity["profile"] == "maxb"
    assert identity["revision"] == ""
