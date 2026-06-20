"""One-time migration of LocalCNFutures files into provider-scoped storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Iterable

from scripts.data_dir import DATA_DIR, get_feat_root
from tools.data.artifacts.storage import artifact_root


PROVIDER = "LocalCNFutures"
SOURCE_ASSETS = (
    "data_mink",
    "data_mink_product",
    "main_mink",
    "main_dayk",
    "fees",
    "fees-effective",
    "data_dayk.parquet",
    "data_mink_2024.7z",
    "data_mink_2025.7z",
    "data_mink_2026_1.7z",
    "main_series_adjusted.parquet",
    "minute_index.parquet",
    "sectors.csv",
    "wind_mapping.parquet",
    "wind_mapping.parquet.bak",
    "wind_mapping_2025.parquet",
)


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file())
    return []


def _sample_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        digest.update(file.read(chunk_size))
        if path.stat().st_size > chunk_size:
            file.seek(max(0, path.stat().st_size - chunk_size))
            digest.update(file.read(chunk_size))
    return digest.hexdigest()


def _snapshot(path: Path) -> dict[str, object]:
    files = _files(path)
    samples = files[:2] + (files[-2:] if len(files) > 2 else [])
    return {
        "file_count": len(files),
        "total_bytes": sum(item.stat().st_size for item in files),
        "samples": {
            str(item.relative_to(path) if path.is_dir() else "<file>"): _sample_hash(item)
            for item in dict.fromkeys(samples)
        },
    }


def _copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=shutil.copy2)
    else:
        shutil.copy2(source, destination)


def _verify(source: Path, destination: Path) -> dict[str, object]:
    source_snapshot = _snapshot(source)
    destination_snapshot = _snapshot(destination)
    if source_snapshot != destination_snapshot:
        raise RuntimeError(f"Migration verification failed: {source} -> {destination}")
    return destination_snapshot


def _write_source_setting(target: Path) -> Path:
    # Shared by sibling feat/master worktrees and every nested issue worktree.
    # .settings lives at feat parent, not DATA_DIR parent.
    settings_path = Path(get_feat_root()).resolve().parent / ".settings"
    payload: dict = {}
    if settings_path.is_file():
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    payload.setdefault("data_dir", str(Path(DATA_DIR).resolve()))
    payload.setdefault("source_data_dirs", {})[PROVIDER] = str(target.resolve())
    settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return settings_path


def migration_plan(source_root: Path, target_root: Path) -> list[tuple[Path, Path]]:
    plan = [
        (source_root / name, target_root / name)
        for name in SOURCE_ASSETS
        if (source_root / name).exists()
    ]
    artifact_dir = artifact_root(PROVIDER)
    if (source_root / "roller_info.parquet").exists():
        plan.append((source_root / "roller_info.parquet", artifact_dir / "roller_info.parquet"))
    for name in ("roller_info.csv", "roller_info.csv.bak", "roller_info.parquet.bak"):
        if (source_root / name).exists():
            plan.append((source_root / name, target_root / "legacy" / name))
    old_curve = source_root / "cn_futures_term_structure.parquet"
    if old_curve.exists():
        plan.append((old_curve, artifact_dir / "legacy" / "term_structure-v1-invalid.parquet"))
    return plan


def migrate(
    *,
    source_root: Path,
    target_root: Path,
    execute: bool,
    remove_source: bool,
) -> dict[str, object]:
    plan = migration_plan(source_root, target_root)
    result: dict[str, object] = {
        "dry_run": not execute,
        "source_root": str(source_root),
        "target_root": str(target_root),
        "assets": [{"source": str(source), "destination": str(destination)} for source, destination in plan],
    }
    if not execute:
        return result

    verified = []
    for source, destination in plan:
        _copy_asset(source, destination)
        verified.append({"destination": str(destination), **_verify(source, destination)})
    manifest = {
        **result,
        "dry_run": False,
        "completed_at": time.time(),
        "verified": verified,
    }
    target_root.mkdir(parents=True, exist_ok=True)
    manifest_path = target_root / "migration-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    settings_path = _write_source_setting(target_root)
    if remove_source:
        for source, _ in reversed(plan):
            if source.is_dir():
                shutil.rmtree(source)
            elif source.exists():
                source.unlink()
    return {**manifest, "manifest_path": str(manifest_path), "settings_path": str(settings_path)}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(DATA_DIR))
    parser.add_argument("--target", type=Path, default=Path(DATA_DIR) / "sources" / PROVIDER)
    parser.add_argument("--execute", action="store_true", help="Copy, verify, and activate the new storage root")
    parser.add_argument("--remove-source", action="store_true", help="Delete old assets only after successful verification")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.remove_source and not args.execute:
        parser.error("--remove-source requires --execute")
    print(json.dumps(migrate(
        source_root=args.source.resolve(),
        target_root=args.target.resolve(),
        execute=args.execute,
        remove_source=args.remove_source,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
