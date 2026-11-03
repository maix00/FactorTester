import base64
from copy import deepcopy
import hashlib
import io
import json
import zipfile
import zlib

import pytest

from server.jobs.storage import couchdb_research_versions as versions
from tests.server.test_couchdb_research_publication import Couch


def document(generation=1, *, resource=b"immutable selected report evidence\n" * 10000):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in [("manifest.json", json.dumps({"generation": generation}).encode()),
                          ("objects/" + hashlib.sha256(resource).hexdigest(), resource)]:
            archive.writestr(zipfile.ZipInfo(name), raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    payload = output.getvalue()
    return {"_id": "research-report:p-test", "kind": "research_report",
            "publication_id": "p-test", "report_id": "report-1", "research_id": "research-1",
            "branch_ref": "main", "owner_identity_id": "stable", "keycloak_resource_id": "resource-1",
            "generation": generation, "_attachments": {
                "authoring.bin": {"content_type": "application/octet-stream",
                                  "data": base64.b64encode(payload).decode()}}}


def test_versions_keep_exact_bytes_and_share_zip_resources_after_head_changes():
    store = Couch()
    first = document()
    ref = versions.archive_report_version(store, first)
    writes = store.writes
    assert versions.archive_report_version(store, first) == ref and store.writes == writes
    first_chunks = {key for key in store.docs if key.startswith(versions._CHUNK)}
    second = document(2)
    later = versions.archive_report_version(store, second, parent=ref)
    next_chunks = {key for key in store.docs if key.startswith(versions._CHUNK)} - first_chunks
    # Only the manifest and central directory change, not the selected resource.
    assert len(next_chunks) == 2 and len(first_chunks) == 3
    for value in store.docs.values():
        value["_rev"] = "99-compacted"
    restored = versions.read_report_version(store, ref, identity=first, include_bytes=True)
    assert restored["_attachments"] == first["_attachments"]
    assert restored["generation"] == 1
    latest = versions.read_report_version(store, later, identity=second)
    assert latest["parent_version_ref"] == ref and "_attachments" not in latest


@pytest.mark.parametrize("field", ["report_id", "research_id", "branch_ref", "owner_identity_id", "keycloak_resource_id"])
def test_history_requires_the_exact_authorized_report_identity(field):
    store, value = Couch(), document()
    ref = versions.archive_report_version(store, value)
    wrong = {**value, field: "other"}
    with pytest.raises(PermissionError, match="identity differs"):
        versions.read_report_version(store, ref, identity=wrong, include_bytes=True)
    before = store.writes
    with pytest.raises(PermissionError):
        versions.archive_report_version(store, wrong, parent=ref)
    assert store.writes == before


def test_incomplete_identity_is_rejected_before_any_object_write():
    store = Couch()
    with pytest.raises(ValueError, match="identity is incomplete"):
        versions.archive_report_version(store, {**document(), "owner_identity_id": ""})
    assert store.writes == 0


def test_chunk_checksums_and_expanded_size_are_checked_before_returning_content():
    store, value = Couch(), document()
    ref = versions.archive_report_version(store, value)
    chunk = next(value for key, value in store.docs.items() if key.startswith(versions._CHUNK))
    original = deepcopy(chunk)
    chunk["data"] = base64.b64encode(zlib.compress(b"wrong" * 100000)).decode()
    with pytest.raises(ValueError, match="checksum or size differs"):
        versions.read_report_version(store, ref, identity=value, include_bytes=True)
    chunk.clear(); chunk.update(original)
    chunk["size_bytes"] = versions.CHUNK_BYTES + 1
    with pytest.raises(ValueError, match="chunk is invalid"):
        versions.read_report_version(store, ref, identity=value, include_bytes=True)


def test_alternative_valid_compression_does_not_change_chunk_identity():
    store, value = Couch(), document()
    ref = versions.archive_report_version(store, value)
    for key, chunk in store.docs.items():
        if key.startswith(versions._CHUNK):
            raw = zlib.decompress(base64.b64decode(chunk["data"]))
            chunk["data"] = base64.b64encode(zlib.compress(raw, level=1)).decode()
    before = store.writes
    assert versions.archive_report_version(store, value) == ref
    assert store.writes == before


def test_empty_attachment_round_trips_without_an_unbounded_or_missing_chunk():
    store, value = Couch(), document()
    value['_attachments']['empty.txt'] = {'content_type': 'text/plain', 'data': ''}
    ref = versions.archive_report_version(store, value)
    restored = versions.read_report_version(store, ref, identity=value, include_bytes=True)
    assert restored['_attachments']['empty.txt']['data'] == ''


def test_existing_attachment_reads_are_bound_to_the_captured_head_revision():
    store, value = Couch(), document()
    raw = base64.b64decode(value['_attachments']['authoring.bin']['data'])
    value['_rev'] = 'captured-revision'
    value['_attachments']['authoring.bin'] = {'content_type': 'application/octet-stream', 'stub': True}
    request = store._request
    seen = []
    def revision_get(method, path, body=None, *, maximum_bytes=None):
        if path.startswith(value['_id'] + '/'):
            seen.append(path)
            assert path.endswith('?rev=captured-revision')
            return 200, raw
        return request(method, path, body, maximum_bytes=maximum_bytes)
    store._request = revision_get
    ref = versions.archive_report_version(store, value)
    restored = versions.read_report_version(store, ref, identity=value, include_bytes=True)
    assert seen and base64.b64decode(restored['_attachments']['authoring.bin']['data']) == raw
