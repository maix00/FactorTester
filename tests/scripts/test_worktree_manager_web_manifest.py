"""Contracts for the static Web renderer module manifest."""

from __future__ import annotations

import json
from pathlib import Path

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
    assert manifest["external_styles"] == ["katex/katex.min.css"]
    assert manifest["styles"] == ["research.css", "styles/report.css"]
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
