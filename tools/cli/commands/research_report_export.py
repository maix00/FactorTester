"""Export one validated branch report through the CLI authority."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.report_export import (
    document_identity,
    markdown_export,
)

from .research_report_common import output as _output, scope_options
from .research_report_scope import (
    load_authoring,
    resolve_branch_report_scope,
)


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
    work_package_id: str,
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
        work_package_id=work_package_id,
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
    content_hash = sha256(payload).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    if output_format.lower() == "markdown":
        _atomic_write(payload, target)
    else:
        _render_pdf(payload, target)
    _output(
        {
            "output": str(target),
            "format": output_format.lower(),
            "bytes": target.stat().st_size,
            "content_hash": content_hash,
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
    with tempfile.NamedTemporaryFile(
        dir=target.parent, prefix=f".{target.name}.", delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _render_pdf(payload: bytes, target: Path) -> None:
    renderer = _resolve_pdf_renderer()
    with tempfile.NamedTemporaryFile(
        suffix=".md", prefix=".factortester-report-", delete=False,
    ) as stream:
        source = Path(stream.name)
        stream.write(payload)
    try:
        process = subprocess.run(
            [str(renderer), "--input", str(source), "--output", str(target)],
            capture_output=True,
            text=True,
        )
    finally:
        source.unlink(missing_ok=True)
    if process.returncode == 0 and target.is_file():
        return
    detail = (process.stderr or process.stdout).strip()
    target.unlink(missing_ok=True)
    raise click.ClickException(
        detail or "native PDF renderer did not create an output file"
    )


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
