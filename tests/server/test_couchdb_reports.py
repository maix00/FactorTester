from __future__ import annotations

from server.jobs.storage.couchdb_reports import (
    CouchDBObjectStore, ReportDocument, content_name, write_report,
)


class FakeStore(CouchDBObjectStore):
    def __init__(self):
        super().__init__("http://couch", "reports")
        self.docs = {}
        self.files = {}

    def put_attachment(self, report_ref, name, data, content_type):
        self.files[(report_ref, name)] = (data, content_type)

    def put_report(self, report, *, overwrite=False):
        self.docs[report.report_ref] = report


def test_report_uses_content_addressed_attachments():
    html = b"<html>report</html>"
    store = FakeStore()
    report = write_report(
        store, job_id="job-1", owner="alice", revision=2,
        metadata={"kind": "backtest"},
        files={"tearsheet.html": (html, "text/html")},
    )
    assert report.report_ref == "report:job-1:2"
    assert report.attachments["tearsheet.html"] == content_name(html, "html")
    assert store.files[(report.report_ref, report.attachments["tearsheet.html"])][0] == html


def test_replication_uses_continuous_database_copy():
    config = CouchDBObjectStore("http://a", "ft_objects").replication_config(
        "http://b/ft_objects", continuous=True,
    )
    assert config == {
        "source": "http://a/ft_objects", "target": "http://b/ft_objects",
        "continuous": True,
    }
