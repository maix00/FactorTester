"""Generate and validate a Sparkle appcast without exposing signing secrets."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


SPARKLE_NAMESPACE = (
    "http://www.andymatuschak.org/xml-namespaces/sparkle"
)


@dataclass(frozen=True)
class SparkleAppcast:
    path: Path
    version: str
    build: int
    channel: str
    download_url: str


def is_secure_release_url(url: str) -> bool:
    """Require HTTPS except for the existing local Beta server."""
    split = urlsplit(url)
    if not split.netloc:
        return False
    if split.scheme == "https":
        return True
    if split.scheme != "http":
        return False
    hostname = split.hostname or ""
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def generate_sparkle_appcast(
    *,
    archive: Path,
    output: Path,
    tool: Path,
    download_url: str,
    version: str,
    build: int,
    channel: str,
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

    with tempfile.TemporaryDirectory(
        prefix="factortester-sparkle-appcast-"
    ) as raw:
        root = Path(raw)
        staged = root / archive.name
        shutil.copy2(archive, staged)
        command = [
            str(tool),
            "--download-url-prefix",
            download_url.rsplit("/", 1)[0] + "/",
        ]
        if channel == "beta":
            command.extend(["--channel", "beta"])
        command.append(str(root))
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        generated = root / "appcast.xml"
        if not generated.is_file():
            raise ValueError("Sparkle did not generate appcast.xml")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.staging")
        shutil.copy2(generated, temporary)
        temporary.replace(output)

    return validate_sparkle_appcast(
        output,
        version=version,
        build=build,
        channel=channel,
        download_url=download_url,
    )


def validate_sparkle_appcast(
    path: Path,
    *,
    version: str,
    build: int,
    channel: str,
    download_url: str,
) -> SparkleAppcast:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("Sparkle appcast is invalid XML") from exc
    item = root.find("./channel/item")
    if item is None:
        raise ValueError("Sparkle appcast has no release item")
    observed_build = item.findtext(f"{{{SPARKLE_NAMESPACE}}}version")
    if observed_build != str(build):
        raise ValueError("Sparkle appcast build does not match release")
    observed_version = item.findtext(
        f"{{{SPARKLE_NAMESPACE}}}shortVersionString"
    )
    if observed_version != version:
        raise ValueError("Sparkle appcast version does not match release")
    observed_channel = item.findtext(f"{{{SPARKLE_NAMESPACE}}}channel")
    if channel == "beta" and observed_channel != "beta":
        raise ValueError("Sparkle appcast Beta channel is missing")
    if channel == "stable" and observed_channel not in (None, "", "stable"):
        raise ValueError("Sparkle appcast Main channel is invalid")
    enclosure = item.find("enclosure")
    if enclosure is None:
        raise ValueError("Sparkle appcast enclosure is missing")
    if enclosure.attrib.get("url") != download_url:
        raise ValueError("Sparkle appcast download URL does not match release")
    signature = enclosure.attrib.get(
        f"{{{SPARKLE_NAMESPACE}}}edSignature"
    )
    if not signature:
        raise ValueError("Sparkle appcast archive signature is missing")
    return SparkleAppcast(
        path=path,
        version=version,
        build=build,
        channel=channel,
        download_url=download_url,
    )
