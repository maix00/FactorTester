"""Atomic version-directory install, status, and pointer rollback."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from .artifacts import install_asset
from .contracts import validate_release_manifest
from .health import release_is_healthy
from .locations import validate_client_root
from .materialize import materialize_release, install_stable_launchers
from .storage import json_hash, read_json, utc_now, write_json


class ClientReleaseStore:
    def __init__(self, root: Path) -> None:
        self.root = validate_client_root(root)
        self.releases = self.root / "releases"
        self.pointer = self.root / "current.json"

    def plan(
        self,
        manifest: dict[str, Any],
        *,
        public_key: Path,
    ) -> dict[str, Any]:
        release = validate_release_manifest(manifest, public_key=public_key)
        current = self._current()
        return {
            "schema_version": 1,
            "current_version": current.get("version"),
            "target_version": release.version,
            "manifest_hash": release.manifest_hash,
            "install_root": str(self.root),
            "mutations": [
                f"create releases/{release.version}",
                f"write releases/{release.version}/receipt.json",
                "replace current.json",
            ],
        }

    def install(
        self,
        manifest: dict[str, Any],
        *,
        public_key: Path,
        allow_file_urls: bool = False,
    ) -> dict[str, Any]:
        release = validate_release_manifest(manifest, public_key=public_key)
        current = self._current()
        target = self.releases / release.version
        existing = self._receipt(target)
        if existing is not None:
            if existing.get("manifest_hash") != release.manifest_hash:
                raise ValueError("installed version conflicts with manifest")
            if current.get("version") != release.version:
                self._write_pointer(release.version, release.manifest_hash)
            if (existing.get("materialized") or {}).get("python"):
                install_stable_launchers(self.root)
            return existing

        self.releases.mkdir(parents=True, exist_ok=True)
        staging = self.releases / f".staging-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            asset_receipts = [
                install_asset(
                    asset,
                    staging,
                    allow_file_urls=allow_file_urls,
                )
                for asset in release.assets
            ]
            materialized = materialize_release(staging, asset_receipts)
            receipt = self._build_receipt(
                version=release.version,
                release_id=release.release_id,
                source_revision=release.source_revision,
                manifest_hash=release.manifest_hash,
                previous_version=str(current.get("version") or ""),
                assets=asset_receipts,
                materialized=materialized,
            )
            write_json(staging / "receipt.json", receipt)
            os.replace(staging, target)
            self._write_pointer(release.version, release.manifest_hash)
            if materialized.get("python"):
                install_stable_launchers(self.root)
            return receipt
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def status(self) -> dict[str, Any]:
        current = self._current()
        versions = []
        if self.releases.is_dir():
            versions = sorted(
                path.name
                for path in self.releases.iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and (path / "receipt.json").is_file()
            )
        receipt = (
            self._receipt(self.releases / str(current.get("version")))
            if current.get("version")
            else None
        )
        version_root = self.releases / str(current.get("version") or "")
        return {
            "schema_version": 1,
            "install_root": str(self.root),
            "current_version": current.get("version"),
            "manifest_hash": current.get("manifest_hash"),
            "installed_versions": versions,
            "healthy": release_is_healthy(version_root, receipt),
            "receipt": receipt,
        }

    def rollback(self, to_version: str = "") -> dict[str, Any]:
        current = self._current()
        current_version = str(current.get("version") or "")
        if not current_version:
            raise ValueError("no installed client release to rollback")
        current_receipt = self._receipt(self.releases / current_version)
        target_version = to_version or str(
            (current_receipt or {}).get("previous_version") or ""
        )
        if not target_version or target_version == current_version:
            raise ValueError("no valid previous client release")
        target_receipt = self._receipt(self.releases / target_version)
        if target_receipt is None:
            raise ValueError(f"rollback target is not installed: {target_version}")
        self._write_pointer(
            target_version,
            str(target_receipt["manifest_hash"]),
        )
        return self.status()

    def _build_receipt(
        self,
        *,
        version: str,
        release_id: str,
        source_revision: str,
        manifest_hash: str,
        previous_version: str,
        assets: list[dict[str, Any]],
        materialized: dict[str, Any],
    ) -> dict[str, Any]:
        body = {
            "schema_version": 1,
            "release_id": release_id,
            "version": version,
            "source_revision": source_revision,
            "manifest_hash": manifest_hash,
            "previous_version": previous_version or None,
            "installed_at": utc_now(),
            "assets": assets,
            "materialized": materialized,
        }
        return {**body, "receipt_hash": json_hash(body)}

    def _current(self) -> dict[str, Any]:
        return read_json(self.pointer) or {}

    def _receipt(self, version_root: Path) -> dict[str, Any] | None:
        receipt = read_json(version_root / "receipt.json")
        if receipt is None:
            return None
        declared = str(receipt.get("receipt_hash") or "")
        body = dict(receipt)
        body.pop("receipt_hash", None)
        if declared != json_hash(body):
            raise ValueError(f"client release receipt is corrupt: {version_root}")
        return receipt

    def _write_pointer(self, version: str, manifest_hash: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(
            self.pointer,
            {
                "schema_version": 1,
                "version": version,
                "manifest_hash": manifest_hash,
                "updated_at": utc_now(),
            },
        )
