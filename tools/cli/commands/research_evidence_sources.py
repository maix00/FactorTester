"""Native source-capture and fragment commands."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import click

from tools.cli.core.context import client_from_config
from tools.cli.protocols.research_evidence_provenance import (
    validate_file_provenance,
)

from .research_evidence_common import (
    emit,
    library_for_profile,
    profile_options,
    read_object,
)
_MAX_SOURCE_BYTES = 8 * 1024 * 1024


def register_source_commands(group: click.Group) -> None:
    group.add_command(source)
    group.add_command(fragment)


@click.group("source")
def source() -> None:
    """Capture immutable Job, terminal, file and web sources."""


@source.command("capture-job")
@click.argument("job_id")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def capture_job(
    job_id: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    value = client_from_config().capture_job_evidence_source(job_id)
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    library.record_source(value)
    emit({
        **value,
        "next_actions": [{
            "action": "select_fragment",
            "argv": [
                "factortester", "research", "evidence", "fragment", "add",
                value["source_ref"], "--profile-id", profile_id, "--help",
            ],
        }],
    }, as_json)


@source.command(
    "capture-terminal",
    context_settings={"ignore_unknown_options": True},
)
@click.argument("argv", nargs=-1, type=click.UNPROCESSED)
@profile_options
@click.option("--timeout", type=click.IntRange(1, 3600), default=60)
@click.option("--json", "as_json", is_flag=True)
def capture_terminal(
    argv: tuple[str, ...],
    profile_id: str,
    release_profile: Path | None,
    timeout: int,
    as_json: bool,
) -> None:
    if not argv:
        raise click.ClickException(
            "command argv is required after capture-terminal options"
        )
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise click.ClickException(str(exc)) from exc
    stdout_hash = hashlib.sha256(completed.stdout).hexdigest()
    stderr_hash = hashlib.sha256(completed.stderr).hexdigest()
    snapshot = json.dumps({
        "argv": list(argv),
        "returncode": completed.returncode,
        "stdout_hash": stdout_hash,
        "stderr_hash": stderr_hash,
    }, sort_keys=True, separators=(",", ":")).encode()
    value = client_from_config().put_research_evidence_source({
        "source_kind": "terminal",
        "identity": {
            "execution_id": hashlib.sha256(snapshot).hexdigest(),
            "argv": list(argv),
        },
        "content_hash": hashlib.sha256(
            snapshot + completed.stdout + completed.stderr
        ).hexdigest(),
        "audit": {
            "returncode": completed.returncode,
            "stdout_hash": stdout_hash,
            "stderr_hash": stderr_hash,
        },
        "captured_at": time.time(),
    })
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    local_artifacts = []
    for name, content in (
        ("stdout.txt", completed.stdout),
        ("stderr.txt", completed.stderr),
    ):
        if content:
            local_artifacts.append(library.record_artifact(
                source_ref=value["source_ref"], name=name, content=content,
            ))
    mirrored = {**value, "local_artifacts": local_artifacts}
    library.record_source(mirrored)
    emit({
        **mirrored,
        "next_actions": [{
            "action": "create_output_fragment",
            "argv": [
                "factortester", "research", "evidence", "fragment", "add",
                value["source_ref"], "--profile-id", profile_id,
                "--selector-file", "<selector.json>",
                "--fragment-file", "<stdout-or-stderr-file>",
            ],
        }],
    }, as_json)


@source.command("capture-file")
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@profile_options
@click.option(
    "--provenance-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="权威下载链路或 Git blob 身份 JSON",
)
@click.option("--json", "as_json", is_flag=True)
def capture_file(
    path: Path,
    profile_id: str,
    release_profile: Path | None,
    provenance_file: Path,
    as_json: bool,
) -> None:
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    resolved = path.resolve()
    user_root = library.root.parent.parent.resolve()
    try:
        relative = resolved.relative_to(user_root)
    except ValueError as exc:
        raise click.ClickException(
            "file evidence must be inside the current user workspace"
        ) from exc
    content = _bounded_read(resolved)
    content_hash = hashlib.sha256(content).hexdigest()
    try:
        provenance = validate_file_provenance(
            read_object(provenance_file, "file provenance")
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    value = client_from_config().put_research_evidence_source({
        "source_kind": "file",
        "identity": {
            "relative_path": relative.as_posix(),
            "content_hash": content_hash,
        },
        "content_hash": content_hash,
        "audit": {"size": len(content), "provenance": provenance},
        "captured_at": resolved.stat().st_mtime,
    })
    artifact = library.record_artifact(
        source_ref=value["source_ref"],
        name=resolved.name,
        content=content,
    )
    mirrored = {**value, "local_artifacts": [artifact]}
    library.record_source(mirrored)
    emit(mirrored, as_json)


@source.command("capture-url")
@click.argument("url")
@profile_options
@click.option("--json", "as_json", is_flag=True)
def capture_url(
    url: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise click.ClickException("URL must use http or https")
    request = Request(url, headers={"User-Agent": "FactorTester-CLI/1"})
    try:
        with urlopen(request, timeout=30) as response:
            content = response.read(_MAX_SOURCE_BYTES + 1)
            final_url = response.geturl()
            content_type = str(response.headers.get("Content-Type") or "")
    except OSError as exc:
        raise click.ClickException(str(exc)) from exc
    if len(content) > _MAX_SOURCE_BYTES:
        raise click.ClickException("web source exceeds 8 MiB")
    content_hash = hashlib.sha256(content).hexdigest()
    value = client_from_config().put_research_evidence_source({
        "source_kind": "web",
        "identity": {
            "url": final_url,
            "content_hash": content_hash,
        },
        "content_hash": content_hash,
        "audit": {
            "requested_url": url,
            "content_type": content_type,
            "size": len(content),
        },
        "captured_at": time.time(),
    })
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    artifact = library.record_artifact(
        source_ref=value["source_ref"],
        name="snapshot.html",
        content=content,
    )
    mirrored = {**value, "local_artifacts": [artifact]}
    library.record_source(mirrored)
    emit(mirrored, as_json)


@click.group("fragment")
def fragment() -> None:
    """Create and inspect exact fragments of an immutable source."""


@fragment.command("add")
@click.argument("source_ref")
@click.option(
    "--selector-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--fragment-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--title-zh", required=True)
@click.option("--summary-zh", required=True)
@profile_options
@click.option("--json", "as_json", is_flag=True)
def add_fragment(
    source_ref: str,
    selector_file: Path,
    fragment_file: Path,
    title_zh: str,
    summary_zh: str,
    profile_id: str,
    release_profile: Path | None,
    as_json: bool,
) -> None:
    content = _bounded_read(fragment_file)
    preview = _preview(content)
    value = client_from_config().put_research_evidence_fragment(
        source_ref,
        {
            "selector": read_object(selector_file, "fragment selector"),
            "fragment_hash": hashlib.sha256(content).hexdigest(),
            "title_zh": title_zh,
            "summary_zh": summary_zh,
            "preview": preview,
        },
    )
    library = library_for_profile(
        release_profile=release_profile, profile_id=profile_id,
    )
    value["local_artifact"] = library.record_artifact(
        source_ref=source_ref,
        name=fragment_file.name,
        content=content,
    )
    library.record_fragment(value)
    emit({
        **value,
        "next_actions": [{
            "action": "create_evidence",
            "argv": [
                "factortester", "research", "evidence", "create",
                "--profile-id", profile_id,
                "--metadata-file", "<evidence.json>",
            ],
        }],
    }, as_json)


@fragment.command("list")
@click.argument("source_ref")
@click.option("--json", "as_json", is_flag=True)
def list_fragments(source_ref: str, as_json: bool) -> None:
    emit({
        "source_ref": source_ref,
        "fragments": client_from_config().list_research_evidence_fragments(
            source_ref
        ),
    }, as_json)


def _bounded_read(path: Path) -> bytes:
    content = path.read_bytes()
    if len(content) > _MAX_SOURCE_BYTES:
        raise click.ClickException(f"source exceeds {_MAX_SOURCE_BYTES} bytes")
    return content


def _preview(content: bytes) -> dict:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"text": content.decode("utf-8", errors="replace")[:1000]}
    return {"json": value} if isinstance(value, (dict, list)) else {
        "text": str(value)[:1000]
    }
