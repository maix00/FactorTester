"""Small Unix-socket protocol for transferring immutable Arrow file handles.

The socket carries metadata only. Arrow bytes stay in the shared cache file and
are mapped by the consumer, so a same-host replay does not copy each batch
through Python or HTTP.
"""
from __future__ import annotations

from array import array
import json
import socket


MAX_FRAME_BYTES = 64 * 1024
MAX_RIGHTS = 1


class DataIOProtocolError(RuntimeError):
    pass


def encode_frame(value: dict) -> bytes:
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise DataIOProtocolError("data I/O protocol frame exceeds byte limit")
    return raw + b"\n"


def receive_frame(sock: socket.socket) -> tuple[dict, int | None]:
    """Receive one small response and at most one transferred descriptor."""
    ancillary_size = socket.CMSG_SPACE(MAX_RIGHTS * array("i").itemsize)
    raw, ancillary, flags, _address = sock.recvmsg(MAX_FRAME_BYTES + 1, ancillary_size)
    if flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
        raise DataIOProtocolError("truncated data I/O response")
    if not raw.endswith(b"\n"):
        raise DataIOProtocolError("incomplete data I/O response")
    descriptor = None
    for level, kind, payload in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            values = array("i")
            values.frombytes(payload[: len(payload) - (len(payload) % values.itemsize)])
            if descriptor is not None or len(values) != 1:
                for value in values:
                    socket.close(value)
                raise DataIOProtocolError("unexpected number of transferred descriptors")
            descriptor = values[0]
    try:
        value = json.loads(raw[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if descriptor is not None:
            socket.close(descriptor)
        raise DataIOProtocolError("invalid data I/O response") from exc
    if not isinstance(value, dict):
        if descriptor is not None:
            socket.close(descriptor)
        raise DataIOProtocolError("data I/O response must be an object")
    return value, descriptor


def send_frame(sock: socket.socket, value: dict, descriptor: int | None = None,
               address=None) -> None:
    raw = encode_frame(value)
    if descriptor is None:
        if address is None:
            sock.sendall(raw)
        else:
            sock.sendto(raw, address)
        return
    rights = array("i", [descriptor])
    sent = sock.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)], 0, address)
    if sent != len(raw):
        raise DataIOProtocolError("short Unix-socket descriptor frame")

