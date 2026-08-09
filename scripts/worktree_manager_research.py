"""Static research UI and event fan-out for Worktree Manager 7998."""

from __future__ import annotations

import html
import json
import mimetypes
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable


WEB_ROOT = Path(__file__).resolve().with_name("worktree_manager_web")
KATEX_ROOT = Path(__file__).resolve().parents[1] / "apple" / "Resources" / "ThirdParty" / "KaTeX"


@lru_cache(maxsize=1)
def _module_manifest() -> dict[str, object]:
    manifest = json.loads(
        (WEB_ROOT / "module-manifest.json").read_text(encoding="utf-8"),
    )
    if manifest.get("schema_version") != 1:
        raise RuntimeError("web module manifest schema is unsupported")
    if not isinstance(manifest.get("entry"), str):
        raise RuntimeError("web module manifest entry is invalid")
    paths: list[str] = []
    for key in ("external_styles", "styles", "external_scripts", "scripts"):
        values = manifest.get(key, [])
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise RuntimeError(f"web module manifest {key} is invalid")
        paths.extend(values)
    if len(paths) != len(set(paths)):
        raise RuntimeError("web module manifest contains duplicate assets")
    for relative in paths:
        root = KATEX_ROOT if relative.startswith("katex/") else WEB_ROOT
        path = (root / relative.removeprefix("katex/")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise RuntimeError(f"web module manifest asset is missing: {relative}")
    return manifest


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
    scripts = [*manifest.get("external_scripts", []), *manifest.get("scripts", [])]

    def tag_path(relative: str) -> str:
        return html.escape(f"/research-static/{relative}", quote=True)

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
    rendered = template.replace("<!-- FT_STATIC_STYLES -->", style_tags)
    rendered = rendered.replace("<!-- FT_STATIC_SCRIPTS -->", script_tags)
    return rendered.encode("utf-8")


def static_file(relative: str) -> tuple[bytes, str]:
    value = relative.lstrip("/")
    if not value or ".." in value.split("/"):
        raise ValueError("static asset path is invalid")
    manifest = _module_manifest()
    if value == manifest.get("entry", "research.html"):
        return shell_bytes(), "text/html"
    root = KATEX_ROOT if value.startswith("katex/") else WEB_ROOT
    path = root / value.removeprefix("katex/")
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file():
        raise ValueError("static asset was not found")
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
