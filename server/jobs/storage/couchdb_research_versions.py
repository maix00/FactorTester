"""Immutable report versions; CouchDB MVCC is only the mutable HEAD's CAS.

Content lives in bounded, deduplicated chunks. ZIP entry boundaries keep
unchanged report resources reusable when the manifest changes. No filesystem
path or executable report/factor code is involved in version storage.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
import zipfile
import zlib

CHUNK_BYTES = 4 * 1024 * 1024
MAX_VERSION_BYTES = 64 * 1024 * 1024
_VERSION = "research-report-version:"
_CHUNK = "research-report-bytes:"
_HEX = re.compile(r"[0-9a-f]{64}")


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _get(store, ref):
    status, raw = store._request("GET", ref, maximum_bytes=8 * 1024 * 1024)
    if status != 200:
        raise OSError("report version store did not confirm a read")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("report version document is invalid")
    return value


def _put_immutable(store, ref, value, *, equivalent=None):
    def matches(existing):
        clean = {k: v for k, v in existing.items() if k != "_rev"}
        return equivalent(clean) if equivalent else clean == value
    try:
        existing = _get(store, ref)
    except HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        if not matches(existing):
            raise ValueError("immutable report content differs")
        return
    try:
        status, raw = store._request("PUT", ref, _encoded(value))
    except HTTPError as exc:
        if exc.code != 409:
            raise
        existing = _get(store, ref)
        if not matches(existing):
            raise ValueError("immutable report content differs") from None
        return
    result = json.loads(raw)
    if status not in {201, 202} or result.get("ok") is not True:
        raise OSError("report version store did not confirm a write")


def _segments(data):
    boundaries = {0, len(data)}
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            boundaries.update(item.header_offset for item in archive.infolist())
            boundaries.add(archive.start_dir)
    ordered = sorted(boundaries)
    if any(not 0 <= offset <= len(data) for offset in ordered):
        raise ValueError("report attachment boundaries are invalid")
    for start, end in zip(ordered, ordered[1:]):
        for position in range(start, end, CHUNK_BYTES):
            yield data[position:min(end, position + CHUNK_BYTES)]


def _save_bytes(store, data):
    if len(data) > MAX_VERSION_BYTES:
        raise ValueError("report version attachment exceeds its limit")
    chunks = []
    for raw in _segments(data):
        digest = _digest(raw)
        ref = _CHUNK + digest
        value = {"_id": ref, "kind": "research_report_bytes", "schema_version": 1,
                 "sha256": digest, "size_bytes": len(raw), "codec": "zlib",
                 "data": base64.b64encode(zlib.compress(raw, level=6)).decode("ascii")}
        _put_immutable(store, ref, value,
                       equivalent=lambda prior: _decode_chunk(prior, digest) == raw)
        chunks.append(digest)
    return {"sha256": _digest(data), "size_bytes": len(data), "chunks": chunks}


def _decode_chunk(chunk, digest):
    if (chunk.get("_id") != _CHUNK + digest
            or chunk.get("kind") != "research_report_bytes" or chunk.get("codec") != "zlib"
            or chunk.get("sha256") != digest or type(chunk.get("size_bytes")) is not int
            or not 0 < chunk["size_bytes"] <= CHUNK_BYTES
            or not isinstance(chunk.get("data"), str)
            or len(chunk["data"]) > (CHUNK_BYTES + 65536) * 4 // 3 + 4):
        raise ValueError("report version chunk is invalid")
    compressed = base64.b64decode(chunk["data"], validate=True)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, chunk["size_bytes"] + 1)
    if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or len(raw) != chunk["size_bytes"] or _digest(raw) != digest):
        raise ValueError("report version chunk checksum or size differs")
    return raw


def _load_bytes(store, recipe):
    if (not isinstance(recipe, dict) or set(recipe) != {"sha256", "size_bytes", "chunks"}
            or type(recipe["size_bytes"]) is not int
            or not 0 <= recipe["size_bytes"] <= MAX_VERSION_BYTES
            or not isinstance(recipe["chunks"], list)
            or (recipe["size_bytes"] == 0) != (not recipe["chunks"])
            or len(recipe["chunks"]) > 10000
            or not _HEX.fullmatch(str(recipe["sha256"]))):
        raise ValueError("report version attachment recipe is invalid")
    parts, total = [], 0
    for digest in recipe["chunks"]:
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise ValueError("report version chunk reference is invalid")
        chunk = _get(store, _CHUNK + digest)
        raw = _decode_chunk(chunk, digest)
        total += len(raw)
        if total > recipe["size_bytes"]:
            raise ValueError("report version attachment exceeds its declared size")
        parts.append(raw)
    data = b"".join(parts)
    if len(data) != recipe["size_bytes"] or _digest(data) != recipe["sha256"]:
        raise ValueError("report version attachment checksum or size differs")
    return data


def valid_version_ref(value):
    return isinstance(value, str) and value.startswith(_VERSION) and _HEX.fullmatch(value[len(_VERSION):]) is not None


def archive_report_version(store, document, *, parent=None):
    """Freeze a verified report before HEAD changes; byte-identical retries reuse it."""
    if parent is not None and not valid_version_ref(parent):
        raise ValueError("report parent version reference is invalid")
    if document.get("kind") != "research_report":
        raise ValueError("only a verified report can be versioned")
    identity_keys = ("publication_id", "report_id", "research_id", "branch_ref",
                     "owner_identity_id", "keycloak_resource_id")
    if any(not isinstance(document.get(k), str) or not document[k].strip()
           or len(document[k]) > 512 for k in identity_keys):
        raise ValueError("report version identity is incomplete")
    entries = document.get("_attachments", {})
    if (not isinstance(entries, dict) or len(entries) > 260
            or any(not isinstance(name, str) or not name or len(name) > 512
                   for name in entries)):
        raise ValueError("report version attachment inventory is invalid")
    body = {k: deepcopy(v) for k, v in document.items()
            if k not in {"_rev", "_attachments", "version_ref", "parent_version_ref"}}
    if len(_encoded(body)) > 4 * 1024 * 1024:
        raise ValueError("report version metadata exceeds its limit")
    if parent is not None:
        read_report_version(store, parent, identity=document)
    recipes, total = {}, 0
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValueError("report attachment metadata is invalid")
        if "data" in entry:
            encoded = entry["data"]
            if not isinstance(encoded, str) or len(encoded) > (MAX_VERSION_BYTES + 2) // 3 * 4:
                raise ValueError("report version attachment exceeds its limit")
            data = base64.b64decode(encoded, validate=True)
        else:
            revision = document.get('_rev')
            if not isinstance(revision, str) or not revision:
                raise ValueError('report attachment stub requires its captured revision')
            status, data = store._request('GET', document['_id'] + '/' + quote(name, safe='')
                                          + '?rev=' + quote(revision, safe=''), maximum_bytes=MAX_VERSION_BYTES)
            if status != 200:
                raise OSError('report version attachment was not confirmed')
        total += len(data)
        if total > MAX_VERSION_BYTES:
            raise ValueError("report version exceeds its byte budget")
        recipes[name] = {**_save_bytes(store, data), "content_type": entry.get("content_type", "application/octet-stream")}
    value = {"kind": "research_report_version", "schema_version": 1,
             "parent": parent, "document": body, "attachments": recipes}
    if len(_encoded(value)) > 4 * 1024 * 1024:
        raise ValueError("report version metadata exceeds its limit")
    ref = _VERSION + _digest(_encoded(value))
    _put_immutable(store, ref, {"_id": ref, **value})
    return ref


def read_report_version(store, ref, *, identity, include_bytes=False):
    """Require the caller's already-authorized report identity for every version."""
    if not valid_version_ref(ref):
        raise ValueError("report version reference is invalid")
    value = _get(store, ref)
    content = {k: v for k, v in value.items() if k not in {"_id", "_rev"}}
    if (value.get("_id") != ref or value.get("kind") != "research_report_version"
            or ref != _VERSION + _digest(_encoded(content))):
        raise ValueError("report version content checksum differs")
    document = value.get("document")
    keys = ("publication_id", "report_id", "research_id", "branch_ref", "owner_identity_id", "keycloak_resource_id")
    if not isinstance(document, dict) or any(not identity.get(k) or document.get(k) != identity[k] for k in keys):
        raise PermissionError("report version identity differs")
    result = deepcopy(document)
    result.update(_rev=ref, version_ref=ref, parent_version_ref=value["parent"])
    if include_bytes:
        result["_attachments"] = {}
        total = 0
        for name, entry in value["attachments"].items():
            recipe = {k: v for k, v in entry.items() if k != "content_type"}
            total += recipe.get("size_bytes", MAX_VERSION_BYTES + 1)
            if total > MAX_VERSION_BYTES:
                raise ValueError("report version exceeds its byte budget")
            data = _load_bytes(store, recipe)
            result["_attachments"][name] = {"content_type": entry["content_type"],
                                           "data": base64.b64encode(data).decode("ascii")}
    return result
