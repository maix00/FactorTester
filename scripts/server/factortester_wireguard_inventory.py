#!/usr/bin/env python3
"""Safely manage signed public WireGuard inventory and owner-local configs."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.deployment.wireguard import (
    InventorySigningKey,
    generate_inventory_signing_key,
    render_wireguard_config,
    sign_inventory,
    verify_signed_inventory,
)


def _write_new(path: Path, value: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing file: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            if not value.endswith("\n"):
                stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, mode)


def _read_text(path: str | Path, *, field: str) -> str:
    selected = Path(path).expanduser().resolve()
    try:
        value = selected.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"cannot read {field}: {selected}") from exc
    if not value:
        raise ValueError(f"{field} is empty: {selected}")
    return value


def _json(path: str | Path) -> dict[str, object]:
    try:
        value = json.loads(_read_text(path, field="inventory"))
    except json.JSONDecodeError as exc:
        raise ValueError("inventory is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("inventory must be a JSON object")
    return value


def _generate_signing_key(args: argparse.Namespace) -> None:
    output = Path(args.output_dir).expanduser().resolve()
    key = generate_inventory_signing_key()
    _write_new(output / "inventory-signing.key", key.private_key, mode=0o600)
    _write_new(output / "inventory-signing.pub", key.public_key, mode=0o644)
    _write_new(output / "inventory-signing.key-id", key.key_id, mode=0o644)
    print("Created inventory authority")


def _generate_node_key(args: argparse.Namespace) -> None:
    output = Path(args.output_dir).expanduser().resolve()
    private = X25519PrivateKey.generate()
    private_bytes = private.private_bytes_raw()
    public_bytes = private.public_key().public_bytes_raw()
    encode = lambda value: base64.b64encode(value).decode("ascii")
    _write_new(output / "wireguard.key", encode(private_bytes), mode=0o600)
    _write_new(output / "wireguard.pub", encode(public_bytes), mode=0o644)
    print("Created WireGuard identity")


def _sign(args: argparse.Namespace) -> None:
    directory = Path(args.signing_key_dir).expanduser().resolve()
    public_key = _read_text(
        directory / "inventory-signing.pub",
        field="inventory signing public key",
    )
    key = InventorySigningKey(
        private_key=_read_text(
            directory / "inventory-signing.key",
            field="inventory signing secret",
        ),
        public_key=public_key,
        key_id=_read_text(
            directory / "inventory-signing.key-id",
            field="inventory signing key id",
        ),
    )
    signed = sign_inventory(_json(args.inventory), signing_key=key)
    _write_new(
        Path(args.output).expanduser().resolve(),
        json.dumps(signed, ensure_ascii=False, sort_keys=True, indent=2),
        mode=0o644,
    )
    print(f"Signed inventory with authority {key.key_id}")


def _verify(args: argparse.Namespace) -> None:
    trusted_key = _read_text(
        args.trusted_public_key,
        field="trusted inventory public key",
    )
    inventory = verify_signed_inventory(
        _json(args.inventory),
        trusted_public_key=trusted_key,
    )
    print(
        f"Verified {inventory.cluster_id} generation {inventory.generation}"
    )


def _render(args: argparse.Namespace) -> None:
    trusted_key = _read_text(
        args.trusted_public_key,
        field="trusted inventory public key",
    )
    inventory = verify_signed_inventory(
        _json(args.inventory),
        trusted_public_key=trusted_key,
    )
    config = render_wireguard_config(
        inventory,
        server_id=args.server_id,
        tunnel=args.tunnel,
        private_key=_read_text(args.private_key, field="local WireGuard secret"),
    )
    output = Path(args.output).expanduser().resolve()
    _write_new(output, config, mode=0o600)
    print(str(output))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage signed FactorTester WireGuard inventory",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    signing = commands.add_parser("generate-signing-key")
    signing.add_argument("--output-dir", required=True)
    signing.set_defaults(handler=_generate_signing_key)

    node = commands.add_parser("generate-node-key")
    node.add_argument("--output-dir", required=True)
    node.set_defaults(handler=_generate_node_key)

    sign = commands.add_parser("sign")
    sign.add_argument("--inventory", required=True)
    sign.add_argument("--signing-key-dir", required=True)
    sign.add_argument("--output", required=True)
    sign.set_defaults(handler=_sign)

    verify = commands.add_parser("verify")
    verify.add_argument("--inventory", required=True)
    verify.add_argument("--trusted-public-key", required=True)
    verify.set_defaults(handler=_verify)

    render = commands.add_parser("render")
    render.add_argument("--inventory", required=True)
    render.add_argument("--trusted-public-key", required=True)
    render.add_argument("--server-id", required=True)
    render.add_argument("--tunnel", required=True)
    render.add_argument("--private-key", required=True)
    render.add_argument("--output", required=True)
    render.set_defaults(handler=_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        args.handler(args)
    except (KeyError, OSError, PermissionError, TypeError, ValueError) as exc:
        print(f"wireguard inventory error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
