from __future__ import annotations

import hashlib

from server.manager.services import factor_source_transfer
from server.manager.transfers.models import TransferStatus


def _entry() -> dict[str, object]:
    source = "class DemoFactor:\n    pass\n"
    raw = source.encode()
    return {
        "canonical_family_ref": "alice:DemoFactor",
        "source_code": source,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
    }


def test_same_manager_source_does_not_upload_again(monkeypatch) -> None:
    class State:
        server_id = "public-1"

        @staticmethod
        def prepare_object_upload(**_kwargs):
            raise AssertionError("same-manager source must not be uploaded")

    factor_source_transfer.FactorSourceTransfer(State()).stage(
        [_entry()], principal="alice", target_server_id="public-1",
    )


def test_remote_source_upload_consumes_ticket_on_loopback(monkeypatch) -> None:
    class State:
        server_id = "public-1"

        @staticmethod
        def prepare_object_upload(**_kwargs):
            return {
                "url": "http://public.example:7997/v1/transfers/a/upload",
                "bearer": "ticket",
            }

    requested = []
    monkeypatch.setattr(
        factor_source_transfer, "urlopen",
        lambda request, **kwargs: (
            requested.append((request.full_url, kwargs.get("context")))
            or _Response()
        ),
    )

    factor_source_transfer.FactorSourceTransfer(State()).stage(
        [_entry()], principal="alice", target_server_id="office-a",
    )

    assert requested == [(
        "http://127.0.0.1:7997/v1/transfers/a/upload", None,
    )]


def test_completed_remote_source_upload_is_not_repeated() -> None:
    class Requests:
        @staticmethod
        def by_idempotency_key(_key):
            return type("Transfer", (), {"status": TransferStatus.COMPLETED})()

    class State:
        server_id = "public-1"
        transfer_coordinator = type("Coordinator", (), {"requests": Requests()})()

        @staticmethod
        def prepare_object_upload(**_kwargs):
            raise AssertionError("completed source transfer must be reused")

    factor_source_transfer.FactorSourceTransfer(State()).stage(
        [_entry()], principal="alice", target_server_id="office-a",
    )


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None
