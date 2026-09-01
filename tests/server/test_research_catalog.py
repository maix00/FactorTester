from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from server.manager.http import research_catalog_routes, research_object_routes
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

    members = catalog.list_members(first["research_id"], viewer="alice")
    assert [(item["principal_ref"], item["profile_ref"]) for item in members] == [
        ("alice", "self"),
    ]
    assert catalog.list_researches(viewer="alice")[0]["research_id"] in {
        first["research_id"], second["research_id"],
    }


def test_existing_research_is_backfilled_with_owner_self_profile(tmp_path):
    db_path = tmp_path / "research.sqlite"
    catalog = ResearchCatalog(db_path)
    research = catalog.create_research(owner_ref="alice", title="旧研究")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM research_catalog_workspaces WHERE research_id=?",
            (research["research_id"],),
        )
        conn.execute(
            "DELETE FROM research_catalog_memberships WHERE research_id=?",
            (research["research_id"],),
        )

    restored = ResearchCatalog(db_path)
    members = restored.list_members(research["research_id"], viewer="alice")
    workspaces = restored.list_workspaces(research["research_id"], viewer="alice")
    assert [(item["principal_ref"], item["profile_ref"]) for item in members] == [
        ("alice", "self"),
    ]
    assert [(item["principal_ref"], item["profile_ref"]) for item in workspaces] == [
        ("alice", "self"),
    ]


def test_report_binding_and_its_research_drive_evidence_access(tmp_path):
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
    )
    assert member_access["can_view"] is True
    assert member_access["can_download"] is True

    report_access = catalog.resolve_evidence_access(
        evidence_ref=link["evidence_ref"], viewer="eve",
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


def test_research_and_report_can_share_with_dynamic_superior_chain(tmp_path):
    accounts = [
        {"username": "chief", "parent_username": "", "active": True},
        {"username": "boss", "parent_username": "chief", "active": True},
        {"username": "alice", "parent_username": "boss", "active": True},
        {"username": "eve", "parent_username": "", "active": True},
    ]
    catalog = ResearchCatalog(
        tmp_path / "research.sqlite", account_provider=lambda: accounts,
    )
    research = catalog.create_research(
        owner_ref="alice", title="上级共享研究", visibility="superiors",
    )
    assert catalog.get_research_summary(
        research["research_id"], viewer="boss",
    )["access"]["can_download"] is True
    assert catalog.get_research_summary(
        research["research_id"], viewer="chief",
    )["access"]["can_view"] is True
    with pytest.raises(PermissionError):
        catalog.get_research_summary(research["research_id"], viewer="eve")

    private_research = catalog.create_research(
        owner_ref="alice", title="私有研究", visibility="private",
    )
    report = catalog.register_report(
        private_research["research_id"], actor="alice",
        report_id="report-superiors", visibility="superiors",
    )
    shared = catalog.list_reports_for_scope(viewer="boss", scope="shared")
    assert shared[0]["report_id"] == report["report_id"]
    assert shared[0]["access"]["can_preview"] is True
    assert shared[0]["access"]["can_download"] is False


def test_owner_can_update_report_visibility_independently(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    report = catalog.register_report(
        research["research_id"], actor="alice", report_id="report-one",
    )
    updated = catalog.update_report(
        research["research_id"], report["report_id"], actor="alice",
        visibility="authorized", authorized_users=["bob"],
    )
    assert updated["visibility"] == "authorized"
    assert updated["authorized_users"] == ["bob"]
    assert catalog.get_research_summary(
        research["research_id"], viewer="alice",
    )["visibility"] == "private"


def test_owner_can_remove_report_and_profile_from_research(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(
        owner_ref="alice", title="研究", profile_ref="self",
    )
    workspace = catalog.list_workspaces(
        research["research_id"], viewer="alice",
    )[0]
    report = catalog.create_report_space(
        research["research_id"], actor="alice", title="第一份报告",
        profile_ref="self",
    )
    assert report["report_id"].startswith("report:v1:")
    assert report["workspace_id"] == workspace["workspace_id"]
    assert report["build_source"] == "workspace"

    removed_report = catalog.remove_report(
        research["research_id"], report["report_id"], actor="alice",
    )
    assert removed_report["status"] == "archived"
    assert catalog.list_reports(research["research_id"], viewer="alice") == []

    with pytest.raises(PermissionError, match="self Profile is a required member"):
        catalog.remove_membership(
            research["research_id"], profile_ref="self", actor="alice",
        )
    assert catalog.list_members(research["research_id"], viewer="alice")[0][
        "profile_ref"
    ] == "self"
    assert catalog.list_workspaces(research["research_id"], viewer="alice")[0][
        "profile_ref"
    ] == "self"

    removed_research = catalog.remove_research(
        research["research_id"], actor="alice",
    )
    assert removed_research["status"] == "archived"
    assert catalog.list_researches(viewer="alice") == []


def test_share_links_grant_target_without_exposing_plain_token(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    report = catalog.register_report(
        research["research_id"], actor="alice", report_id="report-one",
    )
    link = catalog.create_share_link(
        target_kind="report", research_id=research["research_id"],
        report_id=report["report_id"], actor="alice", mode="one_time",
    )
    grant = catalog.redeem_share_link(link["token"], actor="bob")
    assert grant["report_id"] == report["report_id"]
    assert catalog.list_reports_for_scope(viewer="bob", scope="shared")[0][
        "access"
    ]["can_download"] is False
    with pytest.raises(PermissionError, match="already been redeemed"):
        catalog.redeem_share_link(link["token"], actor="carol")
    assert link["token"] not in (tmp_path / "research.sqlite").read_bytes().decode(
        "utf-8", errors="ignore",
    )


def test_permanent_share_link_can_be_redeemed_by_multiple_users(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    link = catalog.create_share_link(
        target_kind="research", research_id=research["research_id"],
        actor="alice", mode="permanent",
    )
    catalog.redeem_share_link(link["token"], actor="bob")
    catalog.redeem_share_link(link["token"], actor="carol")
    assert catalog.get_research_summary(
        research["research_id"], viewer="bob",
    )["access"]["can_download"] is True
    assert catalog.get_research_summary(
        research["research_id"], viewer="carol",
    )["access"]["can_download"] is True
    listed = catalog.list_share_links(research["research_id"], actor="alice")
    assert listed[0]["link_id"] == link["link_id"]
    revoked = catalog.revoke_share_link(
        research["research_id"], link["link_id"], actor="alice",
    )
    assert revoked["revoked_at"] > 0
    with pytest.raises(KeyError, match="share link not found"):
        catalog.redeem_share_link(link["token"], actor="dave")


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

    assert detail["can_delete"] is False
    assert detail["reports"][0]["can_delete"] is False
    with pytest.raises(PermissionError, match="source server"):
        catalog.remove_report(
            research_id, "server-report-1", actor="alice",
        )
    with pytest.raises(PermissionError, match="source server"):
        catalog.update_research(
            research_id, actor="alice", status="archived",
        )


def test_publication_migration_restores_legacy_private_projection_to_superiors(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    result = catalog.migrate_reports([{
        "source_kind": "publication", "source_ref": "publication-one",
        "owner_ref": "alice", "report_id": "report-one", "title": "共享报告",
        "visibility": "private",
    }], actor="alice")
    research_id = result["items"][0]["research_id"]
    assert catalog.get_research_summary(
        research_id, viewer="alice",
    )["visibility"] == "superiors"
    assert catalog.list_reports(research_id, viewer="alice")[0][
        "visibility"
    ] == "superiors"


def test_report_branches_and_replicas_migrate_into_one_research(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    records = [{
        "source_kind": "client", "source_ref": "maxa:package:branch-a",
        "owner_ref": "alice", "report_id": "legacy-branch-report-a",
        "record_id": "package", "title": "动量研究",
        "profile_ref": "maxa", "build_source": "client",
    }, {
        "source_kind": "server_agent", "source_ref": "maxa:package:branch-b",
        "owner_ref": "alice", "report_id": "legacy-branch-report-b",
        "work_package_id": "package", "title": "动量研究",
        "profile_ref": "maxa", "build_source": "server_agent",
    }, {
        "source_kind": "publication", "source_ref": "publication-1",
        "owner_ref": "alice", "report_id": "legacy-branch-report-b",
        "title": "动量研究", "profile_ref": "maxa",
        "build_source": "server_agent",
    }]

    result = catalog.migrate_reports(records, actor="alice")

    assert result["counts"]["migrated"] == 3
    assert len({item["research_id"] for item in result["items"]}) == 1
    assert len({item["report_id"] for item in result["items"]}) == 1
    researches = catalog.list_researches(viewer="alice")
    assert len(researches) == 1
    assert researches[0]["title"] == "动量研究"
    assert researches[0]["visibility"] == "superiors"
    assert len(catalog.list_reports(researches[0]["research_id"], viewer="alice")) == 1


def test_legacy_evidence_link_schema_requires_explicit_migration(tmp_path):
    database = tmp_path / "research.sqlite"
    import sqlite3
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE research_catalog_evidence_links(link_ref TEXT)")

    with pytest.raises(RuntimeError, match="explicit Report-Evidence"):
        ResearchCatalog(database)


def test_canonical_report_scope_inherits_research_membership_and_keeps_research_metadata(
    tmp_path,
):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(
        owner_ref="alice", title="协作研究", visibility="private",
    )
    catalog.add_membership(
        research["research_id"],
        actor="alice",
        principal_ref="bob",
        profile_ref="bob-profile",
        role="viewer",
    )
    catalog.register_report(
        research["research_id"],
        actor="alice",
        report_id="report-private",
        title="协作报告",
        visibility="private",
    )

    reports = catalog.list_reports_for_scope(
        viewer="bob", scope="shared",
    )
    assert len(reports) == 1
    assert reports[0]["title"] == "协作报告"
    assert reports[0]["research"] == {
        "research_id": research["research_id"],
        "title": "协作研究",
        "owner_ref": "alice",
        "status": "active",
        "visibility": "private",
    }
    assert reports[0]["access"]["access_basis"] == "research"
    assert reports[0]["access"]["can_download"] is True
    assert catalog.list_reports_for_scope(
        viewer="bob", scope="mine",
    ) == []


def test_report_only_visibility_does_not_inherit_research_download_access(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(
        owner_ref="alice", title="内部研究", visibility="private",
    )
    report = catalog.register_report(
        research["research_id"],
        actor="alice",
        report_id="report-public",
        title="公开报告",
        visibility="public",
    )
    reports = catalog.list_reports_for_scope(viewer="eve", scope="shared")
    assert reports[0]["report_id"] == report["report_id"]
    assert reports[0]["access"]["access_basis"] == "report"
    assert reports[0]["access"]["can_preview"] is True
    assert reports[0]["access"]["can_download"] is False


def test_report_relationship_requires_catalog_workspace_and_active_profile(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    first = catalog.create_research(
        owner_ref="alice", title="第一个研究", profile_ref="self",
    )
    second = catalog.create_research(owner_ref="alice", title="第二个研究")
    workspace = first["workspaces"][0]

    with pytest.raises(ValueError, match="does not belong"):
        catalog.register_report(
            second["research_id"], actor="alice", report_id="wrong-research",
            workspace_id=workspace["workspace_id"],
        )
    with pytest.raises(ValueError, match="active research member"):
        catalog.register_report(
            second["research_id"], actor="alice", report_id="missing-member",
            profile_ref="other-profile",
        )


def test_evidence_link_requires_active_report_in_same_research(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    first = catalog.create_research(owner_ref="alice", title="第一个研究")
    second = catalog.create_research(owner_ref="alice", title="第二个研究")
    report = catalog.register_report(
        first["research_id"], actor="alice", report_id="report-1",
    )

    with pytest.raises(ValueError, match="report_id is required"):
        catalog.link_evidence(
            first["research_id"], actor="alice",
            evidence_ref="evidence:job:sha256:" + "d" * 64,
        )
    with pytest.raises(ValueError, match="does not belong"):
        catalog.link_evidence(
            second["research_id"], actor="alice",
            evidence_ref="evidence:job:sha256:" + "e" * 64,
            report_id=report["report_id"],
        )


def test_canonical_report_route_returns_bounded_catalog_projection(monkeypatch, tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    catalog.register_report(
        research["research_id"],
        actor="alice",
        report_id="report-1",
        title="报告 1",
        visibility="public",
    )
    responses = []

    class Handler(research_catalog_routes.ResearchCatalogRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)

        def _session(self):
            return {"username": "eve"}

        def _subordinate_users(self, _viewer):
            return []

    monkeypatch.setattr(
        research_catalog_routes,
        "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )
    handled = Handler()._get_research_catalog_routes(SimpleNamespace(
        path="/api/research/reports", query="scope=shared",
    ))

    assert handled is True
    assert responses[0][1] == 200
    assert responses[0][0]["scope"] == "shared"
    assert responses[0][0]["count"] == 1
    assert responses[0][0]["reports"][0]["research"]["title"] == "研究"


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
        query="",
    ))

    assert handled is True
    assert responses[0][1] == 200
    assert responses[0][0]["evidence"]["owner"] == "alice"
    assert responses[0][0]["access"]["can_preview"] is True
    assert responses[0][0]["access"]["can_download"] is False


def test_evidence_summary_route_uses_same_report_access(
    monkeypatch, tmp_path,
):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    research = catalog.create_research(owner_ref="alice", title="研究")
    report = catalog.register_report(
        research["research_id"], actor="alice",
        report_id="report-public", visibility="public",
    )
    evidence_ref = "evidence:job:sha256:" + "d" * 64
    catalog.link_evidence(
        research["research_id"], actor="alice",
        evidence_ref=evidence_ref, evidence_owner_ref="alice",
        report_id=report["report_id"],
    )
    responses = []

    class Handler(research_object_routes.ResearchObjectRoutesMixin):
        state = SimpleNamespace(research_catalog=catalog)

        def _session(self):
            return {"username": "eve"}

    monkeypatch.setattr(
        research_object_routes, "get_evidence_summary",
        lambda *, owner, evidence_ref: {
            "owner": owner, "evidence_ref": evidence_ref,
        },
    )
    monkeypatch.setattr(
        research_object_routes, "json_response",
        lambda _handler, value, status=200: responses.append((value, status)),
    )

    handled = Handler()._get_evidence_route(SimpleNamespace(
        path=(
            "/api/research-evidence/catalog/"
            + quote(evidence_ref, safe="") + "/summary"
        ),
        query="",
    ))

    assert handled is True
    assert responses[0][0]["evidence"]["owner"] == "alice"
    assert responses[0][0]["access"]["access_basis"] == "report"
    assert responses[0][0]["access"]["can_download"] is False
