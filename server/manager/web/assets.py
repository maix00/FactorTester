"""Static research UI and event fan-out for Worktree Manager 7998."""

from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import os
import threading
import time
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
    styles = [*manifest.get("external_styles", []), *manifest.get("styles", [])]
    scripts = [
        *manifest.get("initial_external_scripts", manifest.get("external_scripts", [])),
        *_initial_scripts(manifest),
    ]
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
