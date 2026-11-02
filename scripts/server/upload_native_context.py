#!/usr/bin/env python3
"""Bounded parallel upload over the deployment's existing authenticated SSH route."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time


def upload_context(source: Path, destination: str, ssh: list[str], *, workers: int = 4, chunk_bytes: int = 4 * 1024 * 1024) -> None:
    if not 1 <= workers <= 4 or not 1 <= chunk_bytes <= 4 * 1024 * 1024:
        raise ValueError("invalid upload budget")
    files = sorted(source.iterdir())
    if not files or any(not p.is_file() or p.is_symlink() or (p.suffix != '.whl' and p.name not in {'checksums.sha256', 'build-id.txt'}) for p in files):
        raise ValueError("native context must contain only wheels and receipts")
    quote = shlex.quote
    def remote(command: str, payload: bytes | None = None, *, check: bool = True):
        for attempt in range(3):
            try:
                result = subprocess.run([*ssh, command], input=payload,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            except subprocess.TimeoutExpired:
                if attempt == 2:
                    raise RuntimeError('native transfer timed out after three attempts') from None
            else:
                if result.returncode != 255:
                    if check:
                        result.check_returncode()
                    return result
                if attempt == 2:
                    raise RuntimeError('native SSH transfer failed after three attempts')
            time.sleep(.5 * (attempt + 1))

    def present(target: str, digest: str) -> bool:
        # Probe before passing bytes to SSH, otherwise a skipped remote cat
        # can still consume part of the payload through SSH's input buffers.
        result = remote(f"if test -f {quote(target)} && printf '%s  %s\\n' "
            f"{quote(digest)} {quote(target)} | sha256sum -c - >/dev/null 2>&1; "
            "then exit 0; else exit 44; fi", check=False)
        if result.returncode not in (0, 44):
            result.check_returncode()
        return result.returncode == 0

    def atomic_write(target: str, digest: str, producer: str, payload=None):
        # A lost acknowledgement is safe to retry: only verified complete
        # bytes replace the destination. Each server attempt owns its temp.
        remote(f"set -eu; tmp=$(mktemp {quote(target + '.part.XXXXXX')}); "
            "trap 'rm -f \"$tmp\"' EXIT HUP INT TERM; "
            f"{producer} > \"$tmp\"; printf '%s  %s\\n' {quote(digest)} \"$tmp\" "
            f"| sha256sum -c - >/dev/null; mv -f \"$tmp\" {quote(target)}", payload)

    # Each worker holds one chunk. No local split files or duplicate complete wheel.
    for path in files:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        target = f"{destination}/{path.name}"
        count = (path.stat().st_size + chunk_bytes - 1) // chunk_bytes
        prefix = f"{destination}/.chunk-{digest}-{chunk_bytes}"
        chunks = [f"{prefix}-{index:06d}" for index in range(count)]
        if present(target, digest):
            if chunks:
                remote('rm -f -- ' + ' '.join(map(quote, chunks)))
            print(f"upload cache=hit file={path.name}", flush=True)
            continue
        # Content identity makes interrupted uploads resumable without
        # trusting a local progress counter or accepting equal-sized bytes.
        def transfer(index: int) -> None:
            with path.open('rb') as stream:
                stream.seek(index * chunk_bytes)
                data = stream.read(chunk_bytes)
            target = f"{prefix}-{index:06d}"
            chunk_digest = hashlib.sha256(data).hexdigest()
            if not present(target, chunk_digest):
                atomic_write(target, chunk_digest, 'cat', data)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(transfer, index) for index in range(count)]
            for done, future in enumerate(as_completed(futures), 1):
                future.result()
                if done % workers == 0 or done == count:
                    print(f"upload file={path.name} checked_chunks={done}/{count}", flush=True)
        atomic_write(target, digest, 'cat ' + ' '.join(map(quote, chunks)) if chunks else ':')
        if chunks:
            remote('rm -f -- ' + ' '.join(map(quote, chunks)))
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
