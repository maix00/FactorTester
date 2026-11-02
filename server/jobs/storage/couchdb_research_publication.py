"""Publish one explicitly selected Research report as one CouchDB document.

The caller must authorize the exact report immediately before ``commit``.
There is no account-domain graph, local filesystem path or legacy ACL here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path
from urllib.error import HTTPError

from server.jobs.storage.couchdb_research_reports import document_id
from tools.cli.release.research_reporting.public_research.object_uploads import (
    detach_object_bytes, projection_hash,
)

_KEYS = frozenset({"schema_version", "report_id", "title", "language", "generation", "updated_at",
                   "content_lazy", "components", "bindings", "assets", "local_resources",
                   "related_objects", "attachments", "projection_hash"})
_COLLECTIONS = (("assets", "research_asset", "asset_id"),
                ("attachments", "research_attachment", "attachment_ref"),
                ("local_resources", "research_local_resource", "resource_id"))
_SAFE_MEDIA = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"})
_MAX_PROJECTION = 8 * 1024 * 1024
_MAX_OBJECT = 8 * 1024 * 1024
_MAX_TOTAL_OBJECTS = 20 * 1024 * 1024
_MAX_OBJECTS = 256


class ResearchPublicationConflict(ValueError):
    """The caller's expected CouchDB revision no longer matches."""


def publication_id(manager_id: str, owner_id: str, report_id: str, branch_ref: str) -> str:
    fields = [str(value or "").strip() for value in (manager_id, owner_id, report_id, branch_ref)]
    if any(not field or len(field) > 512 or "\x00" in field for field in fields):
        raise ValueError("report publication identity is invalid")
    canonical = json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "p-" + hashlib.sha256(canonical).hexdigest()


def prepare_projection(raw: object, *, report_id: str) -> tuple[dict, dict, dict]:
    """Validate and detach bounded bodies belonging to this report only."""
    if not isinstance(raw, dict) or set(raw) - _KEYS:
        raise ValueError("report projection contains unsupported fields")
    if raw.get("schema_version") != 2 or raw.get("report_id") != report_id:
        raise ValueError("report projection identity is invalid")
    generation = raw.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise ValueError("report projection generation is invalid")
    if not isinstance(raw.get("components"), list):
        raise ValueError("report components are invalid")
    if raw.get("content_lazy") is True:
        raise ValueError("publish requires a complete report projection")
    if raw.get("projection_hash") != projection_hash(raw):
        raise ValueError("report projection hash does not match its contents")
    ids = set()
    for collection, kind, id_key in _COLLECTIONS:
        values = raw.get(collection, [])
        if not isinstance(values, list):
            raise ValueError("report object collection is invalid")
        for item in values:
            if not isinstance(item, dict) or item.get("purpose") == "report_authoring":
                raise ValueError("report object is invalid or requires separate authoring access")
            object_id = str(item.get(id_key) or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", object_id) or (kind, object_id) in ids:
                raise ValueError("report object identity is invalid or duplicated")
            ids.add((kind, object_id))
            if item.get("available") is not False and "content_base64" not in item:
                raise ValueError("available report object bytes were not supplied")
    if len(ids) > _MAX_OBJECTS:
        raise ValueError("report has too many objects")
    clean, uploads = detach_object_bytes(raw)
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > _MAX_PROJECTION or sum(len(item.content) for item in uploads) > _MAX_TOTAL_OBJECTS:
        raise ValueError("report publication exceeds its size limit")
    attachments: dict[str, dict] = {}
    inline: dict[str, dict] = {}
    projection_name = hashlib.sha256(encoded).hexdigest() + ".json"
    attachments["projection.json"] = {"name": projection_name, "content_type": "application/json",
                                      "sha256": hashlib.sha256(encoded).hexdigest(), "size_bytes": len(encoded)}
    inline[projection_name] = {"content_type": "application/json", "data": base64.b64encode(encoded).decode("ascii")}
    for item in uploads:
        if not item.object_id or len(item.content) > _MAX_OBJECT:
            raise ValueError("report object exceeds its size limit")
        name = item.content_hash + ".bin"
        media = item.content_type.lower() if item.content_type.lower() in _SAFE_MEDIA else "application/octet-stream"
        existing = inline.get(name)
        # One content hash has one representation; avoid a second stored copy.
        encoded_object = base64.b64encode(item.content).decode("ascii")
        if existing is not None and existing["data"] != encoded_object:
            raise ValueError("report object digest collision")
        inline[name] = {"content_type": media, "data": encoded_object}
        attachments[f"{item.object_kind}/{item.object_id}"] = {"name": name, "content_type": media,
            "sha256": item.content_hash, "size_bytes": len(item.content)}
    return clean, attachments, inline


def prepare_authoring(raw: object, *, report_id: str, generation: int, branch_ref: str, projection: dict):
    """Validate a bounded editable branch separately from the read projection."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {'content_base64', 'sha256', 'root_ref'}:
        raise ValueError('report authoring bundle is invalid')
    digest, root_ref, encoded = raw['sha256'], raw['root_ref'], raw['content_base64']
    if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or not isinstance(encoded, str) or len(encoded) > ((_MAX_OBJECT + 2) // 3) * 4):
        raise ValueError('report authoring bundle exceeds its limit')
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError('report authoring bundle encoding is invalid') from None
    if not payload or len(payload) > _MAX_OBJECT or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError('report authoring bundle checksum or size mismatch')
    from tools.cli.release.research_reporting.authoring.tree_bundle import validate_report_bundle
    manifest, files = validate_report_bundle(payload=payload, expected_sha256=digest, report_id=report_id,
        source_generation=generation, source_root_ref=root_ref)
    if manifest.get('source_branch_id') != branch_ref:
        raise ValueError('report authoring bundle branch does not match')
    _check_authoring_projection(manifest, files, digest, report_id, projection)
    return {'sha256': digest, 'root_ref': root_ref, 'generation': generation, 'size_bytes': len(payload)}, payload


def _check_authoring_projection(manifest: dict, files: dict, digest: str,
                                report_id: str, projection: dict) -> None:
    """Reject a display projection that differs from its editable source.

    Materialize only into an ephemeral bounded workspace, and never restore
    referenced Job artifacts into the Manager's global cache. This reuses the
    same source-free comparison as client pull rather than a second renderer.
    """
    from tools.cli.release.research_reporting.authoring.tree_bundle import _import_validated_report_bundle
    from tools.cli.release.research_reporting.local_projection_validation import bundle_matches_projection

    if not isinstance(projection, dict) or 'updated_at' not in projection:
        raise ValueError('report projection is missing its update time')
    with tempfile.TemporaryDirectory(prefix='tr-report-verify-') as temporary:
        root = Path(temporary) / 'report'
        imported = _import_validated_report_bundle(manifest=manifest, files=files, expected_sha256=digest,
            package_root=root, branch_id='main', report_id=report_id, restore_artifacts=False)
        if not bundle_matches_projection(package_root=root, source_manifest=imported['source_manifest'],
                                         remote_projection=projection, expected_hash=projection['projection_hash']):
            raise ValueError('report projection and editable source differ')


def commit_shared_report(store, *, manager_id: str, owner_id: str, owner_ref: str,
                         research_id: str, report_id: str, branch_ref: str,
                         keycloak_resource_id: str, projection: dict, expected_revision: str | None,
                         authorize_now, prepared=None, authoring=None) -> dict:
    """Compare-and-set one document and its content-addressed attachments."""
    identifier = publication_id(manager_id, owner_id, report_id, branch_ref)
    clean, attachments, inline = (prepared if prepared is not None
                                  else prepare_projection(projection, report_id=report_id))
    descriptor = None
    if authoring is not None:
        descriptor, payload = authoring
        name = descriptor['sha256'] + '.bin'
        attachments['report_authoring/' + descriptor['sha256']] = {
            'name': name, 'content_type': 'application/octet-stream',
            'sha256': descriptor['sha256'], 'size_bytes': len(payload)}
        encoded = base64.b64encode(payload).decode('ascii')
        if name in inline and inline[name]['data'] != encoded:
            raise ValueError('report object digest collision')
        inline[name] = {'content_type': 'application/octet-stream', 'data': encoded}
    if not isinstance(keycloak_resource_id, str) or not keycloak_resource_id.strip():
        raise ValueError("report Keycloak resource is missing")
    if expected_revision is not None and (not isinstance(expected_revision, str) or len(expected_revision) > 256):
        raise ValueError("expected CouchDB revision is invalid")
    ref = document_id(identifier)
    try:
        status, body = store._request("GET", ref)
        if status != 200:
            raise RuntimeError("report store returned an invalid response")
        current = json.loads(body)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        current = None
    if current is not None:
        if (not isinstance(current, dict) or current.get("kind") != "research_report"
                or current.get("owner_identity_id") != owner_id or current.get("report_id") != report_id
                or current.get("research_id") != research_id or current.get("branch_ref") != branch_ref
                or current.get("keycloak_resource_id") != keycloak_resource_id):
            raise PermissionError("existing report publication identity does not match")
        prior_record = current.get("publication")
        same_content = (current.get("generation") == clean["generation"]
                        and current.get("projection_hash") == clean["projection_hash"]
                        and current.get('authoring') == descriptor
                        and current.get("attachments") == attachments
                        and isinstance(current.get("_attachments"), dict)
                        and set(current["_attachments"]) == set(inline)
                        and isinstance(prior_record, dict) and prior_record.get("owner_ref") == owner_ref
                        and isinstance(current.get("_rev"), str))
        if same_content:
            # A successful response may have been lost; a byte-identical retry
            # is safe after rechecking the current Keycloak authorization.
            authorize_now()
            return {"publication_id": identifier, "revision": current["_rev"],
                    "generation": clean["generation"], "projection_hash": clean["projection_hash"],
                    "report_id": report_id, "idempotent": True}
        if current.get('authoring') is not None and descriptor is None:
            raise ResearchPublicationConflict('editable report cannot be replaced without its authoring bundle')
        if expected_revision != current.get("_rev"):
            raise ResearchPublicationConflict("report publication revision changed")
        old_generation = current.get("generation")
        if not isinstance(old_generation, int) or clean["generation"] < old_generation:
            raise ResearchPublicationConflict("report generation cannot move backwards")
        if clean["generation"] == old_generation and clean["projection_hash"] != current.get("projection_hash"):
            raise ResearchPublicationConflict("one report generation cannot have different content")
        if (clean['generation'] == old_generation and current.get('authoring') is not None
                and current['authoring'] != descriptor):
            raise ResearchPublicationConflict('one report generation cannot have different authoring content')
    elif expected_revision is not None:
        raise ResearchPublicationConflict("report publication no longer exists")
    record = {"publication_id": identifier, "report_id": report_id, "owner_ref": owner_ref,
              "visibility": "private", "authorized_users": [], "title": clean.get("title", ""),
              "generation": clean["generation"], "projection_hash": clean["projection_hash"],
              "branch_ref": branch_ref, "storage_server_id": manager_id}
    doc = {"_id": ref, "kind": "research_report", "publication_id": identifier, "report_id": report_id,
           "research_id": research_id, "branch_ref": branch_ref, "owner_identity_id": owner_id,
           "keycloak_resource_id": keycloak_resource_id, "generation": clean["generation"],
           "projection_hash": clean["projection_hash"], "publication": record,
           "attachments": attachments, "_attachments": inline}
    if descriptor is not None:
        doc['authoring'] = descriptor
    if current is not None:
        doc["_rev"] = current["_rev"]
    # Authorization may change while a large projection is prepared or read.
    # Check the same verified caller immediately before the CouchDB CAS.
    authorize_now()
    try:
        status, response = store._request("PUT", ref, json.dumps(doc, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except HTTPError as exc:
        if exc.code == 409:
            raise ResearchPublicationConflict("report publication revision changed") from None
        raise
    if status not in {201, 202}:
        raise RuntimeError("report store did not confirm the publication")
    result = json.loads(response)
    if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("rev"), str):
        raise RuntimeError("report store returned an invalid publication receipt")
    return {"publication_id": identifier, "revision": result["rev"], "generation": clean["generation"],
            "projection_hash": clean["projection_hash"], "report_id": report_id}
