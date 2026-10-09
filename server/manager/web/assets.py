"""Static research UI and event fan-out for Worktree Manager 7998."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Iterable


_REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = Path(__file__).resolve().parent
KATEX_ROOT = _REPO_ROOT / "apple" / "Resources" / "ThirdParty" / "KaTeX"
VENDOR_ROOT = _REPO_ROOT / "static" / "vendor"


def _asset_location(relative: str, roots: tuple[Path, Path, Path]) -> tuple[Path, str]:
    web_root, katex_root, vendor_root = roots
    if relative.startswith("katex/"):
        return katex_root, relative.removeprefix("katex/")
    if relative.startswith("vendor/"):
        return vendor_root, relative.removeprefix("vendor/")
    return web_root, relative


def _module_manifest() -> dict[str, object]:
    raw = (WEB_ROOT / "module-manifest.json").read_bytes()
    return _parse_module_manifest(
        raw,
        str(WEB_ROOT.resolve()),
        str(KATEX_ROOT.resolve()),
        str(VENDOR_ROOT.resolve()),
    )


@lru_cache(maxsize=4)
def _parse_module_manifest(
    raw: bytes,
    web_root_value: str,
    katex_root_value: str,
    vendor_root_value: str,
) -> dict[str, object]:
    manifest = json.loads(raw.decode("utf-8"))
    web_root = Path(web_root_value)
    katex_root = Path(katex_root_value)
    vendor_root = Path(vendor_root_value)
    roots = (web_root, katex_root, vendor_root)
    if manifest.get("schema_version") != 1:
        raise RuntimeError("web module manifest schema is unsupported")
    if not isinstance(manifest.get("entry"), str):
        raise RuntimeError("web module manifest entry is invalid")
    paths: list[str] = []
    for key in ("external_styles", "styles", "external_scripts", "scripts", "vendor_assets"):
        values = manifest.get(key, [])
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise RuntimeError(f"web module manifest {key} is invalid")
        paths.extend(values)
    if len(paths) != len(set(paths)):
        raise RuntimeError("web module manifest contains duplicate assets")
    for relative in paths:
        root, owned_path = _asset_location(relative, roots)
        path = (root / owned_path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f"web module manifest asset is missing: {relative}")
    groups = manifest.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise RuntimeError("web module manifest groups are required")
    grouped: list[str] = []
    for group, values in groups.items():
        if not isinstance(group, str) or not group:
            raise RuntimeError("web module manifest group name is invalid")
        if not isinstance(values, list) or not all(
            isinstance(item, str) and item for item in values
        ):
            raise RuntimeError(f"web module manifest group is invalid: {group}")
        grouped.extend(values)
    if set(grouped) != set(manifest["scripts"]):
        raise RuntimeError(
            "web module manifest groups must cover every production script exactly"
        )
    if len(grouped) != len(set(grouped)):
        raise RuntimeError("web module manifest groups contain duplicate scripts")
    style_assets = set(manifest.get("external_styles", [])) | set(manifest.get("styles", []))
    shell_styles = manifest.get(
        "shell_styles", [*manifest.get("external_styles", []), *manifest.get("styles", [])],
    )
    if (
        not isinstance(shell_styles, list)
        or not all(isinstance(item, str) and item for item in shell_styles)
        or len(shell_styles) != len(set(shell_styles))
        or not set(shell_styles).issubset(style_assets)
    ):
        raise RuntimeError("web module manifest shell_styles are invalid")
    group_styles = manifest.get("group_styles", {})
    if not isinstance(group_styles, dict):
        raise RuntimeError("web module manifest group_styles are invalid")
    for group, values in group_styles.items():
        if group not in groups:
            raise RuntimeError(f"web module manifest style group is unknown: {group}")
        if (
            not isinstance(values, list)
            or not all(isinstance(item, str) and item for item in values)
            or len(values) != len(set(values))
            or not set(values).issubset(style_assets)
        ):
            raise RuntimeError(f"web module manifest group styles are invalid: {group}")
    return manifest


def asset_revision() -> str:
    """Return a revision that changes with the manifest or any owned asset."""
    manifest = _module_manifest()
    owned = [
        str(manifest["entry"]),
        *manifest.get("external_styles", []),
        *manifest.get("styles", []),
        *manifest.get("external_scripts", []),
        *manifest.get("scripts", []),
    ]
    digest = hashlib.sha256()
    digest.update((WEB_ROOT / "module-manifest.json").read_bytes())
    roots = (WEB_ROOT, KATEX_ROOT, VENDOR_ROOT)
    for relative in owned:
        root, owned_path = _asset_location(relative, roots)
        path = root / owned_path
        stat = path.stat()
        digest.update(
            f"\0{relative}\0{stat.st_mtime_ns}\0{stat.st_size}".encode("utf-8"),
        )
    return digest.hexdigest()


class PublicResearchEvents:
    """One process-local invalidation stream; report data remains on disk."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._revision = 0
        self._publications: set[str] = set()

    def notify(self, publication_ids: Iterable[str]) -> int:
        with self._condition:
            self._revision += 1
            self._publications.update(str(item) for item in publication_ids)
            self._condition.notify_all()
            return self._revision

    def wait(self, after: int, timeout: float = 20.0) -> tuple[int, set[str]]:
        with self._condition:
            if self._revision <= after:
                self._condition.wait(timeout)
            return self._revision, set(self._publications)

    def acknowledge(self, revision: int) -> None:
        with self._condition:
            if revision == self._revision:
                self._publications.clear()


def shell_bytes() -> bytes:
    """Render the shell from the manifest-owned asset contract.

    ``research.html`` is a template rather than a second, hand-maintained
    dependency list.  Keeping the assembly here gives the static IIFE modules
    one composition seam: moving a module only requires changing
    ``module-manifest.json`` and the same result is served for the root shell
    and the diagnostic ``/research-static/research.html`` URL.
    """
    template = (WEB_ROOT / "research.html").read_text(encoding="utf-8")
    manifest = _module_manifest()
    styles = list(manifest.get(
        "shell_styles", [*manifest.get("external_styles", []), *manifest.get("styles", [])],
    ))
    scripts = list(
        manifest.get("initial_external_scripts", manifest.get("external_scripts", [])),
    )
    initial_groups = manifest.get("initial_groups") or []
    if manifest.get("group_set_bundles") is True and initial_groups:
        # Preserve core → app evaluation order while reducing the parser-blocking
        # shell from one request per module to one cacheable request.
        scripts.append("__groups__/" + ",".join(str(item) for item in initial_groups))
    else:
        # Older embedded clients/servers keep their ordered file path.
        scripts.extend(_initial_scripts(manifest))
    revision = asset_revision()

    def tag_path(relative: str) -> str:
        return html.escape(
            f"/research-static/{relative}?v={revision}", quote=True,
        )

    style_tags = "\n".join(
        f'  <link rel="stylesheet" href="{tag_path(relative)}">'
        for relative in styles
    )
    script_tags = "\n".join(
        f'  <script src="{tag_path(relative)}"></script>'
        for relative in scripts
    )
    if "<!-- FT_STATIC_STYLES -->" not in template:
        raise RuntimeError("research shell is missing the static styles seam")
    if "<!-- FT_STATIC_SCRIPTS -->" not in template:
        raise RuntimeError("research shell is missing the static scripts seam")
    marker = '<meta name="robots" content="noindex,nofollow">'
    if marker not in template:
        raise RuntimeError("research shell is missing the asset revision seam")
    rendered = template.replace(
        marker,
        f'{marker}\n'
        f'  <meta name="ft-client-assets-revision" content="{revision}">\n'
        f'  <meta name="ft-registration-enabled" content="{1 if os.environ.get("FACTORTESTER_ALLOW_PUBLIC_REGISTRATION", "1").strip().lower() in {"1", "true", "yes", "on"} else 0}">',
    )
    rendered = rendered.replace("<!-- FT_STATIC_STYLES -->", style_tags)
    rendered = rendered.replace("<!-- FT_STATIC_SCRIPTS -->", script_tags)
    return rendered.encode("utf-8")


BUNDLE_PREFIX = "__group__"
_BUNDLE_SEPARATOR = b"\n;\n"
_bundle_cache: dict[tuple[str, str], bytes] = {}
_bundle_set_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_MAX_BUNDLE_SET_CACHE_ENTRIES = 16
_bundle_lock = threading.Lock()
_bundle_cache_revision: str | None = None


def group_scripts(group: str) -> list[str]:
    """The declared scripts of one manifest group, in load order."""
    name = str(group or "").strip()
    groups = _module_manifest().get("groups")
    files = groups.get(name) if isinstance(groups, dict) else None
    if not isinstance(files, list) or not files:
        raise ValueError("web module group is not declared")
    return [str(item) for item in files]


def bundle_bytes(group: str) -> bytes:
    """Serve a whole group in one request.

    Every owned module is a self-contained IIFE, so concatenating a group keeps
    the isolation the browser's separate script tags provided while removing
    most of a cold visit's round trips over the public uplink.
    """
    global _bundle_cache_revision
    name = str(group or "").strip()
    revision = asset_revision()
    with _bundle_lock:
        if revision != _bundle_cache_revision:
            _bundle_cache.clear()
            _bundle_set_cache.clear()
            _bundle_cache_revision = revision
        cached = _bundle_cache.get((name, revision))
    if cached is not None:
        return cached
    parts = [static_file(relative)[0] for relative in group_scripts(name)]
    payload = _BUNDLE_SEPARATOR.join(parts)
    with _bundle_lock:
        if revision == _bundle_cache_revision:
            _bundle_cache[(name, revision)] = payload
    return payload


def bundle_bytes_for_groups(groups: Iterable[str]) -> bytes:
    """Return one dependency-ordered bundle for a caller-supplied group closure.

    The browser computes the closure from the manifest and omits groups already
    loaded in that page. Only declared group names and their first-party scripts
    are accepted; external vendor scripts remain separate requests so the
    browser can deduplicate them across route transitions.
    """
    names = [str(item or "").strip() for item in groups]
    if not names or any(not item for item in names) or len(names) != len(set(names)):
        raise ValueError("web module group set is invalid")
    manifest = _module_manifest()
    declared_groups = manifest.get("groups")
    if not isinstance(declared_groups, dict) or any(name not in declared_groups for name in names):
        raise ValueError("web module group is not declared")
    cache_name = "__groups_set__:" + ",".join(names)
    revision = asset_revision()
    global _bundle_cache_revision
    with _bundle_lock:
        if revision != _bundle_cache_revision:
            _bundle_cache.clear()
            _bundle_set_cache.clear()
            _bundle_cache_revision = revision
        cached = _bundle_set_cache.get((cache_name, revision))
        if cached is not None:
            _bundle_set_cache.move_to_end((cache_name, revision))
    if cached is not None:
        return cached
    parts = [
        static_file(str(relative))[0]
        for name in names
        for relative in declared_groups[name]
    ]
    if not parts:
        raise ValueError("web module group set has no scripts")
    payload = _BUNDLE_SEPARATOR.join(parts)
    with _bundle_lock:
        if revision == _bundle_cache_revision:
            key = (cache_name, revision)
            _bundle_set_cache[key] = payload
            _bundle_set_cache.move_to_end(key)
            while len(_bundle_set_cache) > _MAX_BUNDLE_SET_CACHE_ENTRIES:
                _bundle_set_cache.popitem(last=False)
    return payload


def _initial_scripts(manifest: dict) -> list[str]:
    """Return the synchronous shell scripts from the manifest groups.

    The complete ``scripts`` list remains the ownership/declaration boundary,
    while only the small core/app groups are put in the initial document.  A
    browser-side loader fetches the other groups when their route is entered.
    Older test manifests without ``initial_groups`` retain the previous eager
    behavior.
    """
    groups = manifest.get("initial_groups")
    if not groups:
        return list(manifest.get("scripts", []))
    by_group = manifest.get("groups", {})
    return [
        relative
        for group in groups
        for relative in by_group.get(group, [])
    ]


def static_file(relative: str) -> tuple[bytes, str]:
    value = relative.lstrip("/")
    if not value or ".." in value.split("/"):
        raise ValueError("static asset path is invalid")
    manifest = _module_manifest()
    if value == manifest.get("entry", "research.html"):
        return shell_bytes(), "text/html"
    root, owned_path = _asset_location(value, (WEB_ROOT, KATEX_ROOT, VENDOR_ROOT))
    path = root / owned_path
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("static asset was not found")
    # The manifest is the runtime ownership boundary for our Web modules.
    # Without this check a stale URL could continue loading an old JS/CSS file
    # after a module was moved, making a partial tree migration look healthy.
    # KaTeX keeps additional fonts/assets outside the manifest, so only apply
    # the declaration gate to assets served from our own Web root.
    if root != KATEX_ROOT and path.suffix.lower() in {".js", ".css"}:
        declared = {
            *manifest.get("external_scripts", []),
            *manifest.get("scripts", []),
            *manifest.get("external_styles", []),
            *manifest.get("styles", []),
            *manifest.get("vendor_assets", []),
        }
        if value not in declared:
            raise ValueError("web module asset is not declared in manifest")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return resolved.read_bytes(), content_type


def sse_payload(revision: int, publication_ids: set[str]) -> bytes:
    import json
    return (
        f"id: {revision}\n"
        "event: report-generation\n"
        f"data: {json.dumps({'publication_ids': sorted(publication_ids)})}\n\n"
    ).encode("utf-8")


def heartbeat() -> bytes:
    return f": keepalive {int(time.time())}\n\n".encode("ascii")
