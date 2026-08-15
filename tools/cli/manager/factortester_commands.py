"""FactorTester application commands for ``factortester-manager``.

These commands use the Manager control/data planes only.  They do not operate
the host, Docker, WireGuard, SSH, or any other infrastructure transport.
"""

from __future__ import annotations

from pathlib import Path

import click

from tools.cli.core.errors import friendly_errors
from tools.cli.manager import commands as manager_commands
from tools.cli.manager.commands import _echo, manager


def _authenticated_client():
    """Resolve through the auth module so callers can test the shared seam."""
    return manager_commands._authenticated_client()


def _print_job_rows(value: dict) -> None:
    for item in value.get("jobs") or ():
        if not isinstance(item, dict):
            continue
        click.echo(
            f"{item.get('job_id') or '-'} "
            f"status={item.get('status') or '-'} "
            f"port={item.get('port') or '-'} "
            f"server={item.get('server_id') or item.get('source_server_id') or '-'}"
        )


@manager.group("jobs")
def jobs() -> None:
    """Inspect FactorTester Jobs."""


@jobs.command("list")
@click.option(
    "--scope",
    type=click.Choice(["server", "mine", "subordinates", "cross-server"]),
    default="server",
    show_default=True,
)
@click.option("--source-scope", default="")
@click.option("--limit", type=click.IntRange(1, 200), default=20)
@click.option("--cursor", default="")
@click.option("--page", type=click.IntRange(1), default=1)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_jobs(
    scope: str,
    source_scope: str,
    limit: int,
    cursor: str,
    page: int,
    as_json: bool,
) -> None:
    """List local or federated Jobs from the authenticated Manager."""
    client, _ = _authenticated_client()
    value = client.jobs(
        scope=scope,
        source_scope=source_scope,
        limit=limit,
        cursor=cursor,
        page=page,
    )
    if as_json:
        _echo(value, True)
    else:
        _print_job_rows(value)


@jobs.command("ports")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_job_ports(as_json: bool) -> None:
    """List FactorTester service ports visible to this Manager."""
    client, _ = _authenticated_client()
    value = client.job_ports()
    if as_json:
        _echo(value, True)
    else:
        click.echo("\n".join(str(port) for port in value.get("ports") or ()))


@manager.group("artifacts")
def artifacts() -> None:
    """Inspect and download retained Job artifacts through the 7997 data plane."""


@artifacts.command("list")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_artifacts(job_id: str, as_json: bool) -> None:
    client, _ = _authenticated_client()
    value = client.job_artifacts(job_id)
    if as_json:
        _echo(value, True)
    else:
        for item in value.get("artifacts") or ():
            if isinstance(item, dict):
                click.echo(
                    f"{item.get('name') or '-'} "
                    f"size={item.get('size_bytes', 0)} "
                    f"state={item.get('state') or '-'}"
                )


@artifacts.command("download")
@click.argument("job_id")
@click.argument("name")
@click.option(
    "--output",
    "destination",
    type=click.Path(path_type=Path),
    required=True,
)
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def download_artifact(
    job_id: str,
    name: str,
    destination: Path,
    as_json: bool,
) -> None:
    """Download one artifact with a short-lived 7997 capability."""
    client, _ = _authenticated_client()
    value = client.artifact_download_to_path(job_id, name, destination)
    _echo(value, as_json)


@manager.group("storage")
def storage() -> None:
    """Read FactorTester Job and artifact storage usage."""


@storage.command("usage")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def storage_usage(as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.job_storage(), as_json)


@manager.group("research-graph")
def research_graph() -> None:
    """Inspect and activate the server's default Research Graph version."""


@research_graph.command("versions")
@click.argument("graph_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def research_graph_versions(graph_id: str, as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.research_graph_versions(graph_id), as_json)


@research_graph.command("active")
@click.argument("graph_id")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def research_graph_active(graph_id: str, as_json: bool) -> None:
    client, _ = _authenticated_client()
    _echo(client.active_research_graph(graph_id), as_json)


@research_graph.command("set-default")
@click.argument("graph_id")
@click.argument("version", type=click.IntRange(1))
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def set_default_research_graph(
    graph_id: str,
    version: int,
    as_json: bool,
) -> None:
    client, _ = _authenticated_client()
    _echo(client.activate_research_graph(graph_id, version), as_json)


@manager.group("services")
def services() -> None:
    """Control FactorTester service instances owned by this Manager."""


@services.command("list")
@click.option("--json", "as_json", is_flag=True)
@friendly_errors
def list_services(as_json: bool) -> None:
    client, _ = _authenticated_client()
    value = client.instances()
    if as_json:
        _echo(value, True)
        return
    for item in value.get("worktrees") or ():
        click.echo(
            f"{item.get('label') or item.get('instance_id')} "
            f"port={item.get('port')} "
            f"status={'running' if item.get('running') else 'stopped'}"
        )


def _service_action(name: str, help_text: str):
    @services.command(name, help=help_text)
    @click.argument("port", type=click.IntRange(1, 65535))
    @click.option("--json", "as_json", is_flag=True)
    @friendly_errors
    def command(port: int, as_json: bool) -> None:
        client, _ = _authenticated_client()
        matches = [
            item for item in (client.instances().get("worktrees") or ())
            if int(item.get("port") or 0) == port
        ]
        if not matches:
            raise click.ClickException(f"没有找到端口 {port} 对应的 FactorTester 服务")
        if len(matches) != 1:
            raise click.ClickException(f"端口 {port} 对应多个 FactorTester 服务")
        instance_id = str(matches[0].get("instance_id") or "").strip()
        if not instance_id:
            raise click.ClickException(f"端口 {port} 缺少 FactorTester 服务身份")
        value = client.action(instance_id, name)
        value.pop("instance_id", None)
        value["port"] = port
        _echo(value, as_json)

    return command


_service_action("start", "Start one stopped FactorTester service.")
_service_action("stop", "Stop one idle FactorTester service.")
_service_action("restart-api", "Restart one FactorTester service API.")
_service_action("restart-bundle", "Restart one complete FactorTester service.")
_service_action("force-stop", "Force-stop one FactorTester service.")


def register_factor_tester_commands() -> None:
    """Import-time Click registration seam for the Manager entrypoint."""


__all__ = ["register_factor_tester_commands"]
