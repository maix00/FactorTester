from __future__ import annotations

import json
from pathlib import Path
import subprocess

from click.testing import CliRunner

from tools.cli.catalog import factor_resolution
from tools.cli.commands import client_catalog as catalog_commands
from tools.cli.commands.client_catalog import client_catalog
from tools.cli.release.research_reporting.references.factor_git import (
    validate_frozen_factor_identity,
    validate_frozen_factor_identities,
)
from tools.data.sqlite.factor_source_store import load_factor_source


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _factor_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repository = tmp_path / "factor-library"
    source = repository / "public_factors" / "MmRateOfChg.py"
    source.parent.mkdir(parents=True)
    canonical = load_factor_source("public", "", "MmRateOfChg")
    assert canonical
    source.write_text(canonical, encoding="utf-8")
    _git(repository, "init")
    _git(repository, "config", "user.name", "FactorTester Test")
    _git(repository, "config", "user.email", "factor@test.invalid")
    _git(repository, "add", "public_factors/MmRateOfChg.py")
    _git(repository, "commit", "-m", "Add factor")
    first = _git(repository, "rev-parse", "HEAD")
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# later revision\n",
        encoding="utf-8",
    )
    _git(repository, "add", "public_factors/MmRateOfChg.py")
    _git(repository, "commit", "-m", "Update factor")
    second = _git(repository, "rev-parse", "HEAD")
    return repository, first, second


def test_selected_commit_freezes_exact_blob_without_checkout(
    tmp_path, monkeypatch,
) -> None:
    repository, first, second = _factor_repository(tmp_path)
    monkeypatch.setattr(
        factor_resolution,
        "_owner_repository",
        lambda **_kwargs: (repository, "profile-maxa"),
    )

    value = factor_resolution.resolve_local_factor_reference(
        client_root=tmp_path / "client",
        owner_ref="profile:maxa",
        alias="MmRateOfChg|N:20d|$F:1d",
        revision=first,
    )

    assert value["owner_ref"] == "profile:maxa"
    assert value["git_commit"] == first
    assert value["git_commit"] != second
    assert value["relative_path"] == "public_factors/MmRateOfChg.py"
    assert value["factor_ref"].startswith("factor:v1:profile-maxa:")
    assert value["family_ref"].startswith("factor-family:v1:profile-maxa:")
    validated = validate_frozen_factor_identity(
        target_ref=value["factor_ref"], roots={"profile-maxa": repository},
    )
    assert validated["revision"] == first
    batch = validate_frozen_factor_identities(
        target_refs=[value["factor_ref"]],
        roots={"profile-maxa": repository},
    )
    assert batch[0]["revision"] == first


def test_missing_family_at_selected_commit_does_not_fall_back(
    tmp_path, monkeypatch,
) -> None:
    repository, first, _second = _factor_repository(tmp_path)
    monkeypatch.setattr(
        factor_resolution,
        "_owner_repository",
        lambda **_kwargs: (repository, "profile-maxa"),
    )

    try:
        factor_resolution.resolve_local_factor_reference(
            client_root=tmp_path / "client",
            owner_ref="profile:maxa",
            alias="NotPresent|N:20d|$F:1d",
            revision=first,
        )
    except ValueError as error:
        assert "no source" in str(error)
    else:
        raise AssertionError("missing factor family unexpectedly resolved")


def test_selected_owner_revision_lists_families_and_instantiates_candidate(
    tmp_path, monkeypatch,
) -> None:
    repository, first, second = _factor_repository(tmp_path)
    monkeypatch.setattr(
        factor_resolution,
        "_owner_repository",
        lambda **_kwargs: (repository, "profile-maxa"),
    )

    revisions = factor_resolution.list_local_factor_revisions(
        client_root=tmp_path / "client",
        owner_ref="profile:maxa",
        limit=10,
    )
    families = factor_resolution.list_local_factor_families(
        client_root=tmp_path / "client",
        owner_ref="profile:maxa",
        revision=first,
    )
    family = factor_resolution.describe_local_factor_family(
        client_root=tmp_path / "client",
        owner_ref="profile:maxa",
        revision=first,
        family="MmRateOfChg",
    )
    factor = factor_resolution.instantiate_local_factor(
        client_root=tmp_path / "client",
        owner_ref="profile:maxa",
        revision=first,
        family="MmRateOfChg",
        params={"P": "CA", "N": "20d", "$F": "1d", "$Rev": "0"},
    )

    assert [item["git_commit"] for item in revisions[:2]] == [second, first]
    assert [item["family"] for item in families] == ["MmRateOfChg"]
    assert families[0]["git_commit"] == first
    assert "params" not in families[0]
    assert family["family_ref"].startswith("factor-family:v1:profile-maxa:")
    assert {item["alias"] for item in family["params"]} >= {
        "P", "N", "$F", "$Rev",
    }
    assert factor["alias"] == "MmRateOfChg|P:CA|N:20d|$F:1d"
    assert factor["git_commit"] == first
    assert factor["factor_ref"].startswith("factor:v1:profile-maxa:")


def test_catalog_resolve_uses_authenticated_user_when_owner_is_omitted(
    tmp_path, monkeypatch,
) -> None:
    captured = {}

    class Client:
        def current_principal(self):
            return {"username": "18717974771"}

    def resolve(**kwargs):
        captured.update(kwargs)
        return {"factor_ref": "factor:v1:personal:path:alias:commit:blob"}

    monkeypatch.setattr(catalog_commands, "client_from_config", lambda: Client())
    monkeypatch.setattr(catalog_commands, "resolve_local_factor_reference", resolve)
    profile = tmp_path / "release.json"
    profile.write_text(
        json.dumps({
            "schema_version": 1,
            "release": {"install_root": str(tmp_path / "client")},
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        client_catalog,
        [
            "factor", "resolve",
            "--alias", "MmRateOfChg|N:20d|$F:1d",
            "--release-profile", str(profile),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["owner_ref"] == "user:18717974771"
    assert captured["revision"] == "HEAD"


def test_default_owner_uses_unique_local_profile_when_cli_session_is_empty(
    tmp_path, monkeypatch,
) -> None:
    class Client:
        def current_principal(self):
            return {"username": None}

    class Profiles:
        def __init__(self, _root):
            pass

        def list(self):
            return [{
                "session_binding": {"principal_ref": "18717974771"},
            }]

    monkeypatch.setattr(catalog_commands, "client_from_config", lambda: Client())
    monkeypatch.setattr(catalog_commands, "LocalProfileStore", Profiles)

    assert catalog_commands._current_user_owner_ref(tmp_path) == (
        "user:18717974771"
    )
