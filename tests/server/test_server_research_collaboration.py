"""Cross-principal branch read for research report collaboration.

Group A (owner/editor) author branches in their own profile workspaces.  A
reader (group B) can read them.  Only local ``server_agent`` branches are
resolved here; a branch from another source (client / publication / remote
server) is honestly reported as not-local rather than misreading a workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.manager.services.agent_workspace import ensure_server_profile_workspace
from server.manager.services.server_research import ServerResearchService
from server.manager.services.research_catalog import ResearchCatalog
from server.manager.storage.profile_runtime_store import ProfileRuntimeStore
from tools.cli.release.research_reporting.authoring.tree_assets import append_asset
from tools.cli.release.research_reporting.authoring.tree_fork import (
    inherit_report_tree_across_packages,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_component,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.workspace import initialize_work_package

OWNER = "GTHT@owner@1"
EDITOR_A = "GTHT@editorA@2"
READER = "GTHT@reader@3"


@pytest.fixture
def png_bytes() -> bytes:
    # Minimal valid 1x1 transparent PNG.
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42m"
        "Nk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _bind(store: ProfileRuntimeStore, principal: str, profile_id: str) -> None:
    store.bind(
        principal, profile_id,
        runtime_kind="server", executor_id="public-1",
        workspace_relpath=f"users/{principal}/profiles/{profile_id}",
    )


def _service(tmp_path: Path) -> ServerResearchService:
    data_root = tmp_path / "data"
    store = ProfileRuntimeStore(tmp_path / "manager.sqlite")
    for principal, pid in [
        (OWNER, "profile-owner"),
        (EDITOR_A, "profile-editor"),
        (READER, "profile-reader"),
    ]:
        ensure_server_profile_workspace(data_root, principal, pid)
        _bind(store, principal, pid)
    catalog = ResearchCatalog(tmp_path / "manager.sqlite")
    research = catalog.create_research(owner_ref=EDITOR_A, title="协作", authorized_users=[READER])
    catalog.register_report(research["research_id"], actor=EDITOR_A,
        report_id="report-one-editor", build_source="server_agent",
        source_ref="profile-editor:report-one:editor-main")
    return ServerResearchService(data_root, store, server_id="public-1", research_catalog=catalog)


def test_branch_read_resolves_against_creator_workspace(tmp_path):
    service = _service(tmp_path)
    owner_ws = ensure_server_profile_workspace(
        tmp_path / "data", OWNER, "profile-owner",
    )
    initialize_work_package(
        workspace_root=owner_ws, work_package_id="report-one",
        branch_id="main", workspace_id="profile-owner",
        title="协作报告", branch_ref="graph-branch:report-one:main",
    )
    editor_ws = ensure_server_profile_workspace(
        tmp_path / "data", EDITOR_A, "profile-editor",
    )
    editor_pkg = editor_ws / "research" / "report-one"
    inherit_report_tree_across_packages(
        source_package_root=owner_ws / "research" / "report-one",
        target_package_root=editor_pkg,
        source_branch_id="main",
        target_branch_id="editor-main",
        target_report_id="report-one-editor",
    )
    add_component(
        package_root=editor_pkg, branch_id="editor-main",
        component_id="editor-chapter", kind="chapter", title="编辑章节",
        parent_id=None, body="", content=None, display_kind="",
    )

    # Reader reads the EDITOR's branch, resolved against EDITOR's workspace.
    value = service.read_branch(
        READER,
        target_ref=EDITOR_A,
        profile_id="profile-editor",
        package_id="report-one",
        branch_id="editor-main",
    )
    assert value["available"] is True
    assert value["branch_id"] == "editor-main"
    assert value["profile_id"] == "profile-editor"
    assert value["build_source"] == "server_agent"
    assert value["access"]["can_manage"] is False
    index = service.index(READER, "profile-editor:report-one:editor-main", target_ref=EDITOR_A)
    assert index["branch_id"] == "editor-main"
    assert index["access"]["can_manage"] is False
    chapter = service.chapter(READER, "profile-editor:report-one:editor-main", "editor-chapter", target_ref=EDITOR_A)
    assert chapter["access"]["can_manage"] is False


def test_read_branch_denied_for_invalid_reference(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="reference is invalid"):
        service.read_branch(
            READER,
            target_ref=EDITOR_A,
            profile_id="bad/../path",
            package_id="report-one",
            branch_id="main",
        )


def test_read_branch_reports_non_local_source_honestly(tmp_path):
    service = _service(tmp_path)
    value = service.read_branch(
        READER,
        target_ref=EDITOR_A,
        profile_id="profile-editor",
        package_id="report-one",
        branch_id="editor-main",
        build_source="client",
    )
    assert value["available"] is False
    assert value["reason"] == "source-not-local"
    assert value["build_source"] == "client"


def test_reader_reads_foreign_branch_asset(png_bytes: bytes, tmp_path):
    service = _service(tmp_path)
    owner_ws = ensure_server_profile_workspace(
        tmp_path / "data", OWNER, "profile-owner",
    )
    initialize_work_package(
        workspace_root=owner_ws, work_package_id="report-one",
        branch_id="main", workspace_id="profile-owner",
        title="协作报告", branch_ref="graph-branch:report-one:main",
    )
    editor_ws = ensure_server_profile_workspace(
        tmp_path / "data", EDITOR_A, "profile-editor",
    )
    editor_pkg = editor_ws / "research" / "report-one"
    inherit_report_tree_across_packages(
        source_package_root=owner_ws / "research" / "report-one",
        target_package_root=editor_pkg,
        source_branch_id="main",
        target_branch_id="editor-main",
        target_report_id="report-one-editor",
    )
    # Write an asset byte + register it on the editor branch.
    paths = report_tree_paths(editor_pkg, "editor-main")
    asset_dir = paths["root"] / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "diagram.png").write_bytes(png_bytes)
    import hashlib

    head = paths["head"]
    # Load current head, append asset, write back.
    from tools.cli.release.research_reporting.authoring.tree_store import (
        load_head, write_head,
    )

    head_value = load_head(paths)
    head_value = append_asset(head_value, {
        "asset_ref": "asset:diagram.png",
        "media_type": "image/png",
        "filename": "diagram.png",
        "caption": "协作图",
        "alt_text": "协作图",
        "content_hash": hashlib.sha256(png_bytes).hexdigest(),
    })
    write_head(paths, head_value)

    asset_id = hashlib.sha256(
        "asset:diagram.png".encode("utf-8"),
    ).hexdigest()[:24]
    # Reader fetches the EDITOR's asset, resolved against EDITOR's workspace.
    raw, media_type, filename = service.asset(
        READER,
        "profile-editor:report-one:editor-main",
        asset_id,
        target_ref=EDITOR_A,
    )
    assert raw == png_bytes
    assert media_type == "image/png"
    assert filename == "diagram.png"



def test_foreign_unregistered_or_unauthorized_source_is_denied(tmp_path):
    service = _service(tmp_path)
    for viewer, ref in [("GTHT@stranger@4", "profile-editor:report-one:editor-main"),
                        (READER, "profile-editor:report-one:private-branch")]:
        with pytest.raises(PermissionError, match="not authorized"):
            service.asset(viewer, ref, "a" * 24, target_ref=EDITOR_A)
    catalog = service.research_catalog
    research = catalog.list_researches(viewer=EDITOR_A)[0]
    catalog.update_research(research["research_id"], actor=EDITOR_A, authorized_users=[])
    with pytest.raises(PermissionError, match="not authorized"):
        service.local_resource(READER, "profile-editor:report-one:editor-main", "a" * 24, target_ref=EDITOR_A)


def test_branch_http_route_precedes_generic_projection():
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from server.manager.http.server_research_routes import ServerResearchRoutesMixin
    calls = []
    class Handler(ServerResearchRoutesMixin):
        def _session(self): return {"username": READER}
        def send_response(self, status): self.status = status
        def send_header(self, *args): pass
        def end_headers(self): pass
    handler = Handler()
    handler.wfile = BytesIO()
    handler.state = SimpleNamespace(server_research=SimpleNamespace(
        read_branch=lambda *a, **kw: calls.append((a, kw)) or {"available": True}))
    assert handler._get_server_research_routes(urlparse(
        "/api/server-research/branch?target_ref=owner&profile_id=self&package_id=p&branch_id=main"))
    assert handler.status == 200
    assert calls[0][1]["package_id"] == "p"


def test_shared_publication_uses_current_catalog_permissions(tmp_path):
    from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
    catalog = _service(tmp_path).research_catalog
    library = PublicResearchLibrary(tmp_path / "public-research", read_authorizer=catalog.can_read_publication)
    projection = {"schema_version": 2, "report_id": "report-one-editor", "title": "共享报告",
                  "generation": 1, "components": [], "projection_hash": "hash"}
    value = library.sync({"report_id": "report-one-editor", "owner_ref": EDITOR_A, "projection": projection})
    publication = value["publication_id"]
    assert library.list_visible(READER)[0]["publication_id"] == publication
    assert library.index(publication, READER)["title"] == "共享报告"
    assert not library.list_visible("GTHT@stranger@4")
    with pytest.raises(PermissionError):
        library.index(publication, "GTHT@stranger@4")
    assert not catalog.can_read_publication({"report_id": "report-one-editor", "owner_ref": OWNER}, READER)
    research = catalog.list_researches(viewer=EDITOR_A)[0]
    catalog.update_research(research["research_id"], actor=EDITOR_A, authorized_users=[])
    assert not library.list_visible(READER)
    with pytest.raises(PermissionError):
        library.index(publication, READER)
    assert library.index(publication, EDITOR_A)["title"] == "共享报告"


def _editor_branch(service, tmp_path):
    """Publish one editor branch under the owner's research shared with READER."""
    owner_ws = ensure_server_profile_workspace(
        tmp_path / "data", OWNER, "profile-owner",
    )
    initialize_work_package(
        workspace_root=owner_ws, work_package_id="report-one",
        branch_id="main", workspace_id="profile-owner",
        title="协作报告", branch_ref="graph-branch:report-one:main",
    )
    editor_ws = ensure_server_profile_workspace(
        tmp_path / "data", EDITOR_A, "profile-editor",
    )
    editor_pkg = editor_ws / "research" / "report-one"
    inherit_report_tree_across_packages(
        source_package_root=owner_ws / "research" / "report-one",
        target_package_root=editor_pkg,
        source_branch_id="main",
        target_branch_id="editor-main",
        target_report_id="report-one-editor",
    )
    add_component(
        package_root=editor_pkg, branch_id="editor-main",
        component_id="editor-chapter", kind="chapter", title="编辑章节",
        parent_id=None, body="正文内容", content=None, display_kind="",
    )
    return editor_pkg


def test_export_report_renders_markdown_and_refuses_pdf(tmp_path):
    service = _service(tmp_path)
    package_root = _editor_branch(service, tmp_path)
    raw, content_type, filename = service.export_report(
        EDITOR_A, "profile-editor:report-one:editor-main",
    )
    assert content_type == "text/markdown; charset=utf-8"
    assert filename.endswith(".md"), filename
    # The title is sanitized into a filesystem-safe name.
    assert not (set(filename) & set("/\\:"))
    assert "编辑章节" in raw.decode("utf-8")
    assert "正文内容" in raw.decode("utf-8")
    assert package_root.is_dir()
    with pytest.raises(NotImplementedError, match="客户端"):
        service.export_report(
            EDITOR_A, "profile-editor:report-one:editor-main", "pdf",
        )


def test_export_report_authorizes_cross_profile_reader(tmp_path):
    service = _service(tmp_path)
    _editor_branch(service, tmp_path)
    raw, _, _ = service.export_report(
        READER, "profile-editor:report-one:editor-main", target_ref=EDITOR_A,
    )
    assert "编辑章节" in raw.decode("utf-8")
    with pytest.raises(PermissionError, match="not authorized"):
        service.export_report(
            "GTHT@stranger@4",
            "profile-editor:report-one:editor-main",
            target_ref=EDITOR_A,
        )


def test_export_route_streams_attachment_and_maps_errors():
    from io import BytesIO
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from server.manager.http.server_research_routes import ServerResearchRoutesMixin
    seen = []
    class Handler(ServerResearchRoutesMixin):
        def _session(self): return {"username": READER}
        def send_response(self, status): self.status = status
        def send_header(self, *args):
            self.headers = getattr(self, "headers", [])
            self.headers.append(args)
        def end_headers(self): pass
    handler = Handler()
    handler.wfile = BytesIO()

    def export(principal, server_ref, output_format, **kwargs):
        seen.append((principal, server_ref, output_format, kwargs))
        return "# 报告".encode("utf-8"), "text/markdown; charset=utf-8", "报告.md"

    handler.state = SimpleNamespace(server_research=SimpleNamespace(export_report=export))
    assert handler._get_server_research_routes(urlparse(
        "/api/server-research/profile-editor:report-one:editor-main/export"
        "?format=md&target_ref=GTHT%40editorA%402"
    ))
    assert handler.status == 200
    assert seen[0][2] == "md"
    assert seen[0][3] == {"target_ref": "GTHT@editorA@2"}
    assert handler.wfile.getvalue() == "# 报告".encode("utf-8")
    headers = dict(handler.headers)
    disposition = headers["Content-Disposition"]
    assert disposition.startswith("attachment; ")
    assert 'filename="__.md"' in disposition
    assert "filename*=UTF-8''%E6%8A%A5%E5%91%8A.md" in disposition

    def refuse(*args, **kwargs):
        raise NotImplementedError("服务端仅支持导出 Markdown；PDF 请在客户端导出")

    handler.status = None
    handler.state = SimpleNamespace(server_research=SimpleNamespace(export_report=refuse))
    handler._get_server_research_routes(urlparse(
        "/api/server-research/profile-editor:report-one:editor-main/export?format=pdf"
    ))
    assert handler.status == 501


def test_data_plane_research_asset_reuses_catalog_without_control_database(tmp_path, png_bytes):
    import base64
    import hashlib
    from server.manager.data_plane.app import research_read_authorizer
    from tools.cli.release.research_reporting.public_research.library import PublicResearchLibrary
    from tools.cli.release.research_reporting.public_research.object_store import PublicResearchObjectStore
    catalog = _service(tmp_path).research_catalog
    library = PublicResearchLibrary(tmp_path / "public-research")
    asset_id = "a" * 24
    projection = {"schema_version": 2, "report_id": "report-one-editor", "title": "共享报告",
        "generation": 1, "components": [], "projection_hash": "hash", "assets": [{
        "asset_id": asset_id, "media_type": "image/png", "filename": "图片.png",
        "content_hash": hashlib.sha256(png_bytes).hexdigest(),
        "content_base64": base64.b64encode(png_bytes).decode()}]}
    publication = library.sync({"report_id": "report-one-editor", "owner_ref": EDITOR_A,
                               "projection": projection})["publication_id"]
    byte_library = PublicResearchLibrary(library.root,
        read_authorizer=research_read_authorizer(str(catalog.db_path)))
    objects = PublicResearchObjectStore(byte_library)
    assert objects.resolve(publication, "research_asset", asset_id, READER).path.read_bytes() == png_bytes
    research = catalog.list_researches(viewer=EDITOR_A)[0]
    catalog.update_research(research["research_id"], actor=EDITOR_A, authorized_users=[])
    with pytest.raises(PermissionError):
        objects.resolve(publication, "research_asset", asset_id, READER)
