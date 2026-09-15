"""The report download icon: .md/.pdf choices, native bridge, server fallback."""
from pathlib import Path
import subprocess


def test_report_export_js():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "tests/js/test_report_export.js"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_both_report_pages_expose_the_download_icon():
    root = Path(__file__).resolve().parents[2]
    web = root / "server/manager/web"
    manifest = (web / "module-manifest.json").read_text()
    assert manifest.count('"report/export-action.js"') == 2
    # The dedicated report page and the research report tab both mount it.
    assert "FTReportExport.menu(" in (web / "report/report-entry.js").read_text()
    assert "FTReportExport.menu(" in (web / "research/reports.js").read_text()
