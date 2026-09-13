from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli


class FakeResearchClient:
    def __init__(self) -> None:
        self.created = None
        self.removed_report = None
        self.removed_profile = None
        self.removed_research = None

    def create_research_report(self, research_id, payload):
        self.created = (research_id, payload)
        return {"report_id": "report:v1:new", "research_id": research_id,
                "workspace_id": "workspace-one", "owner_ref": "alice", **payload}

    def remove_research_report(self, research_id, report_id):
        self.removed_report = (research_id, report_id)
        return {"report_id": report_id, "status": "archived"}

    def remove_research_member(self, research_id, profile_ref):
        self.removed_profile = (research_id, profile_ref)
        return {"profile_ref": profile_ref, "status": "revoked"}

    def remove_research(self, research_id):
        self.removed_research = research_id
        return {"research_id": research_id, "status": "archived"}


def test_research_cli_exposes_report_spaces_without_link_command(monkeypatch, tmp_path):
    from tools.cli.release.local_profile import LocalProfileStore
    from tools.cli.release.local_profile_contracts import new_local_profile
    monkeypatch.setenv("FACTORTESTER_CLIENT_ROOT", str(tmp_path / "client"))
    LocalProfileStore(tmp_path / "client").save(new_local_profile(
        profile_id="self", display_name="self", workspace_root=tmp_path / "workspace", principal_ref="alice",
    ))
    fake = FakeResearchClient()
    monkeypatch.setattr(
        "tools.cli.commands.research_catalog.client_from_config", lambda: fake,
    )
    runner = CliRunner()

    help_result = runner.invoke(cli, ["research", "--help"])
    created = runner.invoke(cli, [
        "research", "report-create", "research:v1:one",
        "--title", "报告一", "--profile", "self",
    ])
    removed = runner.invoke(cli, [
        "research", "report-remove", "research:v1:one", "report:v1:new",
    ])
    member = runner.invoke(cli, [
        "research", "member-remove", "research:v1:one", "--profile", "self",
    ])
    research_removed = runner.invoke(cli, [
        "research", "remove", "research:v1:one",
    ])

    assert help_result.exit_code == 0
    assert "report-create" in help_result.output
    assert "report-remove" in help_result.output
    assert "report-link" not in help_result.output
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["report_id"] == "report:v1:new"
    assert fake.created == ("research:v1:one", {
        "title": "报告一", "profile_ref": "self",
        "visibility": "private", "authorized_users": [],
    })
    assert removed.exit_code == 0, removed.output
    assert fake.removed_report == ("research:v1:one", "report:v1:new")
    assert member.exit_code == 0, member.output
    assert fake.removed_profile == ("research:v1:one", "self")
    assert research_removed.exit_code == 0, research_removed.output
    assert fake.removed_research == "research:v1:one"


def test_report_space_is_editable_without_factor_worktree_and_retry_preserves_tree(tmp_path):
    from tools.cli.release.local_profile import LocalProfileStore
    from tools.cli.release.local_profile_contracts import new_local_profile
    from tools.cli.release.research_reporting.report_space import initialize_report_space
    from tools.cli.commands.research_report_scope_identity import resolve_branch_report_scope
    from tools.cli.release.research_reporting.authoring.tree_model import add_component, load_snapshot
    store = LocalProfileStore(tmp_path / "client")
    store.save(new_local_profile(profile_id="self", display_name="self", workspace_root=tmp_path / "workspace", principal_ref="alice"))
    report = {"report_id": "report:v1:test", "owner_ref": "alice", "profile_ref": "self",
              "research_id": "research:v1:test", "workspace_id": "workspace-one", "title": "验收报告"}
    initialized = initialize_report_space(store, "self", report)
    scope = resolve_branch_report_scope(client_root=tmp_path / "client", profile_id="self",
                                       work_package_id=initialized["work_package_id"], branch_id=initialized["branch_id"])
    add_component(package_root=scope.package_root, branch_id=scope.branch_id,
                  component_id="chapter-one", kind="chapter", title="验收", parent_id=None,
                  body="", content=None, display_kind="")
    before = load_snapshot(package_root=scope.package_root, branch_id=scope.branch_id)
    assert initialize_report_space(store, "self", report) == initialized
    after = load_snapshot(package_root=scope.package_root, branch_id=scope.branch_id)
    assert after["head"] == before["head"]
    assert len(store.load("self")["research_records"]) == 1


def test_report_identity_rejects_path_traversal(tmp_path):
    import pytest
    from tools.cli.release.research_reporting.work_package_identity import ensure_work_package_identity
    for report_id in ("report:v1:../escape", "report:v1:/absolute", "report:v1:"):
        with pytest.raises(ValueError):
            ensure_work_package_identity(tmp_path / "report", work_package_id="safe", report_id=report_id)


def test_branch_read_uses_federated_publication_for_client_or_server(monkeypatch):
    calls = []
    class Client:
        def read_publication_branch(self, publication_id, *, chapter_id):
            calls.append((publication_id, chapter_id))
            return {'report_id': 'shared-report', 'generation': 3}
    monkeypatch.setattr('tools.cli.commands.research_report_branch.client_from_config', lambda: Client())
    runner = CliRunner()
    result = runner.invoke(cli, ['research', 'reports', 'branch-read', '--publication-id', 'a' * 24,
                                 '--chapter-id', 'chapter-one'])
    assert result.exit_code == 0, result.output
    assert calls == [('a' * 24, 'chapter-one')]
    assert json.loads(result.output)['report_id'] == 'shared-report'
    result = runner.invoke(cli, ['research', 'reports', 'branch-read', 'alice', '--publication-id', 'a' * 24])
    assert result.exit_code != 0
    assert len(calls) == 1


def test_publication_branch_read_keeps_route_and_offline_failure():
    import pytest
    from tools.cli.client_research import ResearchClientMixin
    calls = []
    class Session:
        fail = False
        def get(self, path):
            calls.append(path)
            if self.fail:
                raise ConnectionError('source offline')
            return {'generation': 2}
    class Client(ResearchClientMixin):
        session = Session()
        def _expect_success(self, response):
            return response
    client = Client()
    assert client.read_publication_branch('a' * 24, chapter_id='chapter:one') == {'generation': 2}
    assert calls == ['/api/public-research/' + 'a' * 24 + '/chapters/chapter:one']
    client.session.fail = True
    with pytest.raises(ConnectionError, match='offline'):
        client.read_publication_branch('a' * 24)
    with pytest.raises(ValueError, match='chapter_id'):
        client.read_publication_branch('a' * 24, chapter_id='../other')
    assert len(calls) == 2


def test_branch_lifecycle_cli_routes_identity_and_expected_version(monkeypatch):
    from types import SimpleNamespace
    calls = []
    fake = SimpleNamespace(
        reserve_report_branch=lambda rid, payload: calls.append(('reserve', rid, payload)) or {'branch': {'status': 'reserved'}},
        publish_report_branch=lambda rid, bid, payload: calls.append(('publish', rid, bid, payload)) or {'branch': {'status': 'active'}},
        report_branch_status=lambda rid: {'branches': [{'branch_id': 'review'}]},
    )
    monkeypatch.setattr('tools.cli.commands.research_report_branch.client_from_config', lambda: fake)
    runner = CliRunner()
    reserved = runner.invoke(cli, ['research', 'reports', 'branch-reserve', 'report:v1:one',
                                   '--profile', 'self', '--branch-id', 'review', '--from-branch', 'main',
                                   '--source-generation', '3', '--source-revision', 'a' * 64])
    assert reserved.exit_code == 0, reserved.output
    assert calls[0][2]['source_generation'] == 3
    published = runner.invoke(cli, ['research', 'reports', 'branch-publish', 'report:v1:one',
                                    '--profile', 'self', '--branch-id', 'review', '--publication-id', 'p' * 24,
                                    '--expected-generation', '0'])
    assert published.exit_code == 0, published.output
    assert calls[1][1:3] == ('report:v1:one', 'review')
    assert calls[1][3]['expected_generation'] == 0
    status = runner.invoke(cli, ['research', 'reports', 'branch-status', 'report:v1:one'])
    assert status.exit_code == 0 and json.loads(status.output)['branches'][0]['branch_id'] == 'review'
