"""Shared, distributable Sparkle appcast validation."""

from __future__ import annotations

import ipaddress
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    delta_paths: tuple[Path, ...] = ()


def is_secure_release_url(url: str) -> bool:
    """Require HTTPS except for a loopback Beta readback endpoint."""
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


def validate_sparkle_appcast(
    path: Path,
    *,
    version: str,
    build: int,
    channel: str,
    download_url: str,
    expected_delta_from: int | None = None,
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
        f"{{{SPARKLE_NAMESPACE}}}shortVersionString",
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
        f"{{{SPARKLE_NAMESPACE}}}edSignature",
    )
    if not signature:
        raise ValueError("Sparkle appcast archive signature is missing")
    if expected_delta_from is not None:
        deltas = item.find(f"{{{SPARKLE_NAMESPACE}}}deltas")
        observed = {
            candidate.attrib.get(f"{{{SPARKLE_NAMESPACE}}}deltaFrom")
            for candidate in (
                deltas.findall("enclosure") if deltas is not None else []
            )
        }
        if str(expected_delta_from) not in observed:
            raise ValueError(
                "Sparkle appcast delta does not target the previous build",
            )
    return SparkleAppcast(
        path=path,
        version=version,
        build=build,
        channel=channel,
        download_url=download_url,
    )


__all__ = [
    "SPARKLE_NAMESPACE",
    "SparkleAppcast",
    "is_secure_release_url",
    "validate_sparkle_appcast",
]
