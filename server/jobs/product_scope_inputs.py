"""Immutable product-scope submission artifact shared by every test kind."""

import json

from server.jobs.input_artifacts import retain_input_files


def product_scope_snapshot(job_spec: dict) -> dict:
    selections = job_spec.get("product_selections") or {}
    if selections and any(not value.get("resolution_sha256") for value in selections.values()):
        return {"schema_version": 1, "legacy_unfrozen": True}
    return {
        "schema_version": 1,
        "product_selections": selections,
        "product_categories": job_spec.get("product_categories") or {},
    } if selections else {}


def retain_product_scope(repository, *, job_id, owner, job_spec):
    snapshot = product_scope_snapshot(job_spec)
    if not snapshot.get("product_selections"):
        return []
    return retain_input_files(repository, job_id=job_id, owner=owner, entries=[{
        "name": "product_scope_snapshot",
        "file_name": "product_scope_snapshot.json",
        "artifact_kind": "product_scope",
        "content_type": "application/json",
        "title_zh": "产品范围快照",
        "content": product_scope_content(job_spec),
    }])


def product_scope_content(job_spec):
    snapshot = product_scope_snapshot(job_spec)
    return ((json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)
             + "\n").encode() if snapshot.get("product_selections") else b"")
