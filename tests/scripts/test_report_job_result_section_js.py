"""A report Job result section reuses the shared Job 运行过程与结果 surface."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO / "server" / "manager" / "web"


def test_report_job_result_section_reuses_the_job_detail_implementation():
    result = subprocess.run(
        ["node", "tests/js/test_report_job_result_section.js"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_report_job_result_section: ok" in result.stdout


def test_job_result_renderer_is_lazily_registered_for_the_report_route():
    """The report route must not pay for the Job detail readers up front.

    ``report/job-result-section.js`` renders a section through
    ``FTJobs.loadDetail``/``FTJobResultViewers``, which live in the Job detail
    groups; those groups stay on-demand instead of joining the report route's
    initial script budget.
    """
    manifest = json.loads(
        (WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8")
    )
    assert "report/job-result-section.js" in manifest["groups"]["report"]
    assert "job-detail-core" not in manifest["route_groups"]["report"]
    assert "job-detail-core" not in manifest["group_dependencies"]["report"]
    source = (WEB_ROOT / "report" / "job-result-section.js").read_text(encoding="utf-8")
    assert 'FTStaticLoader?.loadGroups?.([JOB_DETAIL_GROUP])' in source
    assert 'JOB_DETAIL_GROUP = "job-detail-core"' in source
    component_view = (WEB_ROOT / "report" / "component-view.js").read_text(encoding="utf-8")
    assert "FTReportJobResult?.isJobResultSection?.(component)" in component_view
    assert "FTReportJobResult.mount(component, context)" in component_view
