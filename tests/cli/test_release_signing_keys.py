from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.release.signing_keys import manifest_private_key


def test_beta_uses_persistent_server_release_key(tmp_path: Path) -> None:
    expected = (
        tmp_path
        / "Library/Application Support/FactorTester"
        / "server-release-signing/beta-private.pem"
    )
    expected.parent.mkdir(parents=True)
    expected.write_text("private", encoding="utf-8")

    assert manifest_private_key("beta", None, home=tmp_path) == expected


def test_explicit_key_takes_precedence(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.pem"

    assert manifest_private_key("stable", explicit, home=tmp_path) == explicit


def test_main_requires_explicit_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Main"):
        manifest_private_key("stable", None, home=tmp_path)


def test_beta_rejects_missing_persistent_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not installed"):
        manifest_private_key("beta", None, home=tmp_path)
