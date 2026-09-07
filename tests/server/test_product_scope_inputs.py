import json
from server.jobs import product_scope_inputs as inputs


def test_retained_snapshot_uses_frozen_job_without_catalog_access(monkeypatch):
    entries = []
    monkeypatch.setattr(inputs, "retain_input_files", lambda repository, **kw: entries.extend(kw["entries"]) or kw["entries"])
    spec = {"product_selections": {"g": {
        "paths": ["Product/_products/A"], "definition_paths": ["Category/day"],
        "resolution_sha256": "frozen", "label": "day",
    }}, "product_categories": {"c": {"content_hash": "version"}}}
    inputs.retain_product_scope(object(), job_id="job", owner="alice", job_spec=spec)
    assert len(entries) == 1
    assert entries[0]["artifact_kind"] == "product_scope"
    assert json.loads(entries[0]["content"])["product_selections"] == spec["product_selections"]
    assert entries[0]["content"] == inputs.product_scope_content(spec)


def test_legacy_job_never_claims_current_catalog_is_original_snapshot(monkeypatch):
    monkeypatch.setattr(inputs, "retain_input_files", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not persist invented snapshot")))
    spec = {"product_selections": {"g": {"paths": ["Category/day"]}}}
    assert inputs.product_scope_snapshot(spec)["legacy_unfrozen"] is True
    assert inputs.retain_product_scope(None, job_id="j", owner="alice", job_spec=spec) == []
