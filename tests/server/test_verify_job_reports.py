from __future__ import annotations

from server.jobs.storage.couchdb_reports import CouchDBObjectStore, ReportDocument, publish_job_report
from scripts.migrations.verify_job_reports_couchdb import verify_dir


class FakeStore(CouchDBObjectStore):
    def __init__(self):
        super().__init__("http://couch", "reports")
        self.docs = {}
        self.files = {}

    def put_report(self, report, *, overwrite=False):
        self.docs[report.report_ref] = report

    def put_attachment(self, ref, name, data, content_type):
        self.files[(ref, name)] = data

    def get_attachment(self, ref, name):
        return self.files[(ref, name)]

    def _request(self, method, path, body=None, content_type="application/json"):
        import json
        if path == "report:job-1:1":
            return 200, json.dumps(
                self.docs["report:job-1:1"].to_doc()
            ).encode()
        raise KeyError(path)


def test_verify_matches_published_report(tmp_path):
    (tmp_path / "job-1").mkdir()
    (tmp_path / "job-1" / "tearsheet.html").write_text("<html/>")
    store = FakeStore()
    publish_job_report(job_id="job-1", attempt=1, owner="alice",
                       reports_dir=str(tmp_path / "job-1"), store=store)
    assert verify_dir(store, tmp_path / "job-1")["ok"] is True
