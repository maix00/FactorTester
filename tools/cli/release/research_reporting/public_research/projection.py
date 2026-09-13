"""Build a source-free report projection for upload to Manager 7998."""

from __future__ import annotations

import hashlib
import json
import re
import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .attachments import build_related_objects


_MARKDOWN_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")
# A few older report components stored a local URI as plain text instead of
# wrapping it in Markdown.  Only recognize explicit local schemes here; bare
# filesystem paths remain redacted and are never read implicitly.
_BARE_LOCAL_REF = re.compile(
    r"(?<![A-Za-z0-9_])(?:factortester://file(?:/|%2F)[^\s<>\]\[\"']+|file:///[^\s<>\]\[\"']+)"
)
_LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home)/[^\s)\]}>]+")
_LOCAL_RESOURCE_MAX_BYTES = 8 * 1024 * 1024
_LOCAL_RESOURCE_TOTAL_BYTES = 20 * 1024 * 1024
_ASSET_MAX_BYTES = 8 * 1024 * 1024
_ASSET_TOTAL_BYTES = 20 * 1024 * 1024
_ASSET_MEDIA_TYPES = {
    "image/gif", "image/jpeg", "image/png", "image/svg+xml", "image/webp",
}


class _LocalResources(dict[str, dict[str, Any]]):
    """Collect bounded, source-free snapshots of report-local references."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        *,
        include_content_base64: bool = True,
    ) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.include_content_base64 = include_content_base64
        self.total_bytes = 0


def build_upload_projection(
    snapshot: dict[str, Any],
    *,
    asset_refs: set[str] | None = None,
    include_local_resource_bytes: bool = True,
    include_asset_bytes: bool = True,
    include_component_content: bool = True,
) -> dict[str, Any]:
    """Freeze display content while withholding every owner-local path."""
    resources = _LocalResources(
        snapshot,
        include_content_base64=include_local_resource_bytes,
    )
    assets = public_assets(
        snapshot,
        asset_refs=asset_refs,
        include_content_bytes=include_asset_bytes,
    )
    bindings = public_bindings(snapshot.get("bindings") or [], resources)
    if not include_component_content:
        # Capture local references before dropping bodies/content from the
        # metadata response.  The resource index must remain complete so a
        # later component request can still open a file-backed link.
        for item in snapshot.get("components") or []:
            _public_text(str(item.get("body") or ""), resources)
            public_value(item.get("content"), resources)
    related_objects, attachments = build_related_objects(snapshot, bindings)
    binding_ids_by_component: dict[str, list[str]] = {}
    for binding in bindings:
        binding_ids_by_component.setdefault(binding["component_id"], []).append(binding["binding_id"])
    payload: dict[str, Any] = {
        "schema_version": 2,
        "report_id": str(snapshot["head"]["report_id"]),
        "title": _public_text(str(snapshot["head"]["title"]), resources),
        "language": snapshot["head"].get("language") or "zh-Hans",
        "generation": int(snapshot["head"]["generation"]),
        "updated_at": snapshot.get("updated_at", 0),
        "content_lazy": not include_component_content,
        "components": [
            public_component(
                item, assets, resources, binding_ids_by_component,
                include_content=include_component_content,
            )
            for item in snapshot["components"]
        ],
        "bindings": bindings,
        "assets": list(assets.values()),
        "local_resources": list(resources.values()),
        "related_objects": related_objects,
        "attachments": attachments,
    }
    payload["projection_hash"] = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def projection_index(projection: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded report metadata needed before a chapter is opened."""
    components = projection.get("components") or []
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for component in components:
        by_parent.setdefault(component.get("parent_id"), []).append(component)
    chapters = []
    for component in by_parent.get(None, []):
        if component.get("kind") != "chapter":
            continue
        children = by_parent.get(component.get("component_id"), [])
        preview = next((str(item.get("title") or "") for item in children if item.get("title")), "")
        chapters.append({
            "component_id": component.get("component_id"),
            "title": component.get("title") or "",
            "created_at": component.get("created_at"),
            "graph_version": component.get("graph_version"),
            "preview": preview,
        })
    return {
        "schema_version": projection.get("schema_version", 2),
        "report_id": projection.get("report_id", ""),
        "title": projection.get("title", ""),
        "language": projection.get("language", "zh-Hans"),
        "generation": projection.get("generation", 0),
        "updated_at": projection.get("updated_at", 0),
        "projection_hash": projection.get("projection_hash", ""),
        "chapters": chapters,
        **({"authoring_bundle": projection["authoring_bundle"]}
           if projection.get("authoring_bundle") else {}),
    }


def build_upload_index(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build an index directly from a bounded local tree read."""
    head = snapshot.get("head") or {}
    chapters = snapshot.get("chapter_descriptors")
    if not isinstance(chapters, list):
        chapters = projection_index(
            build_upload_projection(
                snapshot,
                include_local_resource_bytes=False,
                include_asset_bytes=False,
            ),
        )["chapters"]
    value = {
        "schema_version": 2,
        "report_id": str(head.get("report_id") or ""),
        "title": _public_text(str(head.get("title") or ""), {}),
        "language": head.get("language") or "zh-Hans",
        "generation": int(head.get("generation") or 0),
        "updated_at": snapshot.get("updated_at", 0),
        "chapters": chapters,
    }
    value["projection_hash"] = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def read_local_resource(
    snapshot: dict[str, Any], resource_id: str,
) -> tuple[bytes, str, str] | None:
    """Read one report-local resource without building the full projection.

    The report route already has a complete authoring snapshot, but a resource
    click should not make ``build_upload_projection`` walk every component,
    read every referenced file, and base64-encode the whole attachment set.
    Resolve only the source target whose content-addressed id was requested.
    """
    normalized_id = str(resource_id or "").lower()
    if not re.fullmatch(r"[0-9a-f]{24}", normalized_id):
        return None
    resources = _LocalResources(snapshot)
    for target in _local_targets(snapshot):
        candidate_id = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
        if candidate_id != normalized_id:
            continue
        path = _resolve_local_resource(resources, target)
        if path is None:
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        if not raw or len(raw) > _LOCAL_RESOURCE_MAX_BYTES:
            return None
        return (
            raw,
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            path.name,
        )
    return None


def read_local_asset(
    snapshot: dict[str, Any], asset_id: str,
) -> tuple[bytes, str, str] | None:
    """Read one owner-local report asset without building a chapter payload."""
    normalized_id = str(asset_id or "").lower()
    if not re.fullmatch(r"[a-f0-9]{24}", normalized_id):
        return None
    root = snapshot.get("paths", {}).get("root")
    if root is None:
        return None
    root_path = Path(root)
    for value in snapshot.get("head", {}).get("assets") or []:
        asset_ref = str(value.get("asset_ref") or "")
        if asset_id_for(asset_ref) != normalized_id:
            continue
        media_type = str(value.get("media_type") or "")
        if media_type not in _ASSET_MEDIA_TYPES:
            return None
        filename = Path(str(value.get("filename") or "image")).name
        candidates = [
            root_path / "assets" / filename,
            root_path.parent / "assets" / filename,
        ]
        external_ref = str(value.get("external_ref") or "").strip()
        artifact_path = _job_artifact_path(external_ref, filename)
        if artifact_path is not None:
            candidates.append(artifact_path)
        expected_hash = str(value.get("content_hash") or "")
        for path in candidates:
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if (
                not raw
                or len(raw) > _ASSET_MAX_BYTES
                or not expected_hash
                or hashlib.sha256(raw).hexdigest() != expected_hash
            ):
                continue
            return raw, media_type, filename
        return None
    return None


def component_content_revision(value: dict[str, Any]) -> str:
    """Detect in-place payload edits even when structural metadata is unchanged."""
    payload = {key: value.get(key) for key in ("body", "content")}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()


def chapter_projection(
    projection: dict[str, Any], chapter_id: str, *, include_content: bool = True,
) -> dict[str, Any]:
    """Return one chapter and its descendants without duplicating other chapters."""
    components = projection.get("components") or []
    by_id = {str(item.get("component_id")): item for item in components}
    chapter_id = str(chapter_id or "")
    chapter = by_id.get(chapter_id)
    if not chapter or chapter.get("kind") != "chapter":
        raise ValueError("report chapter was not found")
    children_by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for item in components:
        children_by_parent.setdefault(item.get("parent_id"), []).append(item)
    selected: list[dict[str, Any]] = []
    pending = [chapter_id]
    while pending:
        current = pending.pop(0)
        item = by_id.get(current)
        if item is None:
            continue
        selected.append(item)
        pending.extend(str(child.get("component_id")) for child in children_by_parent.get(current, []))
    selected_ids = {str(item.get("component_id")) for item in selected}
    selected_output = selected
    if not include_content:
        selected_output = []
        for item in selected:
            value = dict(item)
            value["content_available"] = bool(
                value.get("body") or value.get("content") is not None
            )
            value["content_revision"] = component_content_revision(item)
            value["body"] = ""
            value["content"] = None
            selected_output.append(value)
    bindings = [item for item in projection.get("bindings") or []
                if str(item.get("component_id")) in selected_ids]
    if not include_content:
        # A chapter metadata request is used to build the visible tree, not to
        # render reference detail pages.  Keep the routing identity and the
        # optional Job port, but do not repeat frozen factor/source snapshots
        # for every binding.  The full binding remains available from the
        # component endpoint and from the complete publication projection.
        bindings = [metadata_binding(item) for item in bindings]
    component_asset_refs = component_asset_references(selected)
    assets = []
    for item in projection.get("assets") or []:
        asset_id = str(item.get("asset_id") or item.get("asset_ref") or "")
        asset_ref = str(item.get("asset_ref") or "")
        if asset_id in component_asset_refs or asset_ref in component_asset_refs:
            assets.append(item)
    related = [item for item in projection.get("related_objects") or []
               if str(item.get("object_ref") or "") in {
                   str(binding.get("target_ref") or "") for binding in bindings
               }]
    attachment_refs = {
        str(ref) for item in related for ref in (item.get("attachment_refs") or [])
    }
    attachments = [item for item in projection.get("attachments") or []
                   if str(item.get("attachment_ref") or "") in attachment_refs]
    selected_text = json.dumps(selected, ensure_ascii=False)
    resource_ids = set(re.findall(r"factortester-local://([a-f0-9]{24})", selected_text))
    result = {
        "schema_version": projection.get("schema_version", 2),
        "report_id": projection.get("report_id", ""),
        "title": projection.get("title", ""),
        "language": projection.get("language", "zh-Hans"),
        "generation": projection.get("generation", 0),
        "updated_at": projection.get("updated_at", 0),
        "projection_hash": projection.get("projection_hash", ""),
        "chapter_id": chapter_id,
        "content_lazy": not include_content,
        "components": selected_output,
        "bindings": bindings,
        "assets": assets,
        "local_resources": [
            item for item in projection.get("local_resources") or []
            if str(item.get("resource_id") or "") in resource_ids
        ],
        "related_objects": related,
        "attachments": attachments,
    }
    return result


def metadata_binding(value: dict[str, Any]) -> dict[str, Any]:
    """Return the compact binding shape required by chapter rendering.

    Report links need a stable target, display label, kind and component
    ownership.  Only Job links use a binding data field during navigation: a
    valid port selects the correct service endpoint.  Factor revisions,
    source paths and object snapshots are intentionally deferred until the
    component/reference detail is opened.
    """
    item = {
        "binding_id": str(value.get("binding_id") or ""),
        "component_id": str(value.get("component_id") or ""),
        "kind": str(value.get("kind") or ""),
        "target_ref": str(value.get("target_ref") or ""),
        "label": str(value.get("label") or ""),
    }
    data = value.get("data")
    if isinstance(data, dict) and "port" in data:
        port = data.get("port")
        if isinstance(port, int) and 1 <= port <= 65_535:
            item["data"] = {"port": port}
    return item


def component_projection(
    projection: dict[str, Any], chapter_id: str, component_id: str,
) -> dict[str, Any]:
    """Return one full component payload from a public chapter projection."""
    chapter = chapter_projection(projection, chapter_id)
    component = next(
        (
            item for item in chapter.get("components") or []
            if str(item.get("component_id") or "") == str(component_id)
        ),
        None,
    )
    if component is None:
        raise ValueError("report component was not found")
    selected_ids = {str(component.get("component_id") or "")}
    bindings = [
        item for item in chapter.get("bindings") or []
        if str(item.get("component_id") or "") in selected_ids
    ]
    asset_refs = component_asset_references([component])
    assets = [
        item for item in chapter.get("assets") or []
        if str(item.get("asset_id") or item.get("asset_ref") or "") in asset_refs
        or str(item.get("asset_ref") or "") in asset_refs
    ]
    related = [
        item for item in chapter.get("related_objects") or []
        if str(item.get("object_ref") or "") in {
            str(binding.get("target_ref") or "") for binding in bindings
        }
    ]
    attachment_refs = {
        str(ref) for item in related for ref in (item.get("attachment_refs") or [])
    }
    return {
        **{key: chapter.get(key) for key in (
            "schema_version", "report_id", "title", "language", "generation",
            "projection_hash", "chapter_id",
        )},
        "component_id": str(component_id),
        "components": [component],
        "bindings": bindings,
        "assets": assets,
        "local_resources": [
            item for item in chapter.get("local_resources") or []
            if str(item.get("resource_id") or "") in re.findall(
                r"factortester-local://([a-f0-9]{24})",
                json.dumps(component, ensure_ascii=False),
            )
        ],
        "related_objects": related,
        "attachments": [
            item for item in chapter.get("attachments") or []
            if str(item.get("attachment_ref") or "") in attachment_refs
        ],
    }


def public_assets(
    snapshot: dict[str, Any],
    *,
    asset_refs: set[str] | None = None,
    include_content_bytes: bool = True,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    values = snapshot["head"].get("assets") or []
    root = snapshot.get("paths", {}).get("root")
    # report_tree_paths.root is the branch's authoring directory while
    # staged assets live beside it at <branch>/assets.  Keep both candidates
    # so callers with an older snapshot layout still publish safely.
    asset_roots = []
    if root is not None:
        root_path = Path(root)
        asset_roots.extend((root_path.parent / "assets", root_path / "assets"))
    # Base64 expands the upload; keep the encoded JSON comfortably below the
    # manager's 32 MiB request limit.
    total_bytes = 0
    for value in values:
        if asset_refs is not None:
            asset_ref = str(value.get("asset_ref") or "")
            if asset_ref not in asset_refs and asset_id_for(asset_ref) not in asset_refs:
                continue
        media_type = str(value.get("media_type") or "")
        if media_type not in _ASSET_MEDIA_TYPES:
            continue
        asset_id = asset_id_for(str(value["asset_ref"]))
        item = {
            "asset_id": asset_id,
            "media_type": media_type,
            "filename": str(value.get("filename") or "image").split("/")[-1],
            "caption": _plain_text(str(value.get("caption") or "")),
            "alt_text": _plain_text(str(value.get("alt_text") or "")),
            "content_hash": str(value.get("content_hash") or ""),
        }
        external_ref = str(value.get("external_ref") or "").strip()
        if _job_artifact_path(external_ref, item["filename"]) is not None:
            item["external_ref"] = external_ref
        if not include_content_bytes:
            result[asset_id] = item
            continue
        # The manager has no access to the owner's worktree.  Carry bounded,
        # content-addressed bytes once during publication; the manager stores
        # them separately and serves them through the authenticated/public
        # publication asset route.
        for asset_root in asset_roots:
            path = asset_root / item["filename"]
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if raw and len(raw) <= _ASSET_MAX_BYTES and total_bytes + len(raw) <= _ASSET_TOTAL_BYTES:
                if hashlib.sha256(raw).hexdigest() == item["content_hash"]:
                    item["content_base64"] = base64.b64encode(raw).decode("ascii")
                    total_bytes += len(raw)
                    break
        # Job-produced figures are deliberately kept outside the report
        # package.  During publication the owner client is still the only
        # place that can resolve this immutable artifact reference, so copy
        # the bytes into the source-free publication just like package assets.
        if "content_base64" not in item:
            path = _job_artifact_path(external_ref, item["filename"])
            if path is not None:
                try:
                    raw = path.read_bytes()
                except OSError:
                    raw = b""
                if (
                    raw and len(raw) <= _ASSET_MAX_BYTES
                    and total_bytes + len(raw) <= _ASSET_TOTAL_BYTES
                    and hashlib.sha256(raw).hexdigest() == item["content_hash"]
                ):
                    item["content_base64"] = base64.b64encode(raw).decode("ascii")
                    total_bytes += len(raw)
        result[asset_id] = item
    return result


def component_asset_references(components: list[dict[str, Any]]) -> set[str]:
    """Return asset refs/ids reachable from a bounded component list."""
    references: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"asset_ref", "asset_id"} and isinstance(item, str) and item:
                    references.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(components)
    return references


def _job_artifact_path(external_ref: str, filename: str) -> Path | None:
    """Resolve only the stable, owner-local Job artifact URI form.

    Publication must never follow arbitrary file URLs or paths from a report.
    The report writer emits ``factortester-artifact://jobs/<job>/<name>``;
    validate both identifiers before deriving the standard FactorTester jobs
    directory and use the already frozen asset filename for the leaf.
    """
    parsed = urlparse(external_ref)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "factortester-artifact"
        or parsed.netloc != "jobs"
        or len(parts) != 2
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", parts[0])
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,255}", parts[1])
    ):
        return None
    if any(part in {".", ".."} for part in parts):
        return None
    from tools.cli.release.job_cache import cached_job_artifact, default_job_cache_root
    cached = cached_job_artifact(job_id=parts[0], name=parts[1])
    if cached is not None:
        return Path(cached["path"])
    safe_name = Path(filename).name
    if not safe_name or parts[1] not in {safe_name, Path(safe_name).stem}:
        return None
    return default_job_cache_root() / parts[0] / safe_name


def public_component(
    value: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    binding_ids_by_component: dict[str, list[str]] | None = None,
    *, include_content: bool = True,
) -> dict[str, Any]:
    content_available = bool(value.get("body") or value.get("content") is not None)
    content = public_value(value.get("content"), resources) if include_content else None
    if include_content and value.get("kind") == "image" and isinstance(value.get("content"), dict):
        asset_id = asset_id_for(str(value["content"].get("asset_ref") or ""))
        content = {"asset_id": asset_id} if asset_id in assets else None
    component_id = str(value["component_id"])
    return {
        "component_id": component_id,
        "parent_id": value.get("parent_id"),
        "kind": str(value["kind"]),
        "title": _public_text(str(value.get("title") or ""), resources),
        "body": _public_text(str(value.get("body") or ""), resources) if include_content else "",
        "content": content,
        "content_available": content_available,
        "content_revision": component_content_revision(value),
        "display_kind": str(value.get("display_kind") or ""),
        "binding_ids": (binding_ids_by_component or {}).get(component_id, []),
        "created_at": value.get("created_at"),
        "graph_version": value.get("graph_version"),
    }


def public_bindings(
    values: list[dict[str, Any]],
    resources: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Expose only the stable fields needed by the two report renderers."""
    resources = resources if resources is not None else {}
    result = []
    for value in values:
        item = {
            "binding_id": str(value.get("binding_id") or ""),
            "component_id": str(value.get("component_id") or ""),
            "kind": str(value.get("kind") or ""),
            "target_ref": str(value.get("target_ref") or ""),
            "label": _public_text(str(value.get("label") or ""), resources),
        }
        data = value.get("data")
        if isinstance(data, dict):
            item["data"] = public_value(data, resources)
        if item["binding_id"] and item["target_ref"]:
            result.append(item)
    return result


def public_value(value: Any, resources: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        return _public_text(value, resources)
    if isinstance(value, list):
        return [public_value(item, resources) for item in value]
    if isinstance(value, dict):
        return {
            str(key): public_value(item, resources)
            for key, item in value.items()
            if str(key) not in {
                "local_ref", "workspace_root", "receipt_path", "source_path",
            }
        }
    return value


def _public_text(
    value: str, resources: dict[str, dict[str, Any]],
) -> str:
    def replace_link(match: re.Match[str]) -> str:
        image, label, target = match.groups()
        target = target.strip()
        parsed = urlparse(target)
        scheme = parsed.scheme.lower()
        if scheme in {"http", "https"}:
            return match.group(0)
        if scheme == "file" or (scheme == "factortester" and parsed.netloc == "file") or not scheme:
            if target.startswith("#"):
                return match.group(0)
            resource_id = _capture_local_resource(resources, target, label)
            if resource_id:
                prefix = "!" if image else ""
                return f"{prefix}[{label}](factortester-local://{resource_id})"
            return label
        if scheme == "factortester" and not image:
            kind = urlparse(target.strip()).netloc.lower()
            if kind in {
                "job", "evidence", "factor", "factor-family", "factor-set",
                "product", "product-group", "contract", "continuous-contract",
                "continuous_contract", "profile", "profile-revision", "run",
                "run_spec", "trial_plan", "obligation", "requirement",
                "report_requirement", "entry_requirement", "claim", "task",
                "artifact", "graph_reference", "checkpoint", "delta", "file",
                "url",
            }:
                return match.group(0)
        if scheme == "factortester-artifact" and not image:
            resource_id = _capture_local_resource(resources, target, label)
            return f"[{label}](factortester-local://{resource_id})" if resource_id else label
        return label

    result = _MARKDOWN_LINK.sub(replace_link, value)

    def replace_bare(match: re.Match[str]) -> str:
        target = match.group(0).rstrip(".,;:，。；）)>")
        label = Path(unquote(urlparse(target).path)).name or "本地文件"
        resource_id = _capture_local_resource(resources, target, label)
        if resource_id:
            return f"[{label}](factortester-local://{resource_id})"
        # Keep an explicit, typed link visible even when the source file is no
        # longer available.  The renderer can show the file icon and explain
        # that the publication did not include its bytes.
        return f"[{label}](factortester-local://{hashlib.sha256(target.encode('utf-8')).hexdigest()[:24]})"

    result = _BARE_LOCAL_REF.sub(replace_bare, result)
    result = re.sub(r"file://[^\s)\]}>]+", "[本地路径已隐藏]", result)
    return _LOCAL_PATH.sub("[本地路径已隐藏]", result)


def _capture_local_resource(
    resources: dict[str, dict[str, Any]], target: str, label: str,
) -> str:
    resource_id = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
    if resource_id in resources:
        return resource_id
    parsed = urlparse(target)
    item: dict[str, Any] = {
        "resource_id": resource_id,
        "title": _plain_text(label) or "本地文件",
        "filename": Path(unquote(parsed.path)).name or "resource",
        "media_type": "application/octet-stream",
        "available": False,
    }
    path = _resolve_local_resource(resources, target)
    if path is not None:
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        collector = resources if isinstance(resources, _LocalResources) else None
        total = collector.total_bytes if collector is not None else 0
        if raw and len(raw) <= _LOCAL_RESOURCE_MAX_BYTES and total + len(raw) <= _LOCAL_RESOURCE_TOTAL_BYTES:
            item.update({
                "filename": path.name,
                "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "available": True,
            })
            if collector is None or collector.include_content_base64:
                item["content_base64"] = base64.b64encode(raw).decode("ascii")
            if collector is not None:
                collector.total_bytes += len(raw)
    resources[resource_id] = item
    return resource_id


def _local_targets(snapshot: dict[str, Any]) -> list[str]:
    """Find explicit local link targets without interpreting arbitrary paths."""
    targets: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            for match in _MARKDOWN_LINK.finditer(value):
                target = match.group(3).strip()
                parsed = urlparse(target)
                scheme = parsed.scheme.lower()
                if target.startswith("#") or scheme in {
                    "http", "https",
                }:
                    continue
                if not scheme or scheme in {"file", "factortester-artifact"} or (
                    scheme == "factortester" and parsed.netloc == "file"
                ):
                    targets.add(target)
            for match in _BARE_LOCAL_REF.finditer(value):
                targets.add(match.group(0).rstrip(".,;:，。；）)>")
                )
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(snapshot.get("head"))
    visit(snapshot.get("components"))
    visit(snapshot.get("bindings"))
    return sorted(targets)


def _resolve_local_resource(
    resources: dict[str, dict[str, Any]], target: str,
) -> Path | None:
    parsed = urlparse(target)
    if parsed.scheme == "factortester-artifact":
        return _job_artifact_path(target, Path(parsed.path).name)
    if parsed.scheme == "file":
        candidate = Path(unquote(parsed.path)).expanduser()
        roots = _allowed_resource_roots(resources)
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        package_root = _package_root(resources)
        branch_root = _branch_root(resources)
        if (
            package_root is not None
            and _is_relative_to(resolved, package_root / "branches")
            and branch_root is not None
            and not _is_relative_to(resolved, branch_root)
        ):
            return None
        return resolved if any(_is_relative_to(resolved, root) for root in roots) else None
    relative = unquote(parsed.path or parsed.netloc)
    if parsed.scheme == "factortester" and parsed.netloc == "file":
        relative = relative.lstrip("/")
    if not relative or relative.startswith("/"):
        return None
    relative_path = Path(relative)
    if ".." in relative_path.parts:
        return None
    roots = _allowed_resource_roots(resources)
    package_root = _package_root(resources)
    branch_root = _branch_root(resources)
    for root in roots:
        # The package root contains every branch.  It is needed for shared
        # research assets such as ``research/...`` and ``research-methods``
        # but must never expose a sibling branch through a relative link.
        if (
            package_root is not None
            and root == package_root
            and relative_path.parts[:1] == ("branches",)
        ):
            continue
        candidate = (root / relative_path).resolve()
        if not _is_relative_to(candidate, root) or not candidate.is_file():
            continue
        if (
            package_root is not None
            and _is_relative_to(candidate, package_root / "branches")
            and branch_root is not None
            and not _is_relative_to(candidate, branch_root)
        ):
            continue
        if candidate.is_file():
            return candidate
    return None


def _allowed_resource_roots(resources: dict[str, dict[str, Any]]) -> list[Path]:
    snapshot = getattr(resources, "snapshot", {})
    root = snapshot.get("paths", {}).get("root") if isinstance(snapshot, dict) else None
    if root is None:
        return []
    root_path = Path(root).expanduser().resolve()
    roots = [root_path, root_path.parent]
    package_root = _package_root(resources)
    if package_root is not None:
        roots.append(package_root)
    return roots


def _branch_root(resources: dict[str, dict[str, Any]]) -> Path | None:
    snapshot = getattr(resources, "snapshot", {})
    root = snapshot.get("paths", {}).get("root") if isinstance(snapshot, dict) else None
    if root is None:
        return None
    root_path = Path(root).expanduser().resolve()
    return root_path.parent if root_path.name == "authoring" else None


def _package_root(resources: dict[str, dict[str, Any]]) -> Path | None:
    branch_root = _branch_root(resources)
    if branch_root is None or branch_root.parent.name != "branches":
        return None
    return branch_root.parent.parent


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _plain_text(value: str) -> str:
    return _LOCAL_PATH.sub("[本地路径已隐藏]", value)


def asset_id_for(asset_ref: str) -> str:
    return hashlib.sha256(asset_ref.encode("utf-8")).hexdigest()[:24]
