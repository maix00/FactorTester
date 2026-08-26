import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from tools.cli.commands import (
    client_profile_factor_reference,
    client_profile_factor_set,
)
from tools.cli.commands.client_release import client
from tools.cli.release import profile_factor_set_queries
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile

CANONICAL_20D = "SgCPS|P:CA|N:20d|$F:30m"
CANONICAL_40D = "SgCPS|P:CA|N:40d|$F:30m"


def test_profile_factor_reference_freezes_the_committed_blob(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    monkeypatch.setattr(
        client_profile_factor_reference,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", CANONICAL_20D,
        "--object-kind", "factor",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["kind"] == "factor"
    assert value["object_kind"] == "factor"
    assert value["factor_alias"] == CANONICAL_20D
    assert value["record"]["alias"] == CANONICAL_20D
    assert value["target_ref"].startswith("factor:v2:")
    assert "factortester://" not in result.output


def test_profile_factor_reference_rejects_uncommitted_source(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    source.write_text("factor = 2\n", encoding="utf-8")
    monkeypatch.setattr(
        client_profile_factor_reference,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", "SgCPS",
        "--object-kind", "factor-family",
    ])

    assert result.exit_code != 0
    assert "differs from the selected workspace revision" in result.output


def test_profile_factor_reference_rejects_noncanonical_display_alias(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    monkeypatch.setattr(
        client_profile_factor_reference,
        "load_profile_root",
        lambda _path: root,
    )

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", "SgCPS|P:[CA]|N:20d",
        "--object-kind", "factor",
        "--json",
    ])

    assert result.exit_code != 0
    assert "Non-canonical factor identity" in result.output
    assert CANONICAL_20D in result.output


def test_profile_factor_set_has_stable_id_and_frozen_member_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    member_result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "reference", "maxa",
        "--source-file", str(source),
        "--identity", CANONICAL_20D,
        "--object-kind", "factor",
        "--json",
    ])
    assert member_result.exit_code == 0, member_result.output
    member = json.loads(member_result.output)
    member_ref = member["target_ref"]

    created = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "momentum-column-2025",
        "--title-zh", "2025年动量因子列",
        "--member-record", json.dumps(member["record"]),
        "--json",
    ])
    assert created.exit_code == 0, created.output
    created_value = json.loads(created.output)
    assert created_value["set_ref"].startswith("factor-set:v2:")
    assert created_value["member_count"] == 1
    assert "member_refs" not in created_value

    worktree = source.parents[1]
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(worktree),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "factor set",
    ], check=True)
    frozen = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "reference", "maxa",
        "--set-id", "momentum-column-2025",
        "--json",
    ])
    assert frozen.exit_code == 0, frozen.output
    value = json.loads(frozen.output)
    assert value["kind"] == "factor"
    assert value["object_class"] == "FactorSet"
    assert value["target_ref"] == created_value["set_ref"]
    assert value["member_count"] == 1
    assert "member_refs" not in value
    assert value["target_ref"].startswith("factor-set:v2:")

    members = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "members",
        "--target-ref", value["target_ref"], "--limit", "1", "--json",
    ])
    assert members.exit_code == 0, members.output
    page = json.loads(members.output)
    assert page["member_count"] == 1
    assert page["has_more"] is False
    assert page["related_references"][0]["target_ref"] == member_ref

    descriptor = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "descriptor",
        "--target-ref", value["target_ref"], "--json",
    ])
    assert descriptor.exit_code == 0, descriptor.output
    descriptor_value = json.loads(descriptor.output)
    assert descriptor_value["target_ref"] == value["target_ref"]
    assert descriptor_value["manifest"]["identity"]["members"][0][
        "ref"
    ] == member_ref

    run_input = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "run-input",
        "--target-ref", value["target_ref"], "--json",
    ])
    assert run_input.exit_code == 0, run_input.output
    run_input_value = json.loads(run_input.output)
    assert run_input_value["descriptor"] == descriptor_value
    assert run_input_value["transient_factor_sources"] == []


def test_profile_factor_set_sync_explicitly_registers_frozen_descriptor(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    member = _factor_record(source, CANONICAL_20D)
    member_ref = member["ref"]
    runner = CliRunner()
    created = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "server-visible",
        "--title-zh", "服务器可见集合",
        "--member-record", json.dumps(member),
        "--json",
    ])
    assert created.exit_code == 0, created.output
    _commit_all(source.parents[1], "server-visible set")
    captured = {}

    class FakeClient:
        def register_factor_set(self, descriptor):
            captured.update(descriptor)
            return {"factor_set": {
                "target_ref": descriptor["target_ref"],
                "set_ref": descriptor["manifest"]["ref"],
            }}

    monkeypatch.setattr(
        client_profile_factor_set, "client_from_config", lambda: FakeClient(),
    )
    result = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "sync", "maxa",
        "--set-id", "server-visible", "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["set_ref"].startswith("factor-set:v2:")
    assert captured["target_ref"].startswith("factor-set:v2:")
    assert captured["manifest"]["identity"]["members"][0]["ref"] == member_ref


def test_profile_factor_set_local_catalog_aggregates_all_profiles(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    second_root, second_source = _profile_with_factor_worktree(
        tmp_path / "second",
    )
    second_profile = LocalProfileStore(second_root).load("maxa")
    second_profile["profile_id"] = "analyst"
    second_profile["display_name"] = "Analyst"
    binding = dict(second_profile["factor_workspace_binding"])
    binding["binding_id"] = "factor-analyst"
    second_profile["factor_workspace_binding"] = binding
    LocalProfileStore(root).save(second_profile)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    runner = CliRunner()
    for profile_id, factor_source, set_id in (
        ("maxa", source, "maxa-set"),
        ("analyst", second_source, "analyst-set"),
    ):
        member = _factor_record_for_profile(
            runner, profile_id, factor_source, CANONICAL_20D,
        )
        created = runner.invoke(client, [
            "profile", "factor-worktree", "factor-set", "create", profile_id,
            "--set-id", set_id,
            "--title-zh", f"{profile_id}因子集合",
            "--member-record", json.dumps(member),
            "--json",
        ])
        assert created.exit_code == 0, created.output
        _commit_all(factor_source.parents[1], f"{profile_id} factor set")

    result = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "profiles",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["scope"] == "local"
    assert value["profiles_scanned"] == 2
    assert value["count"] == 2
    assert value["errors"] == []
    assert {
        (item["profile_id"], item["set_id"], item["visibility"])
        for item in value["items"]
    } == {
        ("analyst", "analyst-set", "local"),
        ("maxa", "maxa-set", "local"),
    }

    monkeypatch.setattr(
        profile_factor_set_queries,
        "MAX_LOCAL_FACTOR_SET_ITEMS",
        1,
    )
    bounded = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "profiles",
        "--json",
    ])
    assert bounded.exit_code == 0, bounded.output
    bounded_value = json.loads(bounded.output)
    assert bounded_value["count"] == 1
    assert bounded_value["items_truncated"] is True
    assert bounded_value["profiles_scanned"] == 1


def test_profile_factor_set_rejects_legacy_noncanonical_member(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    monkeypatch.setattr(
        client_profile_factor_set,
        "load_profile_root",
        lambda _path: root,
    )
    worktree = source.parents[1]
    revision = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    blob = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD:custom_factors/SgCPS.py"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    legacy_record = {
        "schema_version": 1,
        "ref": f"factor:v1:{revision}:{blob}",
        "alias": "SgCPS|P:[CA]|N:20d",
        "owner_ref": "profile:maxa",
        "identity": {},
    }

    result = CliRunner().invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "legacy-members",
        "--title-zh", "旧别名集合",
        "--member-record", json.dumps(legacy_record),
        "--json",
    ])

    assert result.exit_code != 0
    assert "schema version 2" in result.output


def test_factor_set_introspection_and_guarded_update(
    tmp_path: Path, monkeypatch,
) -> None:
    root, source = _profile_with_factor_worktree(tmp_path)
    for module in (client_profile_factor_reference, client_profile_factor_set):
        monkeypatch.setattr(module, "load_profile_root", lambda _path: root)
    first_record = _factor_record(source, CANONICAL_20D)
    second_record = _factor_record(source, CANONICAL_40D)
    second_ref = second_record["ref"]
    runner = CliRunner()
    created = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "create", "maxa",
        "--set-id", "momentum-column",
        "--title-zh", "动量因子集合",
        "--description-zh", "用于窗口参数比较",
        "--member-record", json.dumps(first_record),
        "--json",
    ])
    assert created.exit_code == 0, created.output
    created_value = json.loads(created.output)
    worktree = source.parents[1]
    _commit_all(worktree, "factor set v1")
    first = _factor_set_reference(runner, "momentum-column")

    listed = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "list", "maxa",
        "--query", "窗口", "--json",
    ])
    assert listed.exit_code == 0, listed.output
    listed_value = json.loads(listed.output)
    assert listed_value["count"] == 1
    assert listed_value["items"][0]["target_ref"] == first["target_ref"]

    shown = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "show", "maxa",
        "--set-id", "momentum-column", "--json",
    ])
    assert shown.exit_code == 0, shown.output
    shown_value = json.loads(shown.output)
    assert shown_value["member_count"] == 1
    assert "member_refs" not in shown_value
    assert shown_value["member_resolution"]["command"] == "members"

    member_file = tmp_path / "members.json"
    member_file.write_text(
        json.dumps([first_record, second_record]), encoding="utf-8",
    )
    stale = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "update", "maxa",
        "--set-id", "momentum-column",
        "--expected-member-fingerprint", "0" * 64,
        "--title-zh", "动量因子集合",
        "--member-record-file", str(member_file),
    ])
    assert stale.exit_code != 0
    assert "stale" in stale.output

    updated = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "update", "maxa",
        "--set-id", "momentum-column",
        "--expected-member-fingerprint", created_value["member_fingerprint"],
        "--title-zh", "动量因子集合",
        "--description-zh", "用于窗口参数比较",
        "--member-record-file", str(member_file),
        "--json",
    ])
    assert updated.exit_code == 0, updated.output
    updated_value = json.loads(updated.output)
    assert updated_value["member_count"] == 2
    assert "member_refs" not in updated_value
    assert updated_value["next_actions"][0]["argv"][6] == "maxa"
    _commit_all(worktree, "factor set v2")
    second = _factor_set_reference(runner, "momentum-column")

    diff = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "diff",
        "--from-target-ref", first["target_ref"],
        "--to-target-ref", second["target_ref"],
        "--json",
    ])
    assert diff.exit_code == 0, diff.output
    diff_value = json.loads(diff.output)
    assert diff_value["changes"] == [{
        "change": "added", "target_ref": second_ref,
    }]
    assert diff_value["has_more"] is False


def _profile_with_factor_worktree(
    tmp_path: Path,
) -> tuple[Path, Path]:
    worktree = tmp_path / "factor-worktree"
    source = worktree / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from tools.factors import FactorFamily\n"
        "from tools.parameters import DataColumnParam, WindowParam\n\n"
        "class SgCPS(FactorFamily):\n"
        "    @staticmethod\n"
        "    def factor_expr():\n"
        "        P = DataColumnParam('P', default_value='CA')\n"
        "        N = WindowParam('N', default_value='20d')\n"
        "        return (P - P.shift(N)) / (P.shift(N) + 1e-10)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(worktree),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "factor",
    ], check=True)
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-maxa",
        "canonical_repo_ref": "local-factor-git:maxa",
        "base_commit": head,
        "branch": "research-maxa",
        "worktree_path": str(worktree),
        "research_root": str(tmp_path / "workspace" / "research"),
        "git_common_dir": str(worktree / ".git"),
        "owner_ref": "owner-1",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "a" * 64,
        "receipt_ref": (tmp_path / "binding.json").resolve().as_uri(),
    }
    LocalProfileStore(root).save(profile)
    return root, source


def _factor_ref(source: Path, identity: str) -> str:
    return _factor_record(source, identity)["ref"]


def _factor_record(source: Path, identity: str) -> dict:
    return _factor_record_for_profile(CliRunner(), "maxa", source, identity)


def _factor_ref_for_profile(
    runner: CliRunner,
    profile_id: str,
    source: Path,
    identity: str,
) -> str:
    return _factor_record_for_profile(
        runner, profile_id, source, identity,
    )["ref"]


def _factor_record_for_profile(
    runner: CliRunner,
    profile_id: str,
    source: Path,
    identity: str,
) -> dict:
    result = runner.invoke(client, [
        "profile", "factor-worktree", "reference", profile_id,
        "--source-file", str(source),
        "--identity", identity,
        "--object-kind", "factor",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["record"]


def _factor_set_reference(runner: CliRunner, set_id: str) -> dict:
    result = runner.invoke(client, [
        "profile", "factor-worktree", "factor-set", "reference", "maxa",
        "--set-id", set_id, "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _commit_all(repository: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repository),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", message,
    ], check=True)
