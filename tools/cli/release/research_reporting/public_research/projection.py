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


class _LocalResources(dict[str, dict[str, Any]]):
    """Collect bounded, source-free snapshots of report-local references."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.total_bytes = 0


def build_upload_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Freeze display content while withholding every owner-local path."""
    resources = _LocalResources(snapshot)
    assets = public_assets(snapshot)
    bindings = public_bindings(snapshot.get("bindings") or [], resources)
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
        "components": [
            public_component(item, assets, resources, binding_ids_by_component)
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


def public_assets(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    allowed = {
        "image/gif", "image/jpeg", "image/png", "image/svg+xml", "image/webp",
    }
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
        media_type = str(value.get("media_type") or "")
        if media_type not in allowed:
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
            if raw and len(raw) <= 8 * 1024 * 1024 and total_bytes + len(raw) <= 20 * 1024 * 1024:
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
                    raw and len(raw) <= 8 * 1024 * 1024
                    and total_bytes + len(raw) <= 20 * 1024 * 1024
                    and hashlib.sha256(raw).hexdigest() == item["content_hash"]
                ):
                    item["content_base64"] = base64.b64encode(raw).decode("ascii")
                    total_bytes += len(raw)
        result[asset_id] = item
    return result


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
    safe_name = Path(filename).name
    if not safe_name or parts[1] not in {safe_name, Path(safe_name).stem}:
        return None
    return Path.home() / "Documents" / "FactorTester" / "jobs" / parts[0] / safe_name


def public_component(
    value: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    resources: dict[str, dict[str, Any]],
    binding_ids_by_component: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    content = public_value(value.get("content"), resources)
    if value.get("kind") == "image" and isinstance(value.get("content"), dict):
        asset_id = asset_id_for(str(value["content"].get("asset_ref") or ""))
        content = {"asset_id": asset_id} if asset_id in assets else None
    component_id = str(value["component_id"])
    return {
        "component_id": component_id,
        "parent_id": value.get("parent_id"),
        "kind": str(value["kind"]),
        "title": _public_text(str(value.get("title") or ""), resources),
        "body": _public_text(str(value.get("body") or ""), resources),
        "content": content,
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
            return match.group(0)
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
                "content_base64": base64.b64encode(raw).decode("ascii"),
            })
            if collector is not None:
                collector.total_bytes += len(raw)
    resources[resource_id] = item
    return resource_id


def _resolve_local_resource(
    resources: dict[str, dict[str, Any]], target: str,
) -> Path | None:
    parsed = urlparse(target)
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
