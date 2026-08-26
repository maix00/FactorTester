"""Prepare one signed Beta package for one Manager origin."""

from __future__ import annotations

import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from tools.cli.release.client_release_bundle import build_client_release_bundle
from tools.cli.release.sparkle_appcast import validate_sparkle_appcast
from tools.cli.release.update_channel import validate_update_manifest
from tools.cli.release.update_manifest_authoring import (
    create_update_manifest,
    write_update_manifest,
)


def build_target_beta_package(
    release_directory: str | Path,
    *,
    target_origin: str,
    output: str | Path,
    private_key: str | Path,
    public_key: str | Path,
) -> dict[str, object]:
    """Retarget and re-sign release metadata while reusing the same DMG."""
    root = Path(release_directory).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Beta release directory is unavailable")
    source_manifest_path = root / "beta.json"
    source_appcast_path = root / "appcast.xml"
    dmg = root / "FactorTester-Client.dmg"
    if (
        not source_manifest_path.is_file()
        or not source_appcast_path.is_file()
        or not dmg.is_file()
    ):
        raise ValueError("Beta release directory is missing DMG or metadata")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(source_manifest, dict):
        raise ValueError("Beta release manifest must be an object")
    public_key = Path(public_key).expanduser().resolve()
    private_key = Path(private_key).expanduser().resolve()
    source = validate_update_manifest(
        source_manifest, public_key=public_key, expected_channel="beta",
    )
    target = _origin(target_origin)
    source_url = urlsplit(source.dmg_url)
    target_url = urlunsplit((
        target.scheme,
        target.netloc,
        source_url.path,
        "",
        "",
    ))
    manifest = create_update_manifest(
        version=source.version,
        build=source.build,
        channel="beta",
        dmg=dmg,
        dmg_url=target_url,
        minimum_client=source.minimum_client,
        mandatory=source.mandatory,
        published_at=source.published_at,
        private_key=private_key,
        public_key=public_key,
    )
    with tempfile.TemporaryDirectory(prefix="factortester-beta-target-") as raw:
        staging = Path(raw)
        manifest_path = staging / "beta.json"
        appcast_path = staging / "beta.xml"
        write_update_manifest(manifest_path, manifest)
        _retarget_appcast(
            source_appcast_path,
            appcast_path,
            source_origin=_origin(source.dmg_url),
            target_origin=target,
        )
        validate_sparkle_appcast(
            appcast_path,
            version=source.version,
            build=source.build,
            channel="beta",
            download_url=target_url,
        )
        result = build_client_release_bundle(
            dmg=dmg,
            appcast=appcast_path,
            manifest=manifest_path,
            output=Path(output).expanduser().resolve(),
            deltas=sorted((root / "deltas").glob("*.delta"))
            if (root / "deltas").is_dir() else (),
        )
    return result


def _retarget_appcast(
    source: Path,
    target: Path,
    *,
    source_origin,
    target_origin,
) -> None:
    tree = ET.parse(source)
    changed = 0
    for enclosure in tree.getroot().iter("enclosure"):
        value = str(enclosure.attrib.get("url") or "")
        parsed = urlsplit(value)
        if _origin_or_none(value) != source_origin:
            continue
        if not parsed.path.startswith("/api/client/releases/assets/beta/"):
            raise ValueError("Beta appcast contains an unexpected asset path")
        enclosure.set("url", urlunsplit((
            target_origin.scheme,
            target_origin.netloc,
            parsed.path,
            "",
            "",
        )))
        changed += 1
    if changed == 0:
        raise ValueError("Beta appcast has no source-origin asset")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="utf-8", xml_declaration=True)


def _origin(value: str):
    parsed = urlsplit(str(value or "").strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Beta Manager origin is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "Beta Manager origin must not contain credentials or query data",
        )
    return parsed


def _origin_or_none(value: str):
    try:
        parsed = _origin(value)
    except ValueError:
        return None
    return parsed


__all__ = ["build_target_beta_package"]
