"""Bound one HTTP request body without buffering it in memory or on disk."""

from __future__ import annotations


class IncompleteRequestBody(ValueError):
    pass


class BoundedRequestBody:
    """Expose exactly ``length`` bytes from an inbound HTTP stream."""

    def __init__(self, stream, *, length: int) -> None:
        self.stream = stream
        self.remaining = int(length)
        if self.remaining < 0:
            raise ValueError("request body length must not be negative")

    def read(self, size: int = -1) -> bytes:
        if self.remaining == 0:
            return b""
        bounded = self.remaining if size < 0 else min(self.remaining, size)
        chunk = self.stream.read(bounded)
        if not chunk:
            raise IncompleteRequestBody(
                f"request ended with {self.remaining} bytes remaining"
            )
        if len(chunk) > self.remaining:
            raise ValueError("request stream exceeded its declared length")
        self.remaining -= len(chunk)
        return chunk
