"""Generate and validate a Sparkle appcast without exposing signing secrets."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from tools.cli.release.sparkle_appcast import (
    SPARKLE_NAMESPACE,
    SparkleAppcast,
    is_secure_release_url,
    validate_sparkle_appcast,
)

SPARKLE_EXTRACTION_CACHE = (
    Path.home() / "Library" / "Caches" / "Sparkle_generate_appcast"
)


def generate_sparkle_appcast(
    *,
    archive: Path,
    output: Path,
    tool: Path,
    download_url: str,
    version: str,
    build: int,
    channel: str,
    previous_archive: Path | None = None,
    previous_archive_url: str | None = None,
    previous_appcast: Path | None = None,
    delta_output: Path | None = None,
    delta_only: bool = False,
    latest_only: bool = False,
) -> SparkleAppcast:
    """Run Sparkle's Keychain-backed generator in an isolated directory."""
    if channel not in {"stable", "beta"}:
        raise ValueError("Sparkle release channel is invalid")
    if not archive.is_file():
        raise ValueError("Sparkle update archive does not exist")
    if not tool.is_file() or not tool.stat().st_mode & 0o111:
        raise ValueError("Sparkle generate_appcast tool is not executable")
    if not is_secure_release_url(download_url):
        raise ValueError(
            "Sparkle download URL must use HTTPS or loopback HTTP"
        )

    target_name = Path(urlsplit(download_url).path).name
    if not target_name or target_name in {".", ".."}:
        raise ValueError("Sparkle download URL has no archive name")
    if previous_archive is not None and not previous_archive.is_file():
        raise ValueError("Sparkle previous update archive does not exist")
    if previous_appcast is not None and not previous_appcast.is_file():
        raise ValueError("Sparkle previous appcast does not exist")
    if previous_archive_url is not None:
        if not is_secure_release_url(previous_archive_url):
            raise ValueError("Sparkle previous archive URL is not secure")
        previous_name = Path(urlsplit(previous_archive_url).path).name
        if not previous_name or previous_name in {".", ".."}:
            raise ValueError("Sparkle previous archive URL has no archive name")
    elif previous_archive is not None:
        previous_name = previous_archive.name
    else:
        previous_name = ""
    expected_delta_from = _latest_build(previous_appcast)
    if previous_appcast is not None and expected_delta_from is None:
        raise ValueError("previous Sparkle appcast has no valid build")

    with tempfile.TemporaryDirectory(
        prefix="factortester-sparkle-appcast-"
    ) as raw:
        root = Path(raw)
        # generate_appcast constructs the enclosure URL from the prefix and the
        # staged filename. Preserve the content-addressed public filename.
        staged = root / target_name
        shutil.copy2(archive, staged)
        if previous_archive is not None:
            shutil.copy2(previous_archive, root / previous_name)
        if previous_appcast is not None:
            _normalize_appcast_namespace(
                previous_appcast,
                root / "appcast.xml",
            )
        command = [
            str(tool),
            "--download-url-prefix",
            download_url.rsplit("/", 1)[0] + "/",
        ]
        if channel == "beta":
            command.extend(["--channel", "beta"])
        command.append(str(root))
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            _prune_extraction_cache(archive, previous_archive)
        generated = root / "appcast.xml"
        if not generated.is_file():
            raise ValueError("Sparkle did not generate appcast.xml")
        delta_paths: list[Path] = []
        if delta_output is not None:
            delta_output.mkdir(parents=True, exist_ok=True)
            replacements: dict[str, str] = {}
            for delta in sorted(root.glob("*.delta")):
                digest = sha256(delta.read_bytes()).hexdigest()
                destination = delta_output / f"{digest}.delta"
                shutil.copy2(delta, destination)
                delta_paths.append(destination)
                replacements[delta.name] = destination.name
            if replacements:
                _rewrite_delta_urls(
                    generated,
                    replacements,
                    download_url.rsplit("/", 1)[0] + "/",
                )
        if previous_archive is not None and not delta_paths:
            raise ValueError("Sparkle did not generate a delta update")
        if latest_only or delta_only:
            if previous_archive is None:
                if delta_only:
                    raise ValueError("Delta-only appcast requires a previous archive")
            if delta_only and previous_appcast is None:
                raise ValueError("Delta-only appcast requires a previous appcast")
            _retain_latest_item(generated)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.staging")
        shutil.copy2(generated, temporary)
        temporary.replace(output)

    validated = validate_sparkle_appcast(
        output,
        version=version,
        build=build,
        channel=channel,
        download_url=download_url,
        expected_delta_from=expected_delta_from,
    )
    return SparkleAppcast(
        path=validated.path,
        version=validated.version,
        build=validated.build,
        channel=validated.channel,
        download_url=validated.download_url,
        delta_paths=tuple(delta_paths),
    )


def _prune_extraction_cache(*archives: Path | None) -> None:
    """Remove only cache entries keyed by archives used in this invocation."""
    root = SPARKLE_EXTRACTION_CACHE
    if not root.is_dir():
        return
    for archive in archives:
        if archive is None or not archive.is_file():
            continue
        candidate = root / sha256(archive.read_bytes()).hexdigest()
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            shutil.rmtree(candidate)


def _normalize_appcast_namespace(source: Path, destination: Path) -> None:
    """Write a readable Sparkle prefix for legacy appcasts.

    ElementTree accepts any prefix bound to the Sparkle namespace, but older
    releases of this publisher wrote ``ns0``.  Sparkle's native parser is
    stricter when it updates an existing appcast and expects the conventional
    ``sparkle`` prefix to remain declared.
    """
    ET.register_namespace("sparkle", SPARKLE_NAMESPACE)
    tree = ET.parse(source)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def _retain_latest_item(appcast: Path) -> None:
    ET.register_namespace("sparkle", SPARKLE_NAMESPACE)
    tree = ET.parse(appcast)
    root = tree.getroot()
    channel = root.find("./channel")
    if channel is None:
        raise ValueError("Sparkle appcast channel is missing")
    items = channel.findall("item")
    if not items:
        raise ValueError("Sparkle appcast has no release item")
    for item in items[1:]:
        channel.remove(item)
    tree.write(appcast, encoding="utf-8", xml_declaration=True)

def _latest_build(appcast: Path | None) -> int | None:
    if appcast is None or not appcast.is_file():
        return None
    try:
        root = ET.parse(appcast).getroot()
    except (OSError, ET.ParseError):
        return None
    item = root.find("./channel/item")
    if item is None:
        return None
    value = item.findtext(f"{{{SPARKLE_NAMESPACE}}}version")
    try:
        return int(value or "")
    except ValueError:
        return None


def _rewrite_delta_urls(
    appcast: Path,
    replacements: dict[str, str],
    download_url_prefix: str,
) -> None:
    ET.register_namespace("sparkle", SPARKLE_NAMESPACE)
    tree = ET.parse(appcast)
    root = tree.getroot()
    delta_tag = f"{{{SPARKLE_NAMESPACE}}}deltaFrom"
    for enclosure in root.iter("enclosure"):
        if delta_tag not in enclosure.attrib:
            continue
        old_url = enclosure.attrib.get("url", "")
        old_name = Path(urlsplit(old_url).path).name
        new_name = replacements.get(old_name)
        if new_name is not None:
            enclosure.set("url", download_url_prefix + new_name)
    tree.write(appcast, encoding="utf-8", xml_declaration=True)
