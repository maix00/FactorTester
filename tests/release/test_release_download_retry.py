from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from tools.cli.release import artifacts, profile
from tools.cli.release.contracts import ReleaseAsset


class _Response(BytesIO):
    def geturl(self) -> str:
        return "https://objects.example.test/asset"

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def test_transient_asset_download_retries_from_zero(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = b"verified wheel"
    calls = 0

    def open_once_then_succeed(_url: str, timeout: int):
        nonlocal calls
        assert timeout == 60
        calls += 1
        if calls == 1:
            raise OSError("transient TLS EOF")
        return _Response(content)

    monkeypatch.setattr(artifacts, "urlopen", open_once_then_succeed)
    monkeypatch.setattr(artifacts.time, "sleep", lambda _seconds: None)
    asset = ReleaseAsset(
        asset_id="client",
        kind="python-wheel",
        filename="client.whl",
        url="https://example.test/client.whl",
        sha256=sha256(content).hexdigest(),
        size=len(content),
    )

    receipt = artifacts.install_asset(
        asset,
        tmp_path,
        allow_file_urls=False,
    )
    assert calls == 2
    assert receipt["sha256"] == asset.sha256
    assert (tmp_path / "artifacts" / "client.whl").read_bytes() == content


def test_transient_manifest_download_retries(monkeypatch) -> None:
    content = b'{"schema_version":1}'
    calls = 0

    def open_once_then_succeed(_url: str, timeout: int):
        nonlocal calls
        assert timeout == 30
        calls += 1
        if calls == 1:
            raise OSError("transient TLS EOF")
        return _Response(content)

    monkeypatch.setattr(profile, "urlopen", open_once_then_succeed)
    monkeypatch.setattr(profile.time, "sleep", lambda _seconds: None)

    assert profile._read_manifest_with_retry(
        "https://example.test/release-manifest.json"
    ) == content
    assert calls == 2
