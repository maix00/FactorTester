from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import quote

from server.manager.http import research_object_routes
from server.manager.services.research_catalog import ResearchCatalog


def test_research_catalog_keeps_research_and_profile_workspaces_distinct(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")

    first = catalog.create_research(
        owner_ref="alice", title="第一个研究", profile_ref="self",
    )
    second = catalog.create_research(
        owner_ref="alice", title="第二个研究", profile_ref="self",
    )
    assert first["research_id"] != second["research_id"]

    workspace = catalog.create_workspace(
        first["research_id"],
        actor="alice",
        principal_ref="alice",
        profile_ref="self",
        title="第一个研究 / self",
    )
    assert workspace["research_id"] == first["research_id"]
    assert catalog.create_workspace(
        first["research_id"],
        actor="alice",
        principal_ref="alice",
        profile_ref="self",
    )["workspace_id"] == workspace["workspace_id"]


def test_research_and_report_visibility_drive_evidence_access(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    catalog.add_membership(
        research["research_id"],
        actor="alice",
        principal_ref="bob",
        profile_ref="bob-profile",
        role="viewer",
    )
    report = catalog.register_report(
        research["research_id"],
        actor="alice",
        report_id="report-public",
        title="公开报告",
        visibility="public",
    )
    link = catalog.link_evidence(
        research["research_id"],
        actor="alice",
        evidence_ref="evidence:job:sha256:" + "a" * 64,
        report_id=report["report_id"],
        evidence_owner_ref="alice",
    )

    owner_access = catalog.resolve_evidence_access(
        evidence_ref=link["evidence_ref"], viewer="alice",
    )
    assert owner_access["can_download"] is True
    assert owner_access["can_manage"] is True
    assert owner_access["access_basis"] == "owner"

    member_access = catalog.resolve_evidence_access(
        evidence_ref=link["evidence_ref"], viewer="bob",
        research_id=research["research_id"],
    )
    assert member_access["can_view"] is True
    assert member_access["can_download"] is True

    report_access = catalog.resolve_evidence_access(
        evidence_ref=link["evidence_ref"], viewer="eve",
        report_id=report["report_id"],
    )
    assert report_access["can_view"] is True
    assert report_access["can_preview"] is True
    assert report_access["can_download"] is False
    assert report_access["access_basis"] == "report"


def test_archived_research_is_hidden_from_non_owner_and_hides_authorized_users(
    tmp_path,
):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(
        owner_ref="alice",
        title="内部研究",
        visibility="authorized",
        authorized_users=["bob"],
    )
    assert catalog.list_researches(viewer="bob")[0]["authorized_users"] == []

    catalog.update_research(
        research["research_id"], actor="alice", status="archived",
    )
    assert catalog.list_researches(viewer="bob", include_archived=True) == []
    assert catalog.list_researches(viewer="alice", include_archived=True)[0][
        "status"
    ] == "archived"


def test_report_migration_is_explicit_and_idempotent(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    record = {
        "source_kind": "server_report",
        "source_ref": "server-report-1",
        "owner_ref": "alice",
        "report_id": "server-report-1",
        "title": "旧报告",
        "profile_ref": "self",
        "build_source": "server_agent",
        "visibility": "private",
        "evidence_refs": ["evidence:job:sha256:" + "b" * 64],
    }

    first = catalog.migrate_reports([record], actor="alice")
    second = catalog.migrate_reports([record], actor="alice")
    assert first["counts"]["migrated"] == 1
    assert second["counts"]["already_migrated"] == 1
    research_id = first["items"][0]["research_id"]
    detail = catalog.get_research(research_id, viewer="alice")
    assert detail["title"] == "旧报告"
    assert detail["reports"][0]["report_id"] == "server-report-1"
    assert detail["evidence_links"][0]["evidence_ref"].startswith("evidence:job:")


def test_evidence_detail_route_uses_research_access_for_report_preview(
    monkeypatch, tmp_path,
):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    report = catalog.register_report(
        research["research_id"],
        actor="alice",
        report_id="report-public",
        visibility="public",
    )
    evidence_ref = "evidence:job:sha256:" + "c" * 64
    catalog.link_evidence(
        research["research_id"],
        actor="alice",
        evidence_ref=evidence_ref,
        evidence_owner_ref="alice",
        report_id=report["report_id"],
    )
    responses = []

    class Handler(research_object_routes.ResearchObjectRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)

        def _session(self):
            return {"username": "eve"}

    monkeypatch.setattr(
        research_object_routes,
        "get_evidence",
        lambda *, owner, evidence_ref: {
            "owner": owner, "evidence_ref": evidence_ref,
        },
    )
    monkeypatch.setattr(
        research_object_routes,
        "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    handled = Handler()._get_evidence_route(SimpleNamespace(
        path="/api/research-evidence/" + quote(evidence_ref, safe=""),
        query="report_id=" + quote(report["report_id"], safe=""),
    ))

    assert handled is True
    assert responses[0][1] == 200
    assert responses[0][0]["evidence"]["owner"] == "alice"
    assert responses[0][0]["access"]["can_preview"] is True
    assert responses[0][0]["access"]["can_download"] is False
