#!/usr/bin/env python3
"""Bounded parallel upload over the deployment's existing authenticated SSH route."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import uuid


def upload_context(source: Path, destination: str, ssh: list[str], *, workers: int = 4, chunk_bytes: int = 4 * 1024 * 1024) -> None:
    if not 1 <= workers <= 4 or chunk_bytes <= 0:
        raise ValueError("invalid upload budget")
    files = sorted(source.iterdir())
    if not files or any(not p.is_file() or p.is_symlink() or (p.suffix != '.whl' and p.name not in {'checksums.sha256', 'build-id.txt'}) for p in files):
        raise ValueError("native context must contain only wheels and receipts")
    quote = shlex.quote
    def remote(command: str, payload: bytes | None = None, *, check: bool = True):
        return subprocess.run([*ssh, command], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)
    # Each worker holds one chunk. No local split files or duplicate complete wheel.
    for path in files:
        count = (path.stat().st_size + chunk_bytes - 1) // chunk_bytes
        prefix = f"{destination}/.chunk-{uuid.uuid4().hex}"
        def transfer(index: int) -> None:
            with path.open('rb') as stream:
                stream.seek(index * chunk_bytes)
                data = stream.read(chunk_bytes)
            target = f"{prefix}-{index:06d}"
            digest = hashlib.sha256(data).hexdigest()
            remote(f"cat > {quote(target)} && printf '%s  %s\\n' {quote(digest)} {quote(target)} | sha256sum -c - >/dev/null", data)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(transfer, range(count)))
        chunks = [f"{prefix}-{index:06d}" for index in range(count)]
        target = f"{destination}/{path.name}"
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        remote(f"{'cat ' + ' '.join(map(quote, chunks)) if chunks else ':'} > {quote(target)} && printf '%s  %s\\n' {quote(digest)} {quote(target)} | sha256sum -c - >/dev/null")
        for chunk in chunks:
            remote(f"unlink {quote(chunk)}")
        print(f"uploaded {path.name} bytes={path.stat().st_size} workers={workers}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--ssh-json', required=True)
    args = parser.parse_args()
    upload_context(args.source, args.destination, json.loads(args.ssh_json))


if __name__ == '__main__':
    main()
