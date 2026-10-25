from scripts.migrations.migrate_research_reports_to_couchdb import doc_for_record


def test_research_report_doc_is_not_job_test_report():
    doc = doc_for_record({"publication_id": "p1", "owner_ref": "alice", "title": "T"})
    assert doc["_id"] == "research-report:p1"
    assert doc["kind"] == "research_report"
    assert doc["owner_ref"] == "alice"
