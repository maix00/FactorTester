"""Validate and atomically activate an uploaded Beta client package."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from server.manager.objects.models import TransferObjectKind
from tools.cli.release.client_release_bundle import extract_client_release_bundle
from tools.cli.release.update_channel import validate_update_manifest
from server.services.client_release_channels import (
    load_beta_sparkle_appcast,
    load_client_release_channel,
)


_OBJECT_ID = re.compile(
    r"^beta:(?P<version>[0-9A-Za-z.+-]{1,128}):(?P<build>[1-9][0-9]*):"
    r"(?P<package>[0-9a-f]{64})$"
)


class ClientReleaseDestinationAdapter:
    """Own the server-side release root; 7997 only delivers verified bytes."""

    def __init__(
        self,
        *,
        release_root: str | Path,
        public_key: str | Path,
        expected_origin: str = "",
    ) -> None:
        self.release_root = Path(release_root).expanduser().resolve()
        self.public_key = Path(public_key).expanduser().resolve()
        self.expected_origin = str(expected_origin or "").strip().rstrip("/")

    def __call__(self, context, staged_path: Path) -> Path:
        if str(context.transfer.object_kind) != TransferObjectKind.CLIENT_RELEASE.value:
            return staged_path
        object_id = str(context.transfer.object_id or "").strip()
        match = _OBJECT_ID.fullmatch(object_id)
        if match is None:
            raise ValueError("client release transfer identity is invalid")
        if not self.public_key.is_file() or self.public_key.is_symlink():
            raise FileNotFoundError("client release trust root is unavailable")
        self.release_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="client-release-", dir=str(self.release_root.parent),
        ) as raw:
            extracted = Path(raw) / "package"
            metadata = extract_client_release_bundle(staged_path, extracted)
            if (
                str(metadata["version"]) != match.group("version")
                or int(metadata["build"]) != int(match.group("build"))
                or str(metadata["package_sha256"]) != match.group("package")
            ):
                raise ValueError("client release transfer metadata does not match package")
            self._activate(extracted, metadata)
        staged_path.unlink(missing_ok=True)
        return self.release_root / "beta.json"

    def _activate(self, package: Path, metadata: dict[str, object]) -> None:
        import json
        from scripts.release.publish import publish_beta_directory

        manifest_path = package / "beta.json"
        appcast_path = package / "beta.xml"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("client release manifest must be an object")
        validated = validate_update_manifest(
            manifest,
            public_key=self.public_key,
            expected_channel="beta",
        )
        if (
            validated.version != str(metadata["version"])
            or validated.build != int(metadata["build"])
            or validated.dmg_sha256 != str(metadata["dmg_sha256"])
        ):
            raise ValueError("client release manifest identity does not match package")
        if self.expected_origin:
            parsed = urlsplit(validated.dmg_url)
            actual_origin = f"{parsed.scheme}://{parsed.netloc}"
            if actual_origin.rstrip("/") != self.expected_origin:
                raise ValueError("client release manifest origin does not match this Manager")
        dmg = package / "assets" / "beta" / f"{validated.dmg_sha256}.dmg"
        deltas = tuple(sorted((package / "assets" / "beta").glob("*.delta")))
        for delta in deltas:
            if not re.fullmatch(r"[0-9a-f]{64}\.delta", delta.name):
                raise ValueError("client release delta filename is invalid")
        publication = publish_beta_directory(
            dmg=dmg,
            appcast=appcast_path,
            legacy_manifest=manifest,
            release_root=self.release_root,
            deltas=deltas,
            publish_full=True,
            retain_base=False,
        )
        try:
            # Re-read through the same public read validators used by clients.
            # A pointer is never considered active until both files and the
            # signed trust root pass these checks.
            load_client_release_channel(
                self.release_root, "beta", public_key=self.public_key,
            )
            load_beta_sparkle_appcast(
                self.release_root, public_key=self.public_key,
            )
            publication.finalize()
        except BaseException:
            publication.rollback()
            raise


__all__ = ["ClientReleaseDestinationAdapter"]
