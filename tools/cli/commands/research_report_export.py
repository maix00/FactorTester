"""Export one validated branch report through the CLI authority."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import quote, unquote, urlsplit

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.job_cache import cache_job_artifact, cached_job_artifact
from tools.cli.release.research_reporting.report_export import (
    document_identity,
    markdown_export,
)

from .research_report_common import output as _output, scope_options
from .research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)
from tools.cli.core.context import client_from_config


@click.command("export")
@scope_options
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("markdown", "pdf"), case_sensitive=False),
    required=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
)
@click.option("--force", is_flag=True, help="Replace an existing output file.")
@click.option("--json", "as_json", is_flag=True)
def export_report(
    profile_id: str,
    report_workspace_id: str,
    branch_id: str,
    release_profile: Path | None,
    output_format: str,
    output_path: Path,
    force: bool,
    as_json: bool,
) -> None:
    """Export the current structured report as Markdown or PDF."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile),
        profile_id=profile_id,
        report_workspace_id=report_workspace_id,
        branch_id=branch_id,
    )
    snapshot = load_authoring(scope)
    target = output_path.expanduser().resolve()
    _validate_output(target, output_format.lower(), force=force)
    head = snapshot.get("head") or {}
    # The same policy the manager uses, so an exported file carries the branch
    # identity, the export time and the report version wherever it was made.
    payload, _content_type, _filename = markdown_export(
        snapshot, "markdown",
        identity=document_identity(
            branch=scope.branch_id,
            owner=str((scope.profile or {}).get("principal_ref") or ""),
            profile=scope.profile_id,
            generation=head.get("generation") or 0,
            report_id=str(head.get("report_id") or ""),
        ),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if output_format.lower() == "markdown":
        exported = _export_markdown_images(payload, snapshot, scope.package_root, target)
    else:
        _render_pdf(_pdf_image_sources(payload, snapshot, scope.package_root), target)
        exported = payload
    _output(
        {
            "output": str(target),
            "format": output_format.lower(),
            "bytes": target.stat().st_size,
            "content_hash": sha256(exported).hexdigest(),
            "source": str(snapshot["paths"]["head"]),
        },
        as_json,
    )


def _validate_output(target: Path, output_format: str, *, force: bool) -> None:
    expected = ".md" if output_format == "markdown" else ".pdf"
    if target.suffix.lower() != expected:
        raise click.ClickException(
            f"{output_format} export requires a {expected} output filename"
        )
    if target.exists() and not force:
        raise click.ClickException(
            "output already exists; pass --force to replace it"
        )


def _atomic_write(payload: bytes, target: Path) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=f".{target.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _render_pdf(payload: bytes, target: Path) -> None:
    renderer = _resolve_pdf_renderer()
    source: Path | None = None
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".md", prefix=".factortester-report-", delete=False,
        ) as stream:
            source = Path(stream.name)
            stream.write(payload)
        with tempfile.NamedTemporaryFile(
            suffix=".pdf", prefix=f".{target.name}.",
            dir=target.parent, delete=False,
        ) as stream:
            staged = Path(stream.name)
        process = subprocess.run(
            [str(renderer), "--input", str(source), "--output", str(staged)],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0 or not staged.is_file() or staged.stat().st_size == 0:
            detail = (process.stderr or process.stdout).strip()
            raise click.ClickException(
                detail or "native PDF renderer did not create an output file"
            )
        staged.replace(target)
    finally:
        if source is not None:
            source.unlink(missing_ok=True)
        if staged is not None:
            staged.unlink(missing_ok=True)


@dataclass(frozen=True)
class _ReportImage:
    source: str
    path: Path
    digest: str
    extension: str


_IMAGE_EXTENSIONS = {
    "image/svg+xml": ".svg", "image/png": ".png",
    "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif",
}


def _image_reference(source: str) -> re.Pattern[str]:
    return re.compile(r"(!\[[^\]]*\]\()" + re.escape(source) + r"(\))")


def _replace_image_reference(rendered: str, source: str, replacement: str) -> str:
    return _image_reference(source).sub(
        lambda match: match.group(1) + replacement + match.group(2),
        rendered,
    )


def _report_images(payload: bytes, snapshot: dict, package_root: Path) -> list[_ReportImage]:
    """Resolve only referenced images, verifying bytes before either export."""
    rendered = payload.decode("utf-8")
    images: list[_ReportImage] = []
    assets = (snapshot.get("head") or {}).get("assets") or []
    for asset in assets:
        media_type = str(asset.get("media_type") or "").split(";", 1)[0]
        if not media_type.startswith("image/"):
            continue
        external = str(asset.get("external_ref") or "")
        local_ref = str(asset.get("local_ref") or f"assets/{asset.get('filename') or ''}")
        source = external or "../../" + local_ref
        if not _image_reference(source).search(rendered):
            continue
        if external:
            parsed = urlsplit(external)
            segments = [unquote(part) for part in parsed.path.split("/") if part]
            if parsed.scheme != "factortester-artifact" or parsed.netloc != "jobs" or len(segments) != 2:
                raise click.ClickException(f"unsupported report image reference: {external}")
            job_id, name = segments
            expected_hash = str(asset.get("content_hash") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise click.ClickException(
                    f"report image lacks a valid content hash: {external}"
                )
            cached = cached_job_artifact(
                job_id=job_id, name=name, expected_hash=expected_hash,
            )
            if cached is None:
                response = client_from_config().job_artifact(job_id, name)
                raw = bytes(response.content)
                if expected_hash and sha256(raw).hexdigest() != expected_hash:
                    raise click.ClickException(f"report image hash mismatch: {name}")
                cached = cache_job_artifact(
                    job_id=job_id, name=name,
                    filename=str(asset.get("filename") or name),
                    content_type=media_type, raw=raw, server_url="",
                )
            path = Path(cached["path"])
        else:
            path = (package_root / local_ref).resolve()
            if not path.is_relative_to(package_root.resolve()) or not path.is_file():
                raise click.ClickException(f"report image is unavailable: {local_ref}")
            expected_hash = str(asset.get("content_hash") or "")
        digest = sha256(path.read_bytes()).hexdigest()
        if expected_hash and digest != expected_hash:
            raise click.ClickException(f"report image hash mismatch: {source}")
        images.append(_ReportImage(
            source=source, path=path, digest=digest,
            extension=_IMAGE_EXTENSIONS.get(media_type, Path(path.name).suffix.lower() or ".image"),
        ))
    return images


def _pdf_image_sources(payload: bytes, snapshot: dict, package_root: Path) -> bytes:
    """Resolve report image references to verified local files for the renderer.

    Markdown retains portable artifact references.  A PDF needs actual image
    bytes, including the Job images already mounted under a result section.
    Only assets referenced by the rendered document are read or downloaded.
    """
    rendered = payload.decode("utf-8")
    for image in _report_images(payload, snapshot, package_root):
        rendered = _replace_image_reference(
            rendered, image.source, image.path.as_uri(),
        )
    return rendered.encode("utf-8")


def _export_markdown_images(
    payload: bytes, snapshot: dict, package_root: Path, target: Path,
) -> bytes:
    images = _report_images(payload, snapshot, package_root)
    if not images:
        _atomic_write(payload, target)
        return payload
    bundle = target.with_name(f"{target.stem}.assets")
    rendered = payload.decode("utf-8")
    for image in images:
        relative = quote(f"{bundle.name}/{image.digest}{image.extension}", safe="/")
        rendered = _replace_image_reference(rendered, image.source, relative)
    exported = rendered.encode("utf-8")
    bundle.mkdir(exist_ok=True)
    created: list[Path] = []
    try:
        for image in images:
            destination = bundle / f"{image.digest}{image.extension}"
            if destination.exists():
                if sha256(destination.read_bytes()).hexdigest() != image.digest:
                    raise click.ClickException(f"export image is corrupt: {destination.name}")
                continue
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=bundle, prefix=f".{destination.name}.", delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    with image.path.open("rb") as source:
                        shutil.copyfileobj(source, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(destination)
                created.append(destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        _atomic_write(exported, target)
    except BaseException:
        for destination in created:
            destination.unlink(missing_ok=True)
        if not any(bundle.iterdir()):
            bundle.rmdir()
        raise
    return exported


def _resolve_pdf_renderer() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("FACTORTESTER_REPORT_RENDERER", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    executable = Path(sys.executable).resolve()
    candidates.append(executable.parent / "factortester-report-renderer")
    discovered = shutil.which("factortester-report-renderer")
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise click.ClickException(
        "native PDF renderer is unavailable; reinstall or update FTClient"
    )
