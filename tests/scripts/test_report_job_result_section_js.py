"""A report Job result section shows the test page's own 运行过程与结果 panel."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO / "server" / "manager" / "web"


def test_report_job_result_section_matches_the_test_page_panel():
    result = subprocess.run(
        ["node", "tests/js/test_report_job_result_section.js"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_report_job_result_section: ok" in result.stdout


def test_the_panel_reuses_the_test_run_composition_and_stays_lazy():
    """The reader compares the report panel with the test configuration page.

    That page composes the panel in ``workbench/test-run-results.js``
    (``FTTestRunResults.render`` → ``FTTestRunProgress`` + the per-kind result
    view), so the report must call exactly that and must not own a renderer of
    its own.  The group is loaded on demand so the report route's initial script
    budget does not pay for the workbench.
    """
    manifest = json.loads(
        (WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8")
    )
    assert "report/job-result-section.js" in manifest["groups"]["report"]
    assert "workbench-run-results" not in manifest["route_groups"]["report"]
    assert "workbench-run-results" not in manifest["group_dependencies"]["report"]

    source = (WEB_ROOT / "report" / "job-result-section.js").read_text(encoding="utf-8")
    # the test page's composition, not a second renderer
    assert 'FTTestRunResults.render(' in source
    assert 'FTStaticLoader?.loadGroups?.([RUN_RESULT_GROUP])' in source
    assert 'RUN_RESULT_GROUP = "workbench-run-results"' in source
    for owned in ("progressView", "domainSections", "genericSection"):
        assert owned not in source, f"the report must not re-implement {owned}"

    component_view = (WEB_ROOT / "report" / "component-view.js").read_text(encoding="utf-8")
    assert "FTReportJobResult?.isJobResultSection?.(component)" in component_view
    assert "FTReportJobResult.mount(component, context)" in component_view
