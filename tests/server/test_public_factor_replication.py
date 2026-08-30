from __future__ import annotations

import hashlib
from pathlib import Path

from server.manager.services import public_factor_replication as replication
from server.manager.storage.public_factor_replication import (
    PublicFactorReplicationStore,
)


class _Registry:
    def __init__(self) -> None:
        self.online = False
        self.extra: list[dict[str, object]] = []

    def servers(self, *, include_offline: bool) -> list[dict[str, object]]:
        assert include_offline is True
        return [
            {"server_id": "remote-main", "online": self.online},
            *self.extra,
        ]


class _Response:
    status = 200


class _State:
    server_id = "local-feat"

    def __init__(self) -> None:
        self.federation_registry = _Registry()
        self.invalidations = 0

    def route_for(self, *, server_id: str):
        assert server_id == "remote-main"
        return object()

    def route_request(self, _route, **kwargs):
        assert kwargs["path"] == (
            "/api/internal/factor-library/public-source-applied"
        )
        self.invalidations += 1
        return _Response()


def test_public_factor_replication_resumes_offline_target_once(
    monkeypatch, tmp_path: Path,
) -> None:
    source = "class PublicAlpha:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    state = _State()
    uploads: list[str] = []

    monkeypatch.setattr(
        replication, "load_public_factor_source",
        lambda factor_id: source if factor_id == "PublicAlpha" else None,
    )

    class _Transfer:
        def __init__(self, _state) -> None:
            pass

        def stage(self, entries, *, principal: str, target_server_id: str) -> None:
            assert principal == "root"
            assert entries[0]["canonical_family_ref"] == "public:PublicAlpha"
            uploads.append(target_server_id)

    monkeypatch.setattr(replication, "FactorSourceTransfer", _Transfer)
    service = replication.PublicFactorReplicationService(
        state, PublicFactorReplicationStore(tmp_path / "manager.sqlite"),
    )
    descriptor = {
        "factor_id": "PublicAlpha",
        "source_sha256": digest,
        "source_bytes": len(raw),
    }

    first = service.publish([descriptor], principal="root")

    assert first["complete"] is False
    assert uploads == []
    assert {row["status"] for row in first["targets"]} == {
        "completed", "pending",
    }

    state.federation_registry.online = True
    assert service.sync_pending() == {"completed": 1, "pending": 0, "failed": 0}
    second = service.publish([descriptor], principal="root")

    assert second["complete"] is True
    assert uploads == ["remote-main"]
    assert state.invalidations == 1


def test_public_factor_replication_includes_server_registered_after_publish(
    monkeypatch, tmp_path: Path,
) -> None:
    source = "class PublicAlpha:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    state = _State()
    state.federation_registry.online = True
    uploads: list[str] = []
    monkeypatch.setattr(
        replication, "load_public_factor_source", lambda _factor_id: source,
    )

    class _Transfer:
        def __init__(self, _state) -> None:
            pass

        def stage(self, entries, *, principal: str, target_server_id: str) -> None:
            uploads.append(target_server_id)

    monkeypatch.setattr(replication, "FactorSourceTransfer", _Transfer)
    service = replication.PublicFactorReplicationService(
        state, PublicFactorReplicationStore(tmp_path / "manager.sqlite"),
    )
    service.publish([{
        "factor_id": "PublicAlpha",
        "source_sha256": digest,
        "source_bytes": len(raw),
    }], principal="root")

    state.federation_registry.extra.append({
        "server_id": "new-server", "online": True,
    })
    original_route_for = state.route_for
    state.route_for = lambda *, server_id: object()
    service.sync_pending()
    state.route_for = original_route_for

    assert uploads == ["remote-main", "new-server"]


def test_public_factor_replication_rejects_changed_source(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        replication, "load_public_factor_source", lambda _factor_id: "changed",
    )
    service = replication.PublicFactorReplicationService(
        _State(), PublicFactorReplicationStore(tmp_path / "manager.sqlite"),
    )

    try:
        service.publish([{
            "factor_id": "PublicAlpha",
            "source_sha256": "0" * 64,
            "source_bytes": 1,
        }], principal="root")
    except ValueError as exc:
        assert str(exc) == "public factor source changed before publication"
    else:
        raise AssertionError("changed source must be rejected")
