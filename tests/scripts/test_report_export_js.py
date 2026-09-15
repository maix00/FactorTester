"""The report download icon: .md/.pdf choices, native bridge, server fallback."""
import json
from pathlib import Path
import subprocess


def test_report_export_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_report_export.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_both_report_pages_load_the_download_module():
    root = Path(__file__).resolve().parents[2]
    web = root / "server/manager/web"
    manifest = json.loads((web / "module-manifest.json").read_text())
    # One shared module, pulled in by the dedicated page and the report tab.
    assert manifest["groups"]["report-export"] == ["report/export-action.js"]
    for group in ("report", "research-reports"):
        assert "report-export" in manifest["group_dependencies"][group], group
        assert "report/export-action.js" not in manifest["groups"][group], group
    assert manifest["scripts"].count("report/export-action.js") == 1
    # The dedicated report page and the research report tab both mount it.
    assert "FTReportExport.menu(" in (web / "report/report-entry.js").read_text()
    assert "FTReportExport.menu(" in (web / "research/reports.js").read_text()
