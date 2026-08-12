from __future__ import annotations

import hashlib
import io
import threading
import zipfile
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.jobs.artifact_data_plane import (
    ArtifactTicketCodec,
    ArtifactTicketError,
    artifact_data_endpoint,
    artifact_data_url,
)
from server.jobs.models import JobRecord
from server.jobs.repository import JobRepository
from server.jobs.states import JobStatus
from scripts import worktree_artifact_server as data_server
from scripts.worktree_tls import configured_tls_paths


def test_artifact_ticket_is_bound_to_target_and_expires() -> None:
    codec = ArtifactTicketCodec(b"0123456789abcdef0123456789abcdef")
    token = codec.issue(
        owner="alice",
        job_id="job-1",
        name="result.json",
        server_id="node-a",
        now=100,
        ttl_seconds=10,
    )

    claims = codec.verify(
        token,
        owner="alice",
        job_id="job-1",
        name="result.json",
        server_id="node-a",
        now=105,
    )
    assert claims["exp"] == 110
    with pytest.raises(ArtifactTicketError):
        codec.verify(token, owner="bob", now=105)
    with pytest.raises(ArtifactTicketError, match="expired"):
        codec.verify(token, now=110)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ArtifactTicketError):
        codec.verify(tampered, now=105)


def test_artifact_data_endpoint_defaults_to_7997() -> None:
    endpoint = artifact_data_endpoint(endpoint="https://node.example:7998")
    assert endpoint == "https://node.example:7997"
    assert "/v1/artifacts/job-1/result.json" in artifact_data_url(
        endpoint,
        job_id="job-1",
        name="result.json",
        ticket="ticket",
    )


def test_artifact_tls_configuration_can_be_reused_by_manager_and_data_plane(
    tmp_path, monkeypatch,
) -> None:
    certificate = tmp_path / "server.crt"
    private_key = tmp_path / "server.key"
    certificate.write_text("certificate", encoding="ascii")
    private_key.write_text("private-key", encoding="ascii")
    monkeypatch.setenv("FACTORTESTER_ARTIFACT_TLS_CERT", str(certificate))
    monkeypatch.setenv("FACTORTESTER_ARTIFACT_TLS_KEY", str(private_key))

    assert configured_tls_paths(
        None,
        None,
        certificate_env="FACTORTESTER_ARTIFACT_TLS_CERT",
        private_key_env="FACTORTESTER_ARTIFACT_TLS_KEY",
    ) == (certificate.resolve(), private_key.resolve())


def test_artifact_data_server_supports_head_and_range(
    tmp_path, monkeypatch,
) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite")
    record = repository.create(JobRecord(
        job_id="job-1",
        run_id="run-1",
        owner="alice",
        workspace_id="workspace-1",
        kind="backtest",
        status=JobStatus.SUBMITTED,
        job_spec={"run_spec": {}},
    ))
    root = tmp_path / "artifacts"
    target = root / record.job_id / "result.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"abcdef")
    digest = hashlib.sha256(b"abcdef").hexdigest()
    repository.record_artifact(
        job_id=record.job_id,
        name="result",
        relative_path=f"{record.job_id}/result.json",
        content_type="application/json",
        content_hash=digest,
        size_bytes=6,
    )
    monkeypatch.setenv("GTHT_JOB_ARTIFACT_ROOT", str(root))
    monkeypatch.setattr(data_server, "JobRepository", lambda: repository)
    server = data_server.ArtifactDataHTTPServer(
        ("127.0.0.1", 0),
        data_server.ArtifactDataHandler,
        server_id="node-a",
    )
    server.codec = ArtifactTicketCodec(b"0123456789abcdef0123456789abcdef")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ticket = server.codec.issue(
            owner="alice", job_id="job-1", name="result", server_id="node-a",
        )
        url = (
            f"http://127.0.0.1:{server.server_port}"
            f"/v1/artifacts/job-1/result?ticket={ticket}"
        )
        with urlopen(Request(url, method="HEAD")) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == "6"
            assert response.read() == b""
        with urlopen(Request(url, headers={"Range": "bytes=1-3"})) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 1-3/6"
            assert response.read() == b"bcd"
        archive_ticket = server.codec.issue(
            owner="alice", job_id="job-1", name="__archive__", server_id="node-a",
        )
        archive_url = (
            f"http://127.0.0.1:{server.server_port}"
            f"/v1/artifacts/job-1/archive?ticket={archive_ticket}"
        )
        with urlopen(archive_url) as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                assert archive.read("result.json") == b"abcdef"
        with pytest.raises(HTTPError) as error:
            urlopen(url.replace("ticket=", "ticket=bad."))
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
