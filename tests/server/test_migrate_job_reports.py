from __future__ import annotations

from pathlib import Path

from scripts.migrations.migrate_job_reports_to_couchdb import legacy_report_dirs


def test_only_directories_with_files_are_reports(tmp_path):
    (tmp_path / "job-1").mkdir()
    (tmp_path / "job-1" / "tearsheet.html").write_text("<html/>")
    (tmp_path / "empty").mkdir()
    (tmp_path / "note.txt").write_text("not a report")
    assert legacy_report_dirs(tmp_path) == [tmp_path / "job-1"]
