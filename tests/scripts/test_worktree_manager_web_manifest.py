"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.worktree_manager_research as research_static
from scripts.worktree_manager_research import shell_bytes, static_file


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "scripts" / "worktree_manager_web"


def test_manifest_matches_html_script_order_and_files() -> None:
    manifest = json.loads((WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"))
    template = (WEB_ROOT / manifest["entry"]).read_text(encoding="utf-8")
    html = shell_bytes().decode("utf-8")
    static_html, content_type = static_file(manifest["entry"])

    assert manifest["schema_version"] == 1
    assert manifest["scripts"]
    architecture = manifest["architecture"]
    assert architecture["max_script_lines"] == 400
    assert architecture["max_style_lines"] == 500
    groups = manifest["groups"]
    assert set(item for files in groups.values() for item in files) == set(manifest["scripts"])
    assert sum(len(files) for files in groups.values()) == len(manifest["scripts"])
    assert manifest["external_styles"] == ["katex/katex.min.css"]
    assert manifest["styles"] == ["styles/app.css", "styles/report.css"]
    assert "FT_STATIC_STYLES" in template
    assert "FT_STATIC_SCRIPTS" in template
    assert content_type == "text/html"
    assert static_html.decode("utf-8") == html
    for relative in [*manifest["scripts"], *manifest["styles"]]:
        assert (WEB_ROOT / relative).is_file(), relative

    script_paths = [
        line.split('src="/research-static/', 1)[1].split('"', 1)[0]
        for line in html.splitlines()
        if 'src="/research-static/' in line and line.endswith("</script>")
    ]
    style_paths = [
        line.split('href="/research-static/', 1)[1].split('"', 1)[0]
        for line in html.splitlines()
        if 'href="/research-static/' in line and 'stylesheet' in line
    ]
    assert script_paths == [*manifest["external_scripts"], *manifest["scripts"]]
    assert style_paths == [*manifest["external_styles"], *manifest["styles"]]

    discovered_scripts = {
        path.relative_to(WEB_ROOT).as_posix()
        for path in WEB_ROOT.rglob("*.js")
    }
    assert discovered_scripts == set(manifest["scripts"]), (
        "every production Web module must be listed exactly once in the manifest"
    )
    discovered_styles = {
        path.relative_to(WEB_ROOT).as_posix()
        for path in WEB_ROOT.rglob("*.css")
    }
    assert discovered_styles == set(manifest["styles"])
    # Production modules belong to a semantic group.  Keeping the entry HTML,
    # manifest and architecture notes at the root prevents a coordinator or a
    # stylesheet from silently becoming an unowned global again.
    assert not list(WEB_ROOT.glob("*.js"))
    assert not list(WEB_ROOT.glob("*.css"))

    script_lines = {
        relative: len((WEB_ROOT / relative).read_text(encoding="utf-8").splitlines())
        for relative in manifest["scripts"]
    }
    assert max(script_lines.values()) <= architecture["max_script_lines"], script_lines
    style_lines = {
        relative: len((WEB_ROOT / relative).read_text(encoding="utf-8").splitlines())
        for relative in manifest["styles"]
    }
    assert max(style_lines.values()) <= architecture["max_style_lines"], style_lines


def test_runtime_rejects_undeclared_web_module_asset(tmp_path, monkeypatch) -> None:
    """An old module URL must not bypass the manifest at runtime."""
    unlisted = tmp_path / "stale-module.js"
    unlisted.write_text("window.stale = true;", encoding="utf-8")
    manifest = research_static._module_manifest()
    monkeypatch.setattr(research_static, "WEB_ROOT", tmp_path)
    monkeypatch.setattr(research_static, "_module_manifest", lambda: manifest)

    try:
        static_file("stale-module.js")
    except ValueError as error:
        assert str(error) == "web module asset is not declared in manifest"
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("undeclared Web module was served")


def test_navigation_route_classifier_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "navigation_routes.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_product_feature_and_detail_tabs_have_stable_ownership() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "product_tabs.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_route_dispatch_contract() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "route_dispatch.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"


def test_workbench_factor_selection_seam() -> None:
    import subprocess

    fixture = ROOT / "tests" / "scripts" / "fixtures" / "factor_selection.js"
    result = subprocess.run(
        ["node", str(fixture)], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "ok"
