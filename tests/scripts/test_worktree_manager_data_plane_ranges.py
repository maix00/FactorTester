from __future__ import annotations

import pytest

from server.manager.data_plane.ranges import (
    ByteRange,
    RangeNotSatisfiable,
    parse_byte_range,
)


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("", 10, ByteRange(0, 9, 10, partial=False)),
        ("bytes=0-4", 10, ByteRange(0, 4, 10, partial=True)),
        ("bytes=5-", 10, ByteRange(5, 9, 10, partial=True)),
        ("bytes=-3", 10, ByteRange(7, 9, 10, partial=True)),
        ("", 0, ByteRange(0, -1, 0, partial=False)),
    ],
)
def test_parse_single_byte_range(
    header: str,
    size: int,
    expected: ByteRange,
) -> None:
    assert parse_byte_range(header, size=size) == expected
    assert expected.length == max(0, expected.end - expected.start + 1)


@pytest.mark.parametrize(
    "header",
    ["bytes=10-", "bytes=8-7", "bytes=0-1,4-5", "items=0-1", "bytes=-0"],
)
def test_invalid_or_multi_range_is_rejected(header: str) -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_byte_range(header, size=10)


def test_ticket_window_restricts_requested_range() -> None:
    assert parse_byte_range(
        "bytes=4-7", size=12, allowed_start=4, allowed_end=11,
    ) == ByteRange(4, 7, 12, partial=True)
    with pytest.raises(RangeNotSatisfiable, match="capability"):
        parse_byte_range(
            "bytes=0-7", size=12, allowed_start=4, allowed_end=11,
        )

