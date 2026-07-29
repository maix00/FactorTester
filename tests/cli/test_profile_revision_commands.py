import json

from click.testing import CliRunner

from tools.cli.commands import client_profile_revision
from tools.cli.commands.client_release import client_release
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile


def test_profile_revision_freeze_and_show_return_the_same_exact_target(
    tmp_path, monkeypatch,
) -> None:
    root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    LocalProfileStore(root).save(profile)
    monkeypatch.setattr(
        client_profile_revision,
        "load_profile_root",
        lambda _path: root,
    )
    runner = CliRunner()

    frozen = runner.invoke(client_release, [
        "profile", "revision", "freeze", "maxa", "--json",
    ])
    assert frozen.exit_code == 0, frozen.output
    target_ref = json.loads(frozen.output)["target_ref"]
    assert target_ref.startswith("profile-revision:v1:maxa:sha256:")

    shown = runner.invoke(client_release, [
        "profile", "revision", "show", target_ref, "--json",
    ])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["target_ref"] == target_ref


def test_profile_revision_freeze_never_emits_a_markdown_link(
    tmp_path, monkeypatch,
) -> None:
    root = tmp_path / "client"
    LocalProfileStore(root).save(new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    ))
    monkeypatch.setattr(
        client_profile_revision,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client_release, [
        "profile", "revision", "freeze", "maxa",
    ])

    assert result.exit_code == 0
    assert result.output.startswith("profile-revision:v1:maxa:sha256:")
    assert "factortester://" not in result.output
