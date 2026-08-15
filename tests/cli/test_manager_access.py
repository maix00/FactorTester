from __future__ import annotations

import hashlib
import json

from click.testing import CliRunner

from tools.cli.http import HttpClientError
from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import ManagerConfig
from tools.cli.manager_app import manager_cli


def _method(*, auth: dict | None = None, requires_auth: bool = True) -> dict:
    body = b"#!/bin/sh\nprintf '%s\\n' safe\n"
    value = {
        "id": "operator-route",
        "kind": "operator-defined",
        "label": "服务器声明的连接方式",
        "script": {
            "id": "operator-route-v1",
            "filename": "connect.sh",
            "content_type": "text/x-shellscript",
            "sha256": hashlib.sha256(body).hexdigest(),
            "requires_auth": requires_auth,
        },
    }
    if auth is not None:
        value["auth"] = auth
    return value


def _patch_client(monkeypatch, methods, **extra):
    client = type(
        "Client",
        (),
        {
            "identity": lambda _self: {
                "success": True,
                "server": {"server_id": "public-1", "role": "main"},
                "factor_tester": {"control_port": 7998, "data_port": 7997},
                "management_access": methods,
            },
            **extra,
        },
    )()
    monkeypatch.setattr(
        "tools.cli.manager.commands._authenticated_client",
        lambda: (client, object()),
    )
    return client


def test_server_access_check_reports_redacted_local_readiness(monkeypatch) -> None:
    _patch_client(monkeypatch, [_method()])

    result = CliRunner().invoke(
        manager_cli,
        ["server", "access", "check", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["methods"][0]["ready"] is True
    assert "content" not in payload["methods"][0]
    assert "token" not in result.output


def test_script_download_blocks_when_declared_environment_credential_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("ALIYUN_ACCESS_KEY_ID", raising=False)
    called = []
    _patch_client(
        monkeypatch,
        [
            _method(
                auth={
                    "provider": "aliyun",
                    "source": "environment",
                    "environment": ["ALIYUN_ACCESS_KEY_ID"],
                    "setup_hint": "先配置本机阿里云凭证",
                    "required": True,
                },
            ),
        ],
        download_access_script_to_path=lambda *_args, **_kwargs: called.append(True),
    )

    result = CliRunner().invoke(
        manager_cli,
        [
            "server", "access", "script", "download",
            "--method", "operator-route",
            "--output", str(tmp_path / "connect.sh"),
        ],
    )

    assert result.exit_code != 0
    assert "先配置本机阿里云凭证" in result.output
    assert called == []


def test_script_download_can_be_explicitly_delegated_after_credential_override(
    monkeypatch,
    tmp_path,
) -> None:
    downloaded = []
    digest = hashlib.sha256(b"script").hexdigest()
    _patch_client(
        monkeypatch,
        [_method(auth={"source": "aliyun-cli", "required": True})],
        download_access_script_to_path=lambda _self, method_id, destination, **kwargs: (
            downloaded.append((method_id, destination, kwargs))
            or {
                "method_id": method_id,
                "path": str(destination),
                "size_bytes": 6,
                "sha256": digest,
                "executed": False,
            }
        ),
    )

    result = CliRunner().invoke(
        manager_cli,
        [
            "server", "access", "script", "download",
            "--method", "operator-route",
            "--output", str(tmp_path / "connect.sh"),
            "--skip-credential-check",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert downloaded[0][0] == "operator-route"
    assert downloaded[0][2]["expected_sha256"]
    assert json.loads(result.output)["executed"] is False


def test_factor_tester_job_actions_require_explicit_confirmation(monkeypatch) -> None:
    actions = []
    _patch_client(
        monkeypatch,
        [],
        job_action=lambda _self, job_id, action: (
            actions.append((job_id, action))
            or {"success": True, "job_id": job_id, "action": action}
        ),
    )
    runner = CliRunner()

    rejected = runner.invoke(manager_cli, ["jobs", "cancel", "job-1"])
    accepted = runner.invoke(
        manager_cli,
        ["jobs", "cancel", "job-1", "--yes", "--json"],
    )

    assert rejected.exit_code != 0
    assert accepted.exit_code == 0, accepted.output
    assert actions == [("job-1", "cancel")]


def test_manager_help_exposes_operations_without_host_admin_commands() -> None:
    result = CliRunner().invoke(manager_cli, ["--help"])

    assert result.exit_code == 0, result.output
    for command in ("devices", "transfers"):
        assert command in result.output
    assert "restart-fleet" not in result.output


def test_old_manager_contract_failure_is_actionable(monkeypatch) -> None:
    client = ManagerClient(ManagerConfig("http://127.0.0.1:7998"))

    def old_server(*_args, **_kwargs):
        raise HttpClientError(404, "http://127.0.0.1:7998/api/manager/identity", "not found")

    monkeypatch.setattr(client, "_request", old_server)

    try:
        client.identity()
    except RuntimeError as exc:
        assert "服务器访问契约" in str(exc)
    else:
        raise AssertionError("old Manager contract was not detected")
