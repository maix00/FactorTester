"""Bounded, atomic JSON artifact persistence."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import orjson


DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class JsonArtifactReceipt:
    content_hash: str
    size_bytes: int
    max_write_bytes: int


def write_json_artifact(
    target: Path,
    value: Any,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> JsonArtifactReceipt:
    """Stream one JSON value to an atomic target without a full bytes copy."""
    return _write_json_tokens(
        target,
        _value_tokens(value),
        chunk_size=chunk_size,
    )


def write_json_mapping_artifact(
    target: Path,
    *,
    fields: Mapping[str, Any],
    mapping_name: str,
    items: Iterable[tuple[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> JsonArtifactReceipt:
    """Stream a top-level mapping whose large member arrives item by item."""
    return _write_json_tokens(
        target,
        _mapping_tokens(fields, mapping_name, items),
        chunk_size=chunk_size,
    )


def _write_json_tokens(
    target: Path,
    tokens: Iterable[str | bytes],
    *,
    chunk_size: int,
) -> JsonArtifactReceipt:
    size_limit = max(1024, int(chunk_size))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.{os.getpid()}.tmp"
    digest = hashlib.sha256()
    size_bytes = 0
    max_write_bytes = 0
    buffer = bytearray()
    def write(raw: bytes, stream) -> None:
        nonlocal size_bytes, max_write_bytes
        if not raw:
            return
        stream.write(raw)
        digest.update(raw)
        size_bytes += len(raw)
        max_write_bytes = max(max_write_bytes, len(raw))

    try:
        with staging.open("wb") as stream:
            for text in tokens:
                raw = text if isinstance(text, bytes) else text.encode("utf-8")
                if len(raw) >= size_limit:
                    write(bytes(buffer), stream)
                    buffer.clear()
                    for start in range(0, len(raw), size_limit):
                        write(raw[start:start + size_limit], stream)
                    continue
                if len(buffer) + len(raw) > size_limit:
                    write(bytes(buffer), stream)
                    buffer.clear()
                buffer.extend(raw)
            write(bytes(buffer), stream)
            stream.flush()
            os.fsync(stream.fileno())
        staging.replace(target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return JsonArtifactReceipt(
        content_hash=digest.hexdigest(),
        size_bytes=size_bytes,
        max_write_bytes=max_write_bytes,
    )


def _mapping_tokens(
    fields: Mapping[str, Any],
    mapping_name: str,
    items: Iterable[tuple[str, Any]],
) -> Iterator[str]:
    yield "{"
    first = True
    for key, value in fields.items():
        if not first:
            yield ","
        first = False
        yield from _encoder().iterencode(str(key))
        yield ":"
        yield from _value_tokens(value)
    if not first:
        yield ","
    yield from _encoder().iterencode(str(mapping_name))
    yield ":{"
    first_item = True
    for key, value in items:
        if not first_item:
            yield ","
        first_item = False
        yield from _encoder().iterencode(str(key))
        yield ":"
        yield from _value_tokens(value)
    yield "}}"


def _value_tokens(value: Any) -> Iterator[str | bytes]:
    stream = getattr(value, "iter_json_tokens", None)
    if callable(stream):
        yield from stream()
        return
    if not _contains_streaming_value(value):
        yield orjson.dumps(value, default=_json_default)
        return
    if isinstance(value, Mapping):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield ","
            yield from _encoder().iterencode(str(key))
            yield ":"
            yield from _value_tokens(item)
        yield "}"
        return
    if isinstance(value, (list, tuple)):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _value_tokens(item)
        yield "]"
        return
    yield from _encoder().iterencode(value)


def _contains_streaming_value(value: Any) -> bool:
    if callable(getattr(value, "iter_json_tokens", None)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_streaming_value(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_streaming_value(item) for item in value)
    return False


def _encoder() -> json.JSONEncoder:
    return json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def _json_default(value: Any) -> Any:
    if value.__class__.__module__.startswith("numpy"):
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            return tolist()
        item = getattr(value, "item", None)
        if callable(item):
            return item()
    return str(value)
