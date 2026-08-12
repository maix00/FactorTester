"""Read signed update manifests from disk without database access."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
import re
import stat
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from tools.cli.release.update_channel import (
    MAX_UPDATE_MANIFEST_BYTES,
    validate_update_manifest,
)
from scripts.release.sparkle import is_secure_release_url

MAX_SPARKLE_APPCAST_BYTES = 1024 * 1024
MAX_SPARKLE_ITEMS = 10
SPARKLE_NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def load_client_release_channel(
    root: Path,
    channel: str,
    *,
    public_key: Path,
) -> tuple[bytes, str]:
    if channel not in {"stable", "beta"}:
        raise ValueError("client release channel is invalid")
    path = root.resolve() / f"{channel}.json"
    raw = path.read_bytes()
    if len(raw) > MAX_UPDATE_MANIFEST_BYTES:
        raise ValueError("update manifest exceeds size limit")
    value: Any = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("update manifest must be a JSON object")
    validated = validate_update_manifest(
        value,
        public_key=public_key,
        expected_channel=channel,
    )
    if channel == "beta":
        parsed_dmg = urlparse(validated.dmg_url)
        expected_path = (
            "/api/client/releases/assets/beta/"
            f"{validated.dmg_sha256}.dmg"
        )
        if (
            parsed_dmg.path != expected_path
            or parsed_dmg.query
            or parsed_dmg.fragment
        ):
            raise ValueError(
                "Beta DMG URL is not the SHA-addressed server asset route"
            )
    return raw, sha256(raw).hexdigest()


def load_beta_sparkle_appcast(
    root: Path,
    *,
    public_key: Path,
) -> tuple[bytes, str]:
    """Load the appcast only when it agrees with the verified Beta pointer."""
    legacy_raw, _ = load_client_release_channel(
        root,
        "beta",
        public_key=public_key,
    )
    legacy: Any = json.loads(legacy_raw)
    directory = os.open(
        root.resolve(),
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        descriptor = os.open(
            "beta.xml",
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size > MAX_SPARKLE_APPCAST_BYTES
            ):
                raise ValueError("Sparkle Beta appcast is not a bounded file")
            raw = stream.read(MAX_SPARKLE_APPCAST_BYTES + 1)
    finally:
        os.close(directory)
    if len(raw) > MAX_SPARKLE_APPCAST_BYTES:
        raise ValueError("Sparkle Beta appcast exceeds size limit")
    try:
        document = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Sparkle Beta appcast is invalid XML") from exc
    items = document.findall("./channel/item")
    if not items or len(items) > MAX_SPARKLE_ITEMS:
        raise ValueError("Sparkle Beta appcast item count is invalid")
    for item in items:
        if item.findtext(f"{{{SPARKLE_NAMESPACE}}}channel") != "beta":
            raise ValueError("Sparkle appcast item is not Beta")
        enclosure = item.find("enclosure")
        if enclosure is None:
            raise ValueError("Sparkle Beta appcast enclosure is missing")
        url = enclosure.attrib.get("url", "")
        parsed = urlparse(url)
        signature = enclosure.attrib.get(
            f"{{{SPARKLE_NAMESPACE}}}edSignature",
            "",
        )
        if (
            not _is_beta_asset_url(parsed, suffix="dmg")
            or not signature
        ):
            raise ValueError("Sparkle Beta appcast item is invalid")
        deltas = item.find(f"{{{SPARKLE_NAMESPACE}}}deltas")
        if deltas is None:
            continue
        for delta in deltas.findall("enclosure"):
            delta_url = urlparse(delta.attrib.get("url", ""))
            if (
                not _is_beta_asset_url(delta_url, suffix="delta")
                or not delta.attrib.get(
                    f"{{{SPARKLE_NAMESPACE}}}deltaFrom"
                )
                or not delta.attrib.get(
                    f"{{{SPARKLE_NAMESPACE}}}edSignature"
                )
            ):
                raise ValueError("Sparkle Beta delta item is invalid")
    item = items[0]
    enclosure = item.find("enclosure")
    assert enclosure is not None
    url = enclosure.attrib.get("url", "")
    parsed = urlparse(url)
    signature = enclosure.attrib.get(
        f"{{{SPARKLE_NAMESPACE}}}edSignature",
        "",
    )
    expected_url = str(legacy.get("dmg_url") or "")
    expected_digest = str(legacy.get("sha256") or "")
    if (
        not is_secure_release_url(url)
        or parsed.query
        or parsed.fragment
        or not signature
    ):
        raise ValueError("Sparkle Beta appcast enclosure is invalid")
    if url == expected_url and parsed.path == (
        "/api/client/releases/assets/beta/"
        f"{expected_digest}.dmg"
    ):
        return raw, sha256(raw).hexdigest()

    # Delta-only Beta keeps the old signed legacy manifest as the trust root,
    # while the appcast advances to a new build whose full DMG is deliberately
    # not public.  Accept that transition only when the latest item contains a
    # signed delta explicitly targeting the legacy build; arbitrary appcast
    # pointer swaps must remain rejected.
    try:
        legacy_build = int(legacy.get("build"))
        latest_build = int(
            item.findtext(f"{{{SPARKLE_NAMESPACE}}}version") or ""
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Sparkle Beta appcast build is invalid") from exc
    deltas = item.find(f"{{{SPARKLE_NAMESPACE}}}deltas")
    matching_delta = None if deltas is None else next(
        (
            delta for delta in deltas.findall("enclosure")
            if delta.attrib.get(f"{{{SPARKLE_NAMESPACE}}}deltaFrom")
            == str(legacy_build)
        ),
        None,
    )
    if (
        latest_build <= legacy_build
        or matching_delta is None
        or not matching_delta.attrib.get(
            f"{{{SPARKLE_NAMESPACE}}}edSignature"
        )
    ):
        raise ValueError(
            "Sparkle Beta appcast does not match the verified channel"
        )
    return raw, sha256(raw).hexdigest()


def _is_beta_asset_url(parsed, *, suffix: str) -> bool:
    if not is_secure_release_url(parsed.geturl()):
        return False
    if parsed.query or parsed.fragment:
        return False
    return bool(
        re.fullmatch(
            rf"/api/client/releases/assets/beta/[0-9a-f]{{64}}\.{suffix}",
            parsed.path,
        )
    )
