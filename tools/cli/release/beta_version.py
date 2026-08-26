"""Resolve the next Beta version from published channel metadata.

The source checkout deliberately carries a development version.  Release
numbers belong to the Beta channel and are therefore derived from the channel
manifests that the publisher is about to update.
"""

from __future__ import annotations

import json
import plistlib
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_BETA_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)-beta\."
    r"(?P<ordinal>[1-9][0-9]*)$"
)
_BASE_VERSION = re.compile(
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
)
_MAX_MANIFEST_BYTES = 64 * 1024


class BetaSourceUnavailable(OSError):
    """A source that could not establish a network connection."""


class BetaSourceTrustError(RuntimeError):
    """A reachable source whose TLS identity could not be verified."""


@dataclass(frozen=True, slots=True)
class ExistingBetaRelease:
    """One valid Beta release discovered from a server or release root."""

    version: str
    build: int
    source: str

    @property
    def version_key(self) -> tuple[int, int, int, int]:
        parsed = parse_beta_version(self.version)
        return parsed


def parse_beta_version(value: str) -> tuple[int, int, int, int]:
    """Parse the supported ``X.Y.Z-beta.N`` release form."""
    match = _BETA_VERSION.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError(
            "Beta version must use the form X.Y.Z-beta.N with a positive N"
        )
    return tuple(int(match.group(name)) for name in (
        "major", "minor", "patch", "ordinal",
    ))


def base_version_from_project(project_file: Path) -> str:
    """Read the numeric base from the development version in project.yml."""
    text = project_file.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*MARKETING_VERSION:\s*[\"']?([^\"'\s]+)",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("MARKETING_VERSION is missing from the client project")
    base = _BASE_VERSION.match(match.group(1))
    if base is None:
        raise ValueError("MARKETING_VERSION has no valid X.Y.Z base")
    return ".".join(base.group(name) for name in ("major", "minor", "patch"))


def next_beta_version(
    releases: Iterable[ExistingBetaRelease],
    *,
    project_base_version: str,
) -> str:
    """Return the next channel version after all discovered releases."""
    parsed_base = _parse_base_version(project_base_version)
    current = max((release.version_key for release in releases), default=None)
    if current is None:
        major, minor, patch = parsed_base
        return f"{major}.{minor}.{patch}-beta.1"
    major, minor, patch, ordinal = current
    return f"{major}.{minor}.{patch}-beta.{ordinal + 1}"


def resolve_beta_identity(
    *,
    version: str | None,
    build: int | str | None,
    sources: Iterable[str | Path],
    project_file: Path,
    ca_file: Path | None = None,
) -> tuple[str, int, tuple[ExistingBetaRelease, ...]]:
    """Resolve or validate a Beta version and monotonically increasing build.

    ``version`` and ``build`` may be omitted or set to ``auto``.  Every source
    is read before a release is built; an unavailable source fails closed so a
    stale server cannot accidentally receive a duplicate release.
    """
    discovered_items: list[ExistingBetaRelease] = []
    for source in sources:
        try:
            release = (
                read_installed_beta_release(source)
                if isinstance(source, Path) and source.name == "Info.plist"
                else read_beta_release(source, ca_file=ca_file)
            )
        except BetaSourceUnavailable:
            # A server that is currently offline cannot receive this release
            # either. It is intentionally omitted from the high-water mark;
            # a later, explicit administrator invocation may publish to it.
            continue
        if release is not None:
            discovered_items.append(release)
    discovered = tuple(discovered_items)
    highest_version = max(
        (release.version_key for release in discovered),
        default=None,
    )
    requested_version = str(version or "").strip().lower()
    if not requested_version or requested_version == "auto":
        resolved_version = next_beta_version(
            discovered,
            project_base_version=base_version_from_project(project_file),
        )
    else:
        resolved_version = str(version).strip()
        resolved_key = parse_beta_version(resolved_version)
        if highest_version is not None and resolved_key <= highest_version:
            raise ValueError(
                f"Beta version {resolved_version} is not newer than the "
                f"published version {format_beta_key(highest_version)}"
            )

    requested_build = str(build or "").strip().lower()
    if not requested_build or requested_build == "auto":
        project_build = project_build_number(project_file)
        highest_build = max((release.build for release in discovered), default=0)
        resolved_build = max(project_build, highest_build) + 1
    else:
        try:
            resolved_build = int(requested_build)
        except ValueError as exc:
            raise ValueError("Beta build must be a positive integer or auto") from exc
        if resolved_build < 1:
            raise ValueError("Beta build must be a positive integer")
        highest_build = max((release.build for release in discovered), default=0)
        if resolved_build <= highest_build:
            raise ValueError(
                f"Beta build {resolved_build} is not newer than the "
                f"published build {highest_build}"
            )
    return resolved_version, resolved_build, discovered


def read_beta_release(
    source: str | Path,
    *,
    ca_file: Path | None = None,
) -> ExistingBetaRelease | None:
    """Read one Beta manifest; return None only when the source has no release."""
    label, raw = _read_source(source, ca_file=ca_file)
    if raw is None:
        return None
    try:
        manifest: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Beta manifest from {label} is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"Beta manifest from {label} must be an object")
    version = str(manifest.get("version") or "").strip()
    parse_beta_version(version)
    build = manifest.get("build")
    if isinstance(build, bool) or not isinstance(build, int) or build < 1:
        raise ValueError(f"Beta manifest from {label} has an invalid build")
    return ExistingBetaRelease(version=version, build=build, source=label)


def read_installed_beta_release(
    info_plist: Path,
) -> ExistingBetaRelease | None:
    """Use an installed Beta app as a local monotonic version floor."""
    if not info_plist.is_file():
        return None
    try:
        value = plistlib.loads(info_plist.read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ValueError(f"installed FTClient Info.plist is invalid: {info_plist}") from exc
    version = str(value.get("CFBundleShortVersionString") or "").strip()
    if not version:
        return None
    if "-beta." not in version:
        return None
    parse_beta_version(version)
    raw_build = value.get("CFBundleVersion")
    try:
        build = int(str(raw_build or "0"))
    except ValueError as exc:
        raise ValueError(f"installed FTClient build is invalid: {info_plist}") from exc
    if build < 1:
        raise ValueError(f"installed FTClient build is invalid: {info_plist}")
    return ExistingBetaRelease(
        version=version,
        build=build,
        source=str(info_plist),
    )


def project_build_number(project_file: Path) -> int:
    """Read the current development build as a floor for the next release."""
    text = project_file.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*CURRENT_PROJECT_VERSION:\s*[\"']?([0-9]+)",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        return 0
    return int(match.group(1))


def format_beta_key(value: tuple[int, int, int, int]) -> str:
    """Format a parsed Beta version for an error message."""
    major, minor, patch, ordinal = value
    return f"{major}.{minor}.{patch}-beta.{ordinal}"


def _read_source(
    source: str | Path,
    *,
    ca_file: Path | None = None,
) -> tuple[str, bytes | None]:
    if isinstance(source, Path):
        path = source / "beta.json" if source.is_dir() else source
        if not path.exists():
            return str(path), None
        return str(path), path.read_bytes()
    value = str(source or "").strip()
    if not value:
        return "<empty source>", None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Beta source is not a valid HTTP(S) URL: {value}")
    url = value if parsed.path.endswith(".json") else (
        value.rstrip("/") + "/api/client/releases/beta.json"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FactorTester-Manager/beta-version-v1",
        },
    )
    context = (
        ssl.create_default_context(cafile=str(ca_file))
        if ca_file is not None
        else None
    )
    try:
        with urlopen(request, timeout=15, context=context) as response:
            raw = response.read(_MAX_MANIFEST_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return url, None
        raise ValueError(
            f"cannot read Beta manifest {url}: HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        if _is_certificate_error(exc):
            raise BetaSourceTrustError(
                f"cannot verify Beta manifest TLS identity for {url}"
            ) from exc
        raise BetaSourceUnavailable(
            f"cannot connect to Beta manifest {url}: {exc}"
        ) from exc
    except OSError as exc:
        if _is_certificate_error(exc):
            raise BetaSourceTrustError(
                f"cannot verify Beta manifest TLS identity for {url}"
            ) from exc
        raise BetaSourceUnavailable(
            f"cannot connect to Beta manifest {url}: {exc}"
        ) from exc
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise ValueError(f"Beta manifest from {url} is too large")
    return url, raw


def _is_certificate_error(error: BaseException) -> bool:
    pending: BaseException | None = error
    seen: set[int] = set()
    while pending is not None and id(pending) not in seen:
        seen.add(id(pending))
        if isinstance(pending, ssl.SSLCertVerificationError):
            return True
        reason = getattr(pending, "reason", None)
        if isinstance(reason, BaseException):
            pending = reason
            continue
        pending = pending.__cause__ or pending.__context__
    return False


def _parse_base_version(value: str) -> tuple[int, int, int]:
    match = _BASE_VERSION.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError("project base version must use the form X.Y.Z")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))
