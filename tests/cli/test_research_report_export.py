from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import unquote

import click
from click.testing import CliRunner
import pytest

from tools.cli.commands import research_report_export
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.tree_model import (
    add_asset,
    add_component,
)
from tools.cli.release.job_cache import cache_job_artifact
from tools.cli.commands.research_report_scope import resolve_branch_report_scope
from tools.cli.release.research_reporting.workspace import (
    initialize_report_workspace,
)


def _scope(tmp_path: Path) -> Path:
    client_root = tmp_path / "client"
    workspace = tmp_path / "workspace"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=workspace,
    )
    LocalProfileStore(client_root).save(profile)
    initialized = initialize_report_workspace(
        workspace_root=workspace,
        report_workspace_id="wp",
        branch_id="main",
        report_id="report-1",
        workspace_id="one",
        title="报告",
        branch_ref="report-branch:main",
    )
    add_component(
        package_root=initialized["package_root"], branch_id="main",
        component_id="factor_semantics", kind="chapter", title="因子语义",
        parent_id=None, body="", content=None, display_kind="",
    )
    return client_root


def _args(output: Path, output_format: str) -> list[str]:
    return [
        "export",
        "--profile", "maxa",
        "--report-workspace-id", "wp",
        "--branch-id", "main",
        "--format", output_format,
        "--output", str(output),
        "--json",
    ]


def test_markdown_export_is_cli_owned_and_refuses_implicit_overwrite(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )
    output = tmp_path / "研究报告.md"
    runner = CliRunner()

    exported = runner.invoke(report_cli, _args(output, "markdown"))

    assert exported.exit_code == 0, exported.output
    payload = json.loads(exported.output)
    assert payload["format"] == "markdown"
    assert payload["output"] == str(output)
    written = output.read_text(encoding="utf-8")
    assert "# 因子语义" in written
    # The native export writes the same branch/version front matter.
    assert "- 分支：main" in written
    assert "- 作者 profile：maxa" in written
    assert "- 导出时间：" in written
    assert "报告版本" in written
    assert not (
        tmp_path / "workspace/research/wp/branches/main/REPORT.md"
    ).exists()
    rejected = runner.invoke(report_cli, _args(output, "markdown"))
    assert rejected.exit_code != 0
    assert "--force" in rejected.output


def test_pdf_export_invokes_the_configured_native_renderer(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )
    renderer = tmp_path / "factortester-report-renderer"
    renderer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "test \"$1\" = --input\n"
        "test \"$3\" = --output\n"
        "printf '%%PDF-native-test' > \"$4\"\n",
        encoding="utf-8",
    )
    renderer.chmod(0o755)
    monkeypatch.setenv("FACTORTESTER_REPORT_RENDERER", str(renderer))
    output = tmp_path / "研究报告.pdf"

    exported = CliRunner().invoke(report_cli, _args(output, "pdf"))

    assert exported.exit_code == 0, exported.output
    assert output.read_bytes().startswith(b"%PDF-native-test")
    renderer.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failed = CliRunner().invoke(report_cli, _args(output, "pdf") + ["--force"])
    assert failed.exit_code != 0
    assert output.read_bytes().startswith(b"%PDF-native-test")
    assert not list(tmp_path.glob(".研究报告.pdf.*"))


def test_markdown_export_materializes_only_referenced_job_images(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(research_report_export, "load_profile_root", lambda _: client_root)
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id="maxa",
        report_workspace_id="wp", branch_id="main",
    )
    job_id = "b" * 32
    image = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    digest = hashlib.sha256(image).hexdigest()
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    cache_job_artifact(
        job_id=job_id, name="chart", filename="chart.svg",
        content_type="image/svg+xml", raw=image, server_url="",
    )
    for name in ("chart", "unused"):
        add_asset(
            package_root=scope.package_root, branch_id="main",
            asset={
                "asset_ref": f"job-artifact:{job_id}:{name}",
                "media_type": "image/svg+xml", "filename": f"{name}.svg",
                "caption": "结果图", "alt_text": "结果图", "content_hash": digest,
                "external_ref": f"factortester-artifact://jobs/{job_id}/{name}",
            },
        )
    add_component(
        package_root=scope.package_root, branch_id="main",
        component_id="result-chart", kind="image", title="结果图",
        parent_id="factor_semantics", body="",
        content={"asset_ref": f"job-artifact:{job_id}:chart"}, display_kind="",
    )
    add_component(
        package_root=scope.package_root, branch_id="main",
        component_id="unused-link", kind="entry", title="来源链接",
        parent_id="factor_semantics",
        body=f"[未挂载的生成物](factortester-artifact://jobs/{job_id}/unused)",
        content=None, display_kind="",
    )
    output = tmp_path / "研究报告.md"
    bundle = tmp_path / "研究报告.assets"
    with monkeypatch.context() as failing:
        def fail_write(*_args):
            raise OSError("write failed")
        failing.setattr(research_report_export, "_atomic_write", fail_write)
        failed = CliRunner().invoke(report_cli, _args(output, "markdown"))
    assert failed.exit_code != 0
    assert not output.exists()
    assert not bundle.exists()

    exported = CliRunner().invoke(report_cli, _args(output, "markdown"))
    assert exported.exit_code == 0, exported.output
    written = output.read_text(encoding="utf-8")
    assert f"研究报告.assets/{digest}.svg" in unquote(written)
    assert f"![结果图](factortester-artifact://jobs/{job_id}/chart)" not in written
    assert f"[未挂载的生成物](factortester-artifact://jobs/{job_id}/unused)" in written
    assert (bundle / f"{digest}.svg").read_bytes() == image
    assert len(list(bundle.iterdir())) == 1


@pytest.mark.parametrize("content_hash", ["", "not-a-sha256"])
def test_remote_report_image_requires_verified_content_hash(
    tmp_path: Path, content_hash: str,
) -> None:
    source = "factortester-artifact://jobs/" + "a" * 32 + "/chart"
    snapshot = {"head": {"assets": [{
        "media_type": "image/svg+xml", "external_ref": source,
        "filename": "chart.svg", "content_hash": content_hash,
    }]}}
    with pytest.raises(click.ClickException, match="valid content hash"):
        research_report_export._pdf_image_sources(
            f"![chart]({source})".encode(), snapshot, tmp_path,
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="native PDF renderer requires macOS")
def test_pdf_export_renders_mounted_svg_without_the_live_job_panel(
    tmp_path: Path, monkeypatch,
) -> None:
    if not shutil.which("swiftc"):
        pytest.skip("Swift compiler is unavailable")
    pymupdf = pytest.importorskip("pymupdf")
    client_root = _scope(tmp_path)
    monkeypatch.setattr(research_report_export, "load_profile_root", lambda _: client_root)
    scope = resolve_branch_report_scope(
        client_root=client_root, profile_id="maxa",
        report_workspace_id="wp", branch_id="main",
    )
    job_id = "a" * 32
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="30" height="20">'
           b'<rect width="30" height="20" fill="red"/></svg>')
    digest = hashlib.sha256(svg).hexdigest()
    monkeypatch.setenv("FACTORTESTER_JOB_CACHE_ROOT", str(tmp_path / "jobs"))
    cache_job_artifact(
        job_id=job_id, name="equity", filename="equity.svg",
        content_type="image/svg+xml", raw=svg, server_url="",
    )
    reference = f"factortester-artifact://jobs/{job_id}/equity"
    add_asset(
        package_root=scope.package_root, branch_id="main",
        asset={
            "asset_ref": f"job-artifact:{job_id}:equity",
            "media_type": "image/svg+xml", "filename": "equity.svg",
            "caption": "净值图", "alt_text": "净值图",
            "external_ref": reference, "content_hash": digest,
        },
    )
    add_component(
        package_root=scope.package_root, branch_id="main",
        component_id=f"job-{job_id}-result", kind="special",
        title="动态任务面板", parent_id="factor_semantics",
        body="运行中", content=None, display_kind="test_result",
    )
    add_component(
        package_root=scope.package_root, branch_id="main",
        component_id="equity-image", kind="image", title="净值图",
        parent_id=f"job-{job_id}-result", body="",
        content={"asset_ref": f"job-artifact:{job_id}:equity"},
        display_kind="",
    )
    renderer = tmp_path / "factortester-report-renderer"
    source = Path(__file__).resolve().parents[2] / "tools/cli/native/report_renderer.swift"
    subprocess.run(["swiftc", str(source), "-o", str(renderer)], check=True)
    monkeypatch.setenv("FACTORTESTER_REPORT_RENDERER", str(renderer))
    output = tmp_path / "研究报告.pdf"
    exported = CliRunner().invoke(report_cli, _args(output, "pdf"))
    assert exported.exit_code == 0, exported.output
    with pymupdf.open(output) as document:
        assert any(page.get_images(full=True) for page in document)
        text = "\n".join(page.get_text() for page in document)
        assert "动态任务面板" not in text
        assert "运行中" not in text


def test_export_requires_the_matching_filename_extension(
    tmp_path: Path, monkeypatch,
) -> None:
    client_root = _scope(tmp_path)
    monkeypatch.setattr(
        research_report_export,
        "load_profile_root",
        lambda _path: client_root,
    )

    result = CliRunner().invoke(
        report_cli, _args(tmp_path / "report.txt", "pdf"),
    )

    assert result.exit_code != 0
    assert ".pdf" in result.output
