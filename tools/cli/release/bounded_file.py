"""Bounded regular-file reads for client-side report resources."""
from __future__ import annotations

import os
from pathlib import Path
import stat


def read_bounded_file(path: Path, maximum_bytes: int) -> bytes:
    """Reject oversized files before reading and again if they grow meanwhile."""
    if type(maximum_bytes) is not int or maximum_bytes < 0:
        raise ValueError('invalid file size limit')
    descriptor = os.open(Path(path), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum_bytes:
            raise ValueError('file exceeds size limit or is not a regular file')
        raw = source.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ValueError('file exceeds size limit')
    return raw
