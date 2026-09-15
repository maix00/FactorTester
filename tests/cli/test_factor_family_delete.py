"""Removing a factor family goes through the platform, not the workspace sync.

The workspace upload only propagates content changes, so a curated deletion
needs an explicit library command; these tests pin its contract.
"""

from __future__ import annotations

from click.testing import CliRunner

from tools.cli.client_factor_library import FactorLibraryClientMixin
from tools.cli.modules.custom_factors import controller


class _Session:
    def __init__(self):
        self.deleted = []

    def delete(self, path):
        self.deleted.append(path)
        return {"success": True}


class _Client(FactorLibraryClientMixin):
    def __init__(self):
        self.session = _Session()

    def _expect_success(self, payload):
        return payload


def test_client_deletes_by_kind_and_quoted_alias():
    client = _Client()
    client.delete_factor_family("public", "OiChgRat")
    client.delete_factor_family("custom", "带|参数")
    assert client.session.deleted == [
        "/api/factor-library/families/public/OiChgRat",
        "/api/factor-library/families/custom/%E5%B8%A6%7C%E5%8F%82%E6%95%B0",
    ]
    for kind in ("", "shared"):
        try:
            client.delete_factor_family(kind, "X")
        except ValueError as exc:
            assert "custom or public" in str(exc)
        else:  # pragma: no cover - the guard must reject it
            raise AssertionError(f"kind {kind!r} must be rejected")


def test_command_passes_kind_and_alias(monkeypatch):
    calls = []

    class _Fake:
        def delete_factor_family(self, kind, alias):
            calls.append((kind, alias))
            return {"success": True}

    monkeypatch.setattr(controller, "client_from_config", lambda: _Fake())
    monkeypatch.setattr(controller, "require_user_factor_library_write", lambda: None)
    result = CliRunner().invoke(
        controller.factor_library, ["family-delete", "--kind", "public", "OiChgRat"],
    )
    assert result.exit_code == 0, result.output
    assert calls == [("public", "OiChgRat")]


def test_command_requires_the_library_write_boundary(monkeypatch):
    import click

    def _deny():
        raise click.ClickException("只有用户本人可以修改用户因子库")

    monkeypatch.setattr(controller, "require_user_factor_library_write", _deny)
    result = CliRunner().invoke(controller.factor_library, ["family-delete", "OiChgRat"])
    assert result.exit_code != 0
    assert "只有用户本人" in result.output
