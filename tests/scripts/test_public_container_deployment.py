from __future__ import annotations

import os
import re
import stat
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT = ROOT / "deploy" / "docker" / "factortester-public"


def _compose() -> dict:
    return yaml.safe_load((DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8"))


def _published_container_ports(service: dict) -> set[int]:
    result: set[int] = set()
    for item in service.get("ports") or []:
        match = re.search(r":(\d+)(?:/(?:tcp|udp))?$", str(item))
        if match:
            result.add(int(match.group(1)))
    return result


def test_public_compose_has_exactly_two_business_containers() -> None:
    compose = _compose()

    assert set(compose["services"]) == {
        "factortester-public",
        "postgresql-control",
    }


def test_public_compose_never_publishes_internal_service_or_postgres() -> None:
    services = _compose()["services"]
    source = (DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8")

    assert _published_container_ports(services["factortester-public"]) == {
        7998, 7997, 51820,
    }
    assert _published_container_ports(services["postgresql-control"]) == {51821}
    assert 8000 not in _published_container_ports(services["factortester-public"])
    assert 5432 not in _published_container_ports(services["postgresql-control"])
    assert "FACTORTESTER_FEDERATION_UDP_HOST_PORT:-51820" in source
    assert "FACTORTESTER_DB_WIREGUARD_UDP_HOST_PORT:-51821" in source


def test_public_compose_enforces_immutable_main_runtime() -> None:
    service = _compose()["services"]["factortester-public"]
    environment = service["environment"]

    assert environment["FACTORTESTER_HOT_RELOAD"] == "0"
    assert environment["FACTORTESTER_SERVICE_DEBUG"] == "0"
    assert environment["FACTORTESTER_ALLOW_PUBLIC_REGISTRATION"] == "0"
    assert environment["FACTORTESTER_REQUIRE_LOGIN_FOR_UI"] == "1"
    assert environment["FACTORTESTER_REQUIRE_DEVICE_AUTH"] == "1"
    assert service["restart"] == "unless-stopped"
    assert "depends_on" not in service


def test_public_image_excludes_development_only_dependencies() -> None:
    requirements = (
        ROOT / "deploy" / "requirements-public-linux.txt"
    ).read_text(encoding="utf-8")
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "requirements-public-linux.txt" in dockerfile
    for package in ("pytest", "mypy", "watchdog"):
        assert not re.search(rf"(?m)^{package}(?:\[|[<=>])", requirements)


def test_public_image_includes_runtime_localizations_and_git() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "COPY apple/Resources apple/Resources" in dockerfile
    assert re.search(r"(?m)^\s+git \\?$", dockerfile)


def test_public_manager_can_import_vendored_research_contracts() -> None:
    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(
        encoding="utf-8",
    )

    assert (
        "PYTHONPATH=/opt/factortester/app/tools/cli/agent-harness:"
        "/opt/factortester/app"
    ) in entrypoint


def test_wireguard_identities_are_separate_and_db_has_no_swift_peer_source() -> None:
    services = _compose()["services"]
    app = services["factortester-public"]
    database = services["postgresql-control"]

    app_mounts = {str(item.get("target")) for item in app["volumes"] if isinstance(item, dict)}
    db_mounts = {str(item.get("target")) for item in database["volumes"] if isinstance(item, dict)}
    assert "/run/secrets/federation-wireguard" in app_mounts
    assert "/run/secrets/database-wireguard" not in app_mounts
    assert "/run/secrets/database-wireguard" in db_mounts
    assert "/run/secrets/federation-wireguard" not in db_mounts
    assert "FACTORTESTER_DB_ALLOWED_WIREGUARD_CIDRS" in database["environment"]
    assert "SWIFT" not in repr(database).upper()


def test_public_wireguard_gateways_explicitly_enable_forwarding() -> None:
    services = _compose()["services"]

    for service_name in ("factortester-public", "postgresql-control"):
        service = services[service_name]
        assert service["sysctls"]["net.ipv4.ip_forward"] == "1"

    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(
        encoding="utf-8",
    )
    assert "net.ipv4.ip_forward" in entrypoint
    assert "FACTORTESTER_REQUIRE_PEER_LISTENERS:-1" in entrypoint


def test_private_database_network_is_not_the_udp_transport_network() -> None:
    compose = _compose()
    networks = compose["networks"]
    services = compose["services"]

    assert networks["private"]["internal"] is True
    assert "internal" not in networks["transport"]
    assert services["factortester-public"]["networks"]["private"]["ipv4_address"] == "172.30.185.2"
    assert services["postgresql-control"]["networks"]["private"]["ipv4_address"] == "172.30.185.3"


def test_public_entrypoint_uses_184_peer_contract_without_public_mapping() -> None:
    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(encoding="utf-8")

    assert "--overlay-bind-address" in entrypoint
    assert "--peer-port 17998" in entrypoint
    assert "--peer-data-port 17997" in entrypoint
    assert "17998:" not in (DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8")
    assert "17997:" not in (DEPLOYMENT / "compose.yaml").read_text(encoding="utf-8")


def test_public_compose_names_local_overlay_addresses_without_singular_peer() -> None:
    services = _compose()["services"]
    app_environment = services["factortester-public"]["environment"]
    database_environment = services["postgresql-control"]["environment"]

    assert "FACTORTESTER_FEDERATION_LOCAL_ADDRESS" in app_environment
    assert "FACTORTESTER_DATABASE_LOCAL_ADDRESS" in database_environment
    assert "FACTORTESTER_PEER_ADDRESS" not in repr(services)
    assert "FACTORTESTER_DB_PEER_ADDRESS" not in repr(services)
    assert ":?set FACTORTESTER_SERVER_ID" in app_environment["FACTORTESTER_SERVER_ID"]


def test_postgres_entrypoint_stages_root_only_inputs_for_postgres() -> None:
    entrypoint = (DEPLOYMENT / "postgres-entrypoint.sh").read_text(
        encoding="utf-8",
    )
    init_script = (DEPLOYMENT / "postgres-init-control.sh").read_text(
        encoding="utf-8",
    )

    assert "install -o postgres -g postgres -m 0600" in entrypoint
    assert 'export FACTORTESTER_CONTROL_DB_PASSWORD_FILE="$runtime_password_file"' in entrypoint
    assert 'export FACTORTESTER_POSTGRES_MIGRATION_DUMP="$runtime_migration_dump"' in entrypoint
    assert "FACTORTESTER_POSTGRES_MIGRATION_DUMP" in init_script


def test_postgres_healthcheck_requires_control_database() -> None:
    database = _compose()["services"]["postgresql-control"]
    healthcheck = " ".join(database["healthcheck"]["test"])

    assert "factortester_control" in healthcheck
    assert "pg_isready -U postgres -d postgres" not in healthcheck


def test_postgres_image_bootstraps_ca_before_using_https_mirrors() -> None:
    dockerfile = (DEPLOYMENT / "PostgreSQL.Dockerfile").read_text(
        encoding="utf-8",
    )

    ca_install = dockerfile.index("ca-certificates")
    https_mirror_switch = dockerfile.index("RUN sed -i")

    assert ca_install < https_mirror_switch


def test_public_compose_exposes_reproducible_package_mirror_inputs() -> None:
    services = _compose()["services"]
    app_args = services["factortester-public"]["build"]["args"]
    database_args = services["postgresql-control"]["build"]["args"]

    for args in (app_args, database_args):
        assert "DEBIAN_MIRROR" in args
        assert "DEBIAN_SECURITY_MIRROR" in args
    assert "PIP_INDEX_URL" in app_args
    assert "DEBIAN_BOOTSTRAP_MIRROR" in database_args
    assert "DEBIAN_BOOTSTRAP_SECURITY_MIRROR" in database_args


def test_postgres_image_provides_sysctl_used_by_its_entrypoint() -> None:
    dockerfile = (DEPLOYMENT / "PostgreSQL.Dockerfile").read_text(
        encoding="utf-8",
    )
    entrypoint = (DEPLOYMENT / "postgres-entrypoint.sh").read_text(
        encoding="utf-8",
    )

    assert "sysctl" in entrypoint
    assert re.search(r"(?m)^\s+procps \\?$", dockerfile)


def test_public_entrypoint_stages_root_only_tls_for_service_user() -> None:
    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(
        encoding="utf-8",
    )

    assert 'runtime_tls_key="$runtime_dir/manager.key"' in entrypoint
    assert 'install -o factortester -g "$app_group" -m 0600' in entrypoint
    assert 'export FACTORTESTER_MANAGER_TLS_KEY="$runtime_tls_key"' in entrypoint
    assert 'export FACTORTESTER_ARTIFACT_TLS_KEY="$runtime_tls_key"' in entrypoint


def test_postgres_image_switches_bootstrap_mirrors_after_ca_install() -> None:
    dockerfile = (DEPLOYMENT / "PostgreSQL.Dockerfile").read_text(
        encoding="utf-8",
    )

    ca_install = dockerfile.index("ca-certificates")
    mirror_switch = dockerfile.index(
        's|${DEBIAN_BOOTSTRAP_MIRROR}|${DEBIAN_MIRROR}|g',
    )
    security_switch = dockerfile.index(
        's|${DEBIAN_BOOTSTRAP_SECURITY_MIRROR}|${DEBIAN_SECURITY_MIRROR}|g',
    )

    assert ca_install < mirror_switch
    assert ca_install < security_switch


def test_public_image_revision_does_not_invalidate_dependency_layers() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    dependency_install = dockerfile.index("-r /tmp/requirements-public-linux.txt")
    revision_argument = dockerfile.index("ARG FACTORTESTER_REVISION")

    assert dependency_install < revision_argument


def test_public_verifier_loads_database_url_from_runtime_secret() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")

    assert "^FACTORTESTER_CONTROL_DATABASE_URL=" in script
    assert "/run/secrets/control-db.env" in script
    assert 'export FACTORTESTER_CONTROL_DATABASE_URL="${control_line#*=}"' in script
    assert "psycopg.connect(os.environ[\"FACTORTESTER_CONTROL_DATABASE_URL\"])" in script


def test_public_verifier_migrates_and_checks_control_database_schema() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")

    assert "control_store_from_env" in script
    assert "control_store.ensure_schema()" in script
    assert "CONTROL_DATABASE_SCHEMA_VERSION" in script
    assert "select coalesce(max(version), 0) from control_schema_migrations" in script


def test_public_verifier_checks_real_host_port_bindings() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")

    assert ".HostConfig.PortBindings" in script
    assert '"${compose[@]}" port postgresql-control 5432' not in script


def test_public_main_publish_is_one_incremental_rollback_safe_command() -> None:
    publish_path = ROOT / "scripts" / "server" / "publish_public_main.sh"
    publish = publish_path.read_text(encoding="utf-8")
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")

    assert publish_path.stat().st_mode & stat.S_IXUSR
    assert re.search(r'git -C "\$repo_root" push origin main', publish)
    assert 'main:refs/heads/main' in publish
    assert "activate_public_revision.sh" in publish
    assert "worktree add" in activate
    assert "--detach" in activate
    assert "build factortester-public" in activate
    assert "backup" in activate
    assert "restart-app" in activate
    assert "restore-check" in activate
    assert "verify" in activate
    assert "rollback" in activate
    assert "FACTORTESTER_PUBLIC_RELEASE_RETENTION:-3" in activate
    assert "docker image rm" in activate
    assert "git --git-dir=\"$git_root/repo.git\" worktree remove" in activate
    assert " container-id factortester-public" in activate
    assert " container-id postgresql-control" in activate
    assert "factortester-public-postgresql-control-1" not in activate
    assert "docker system prune" not in publish
    assert "docker system prune" not in activate
    assert activate.index(" backup") < activate.index("restart-app")
    assert activate.index("restart-app") < activate.index(" verify")
    assert "101.133.144.27" not in publish
    assert "/Users/maxdeux/.ssh" not in publish


def test_public_main_auto_update_is_server_local_and_timer_driven() -> None:
    updater_path = ROOT / "scripts" / "server" / "auto_update_public_main.sh"
    installer_path = (
        ROOT / "scripts" / "server" / "install_public_auto_update.sh"
    )
    service = (
        ROOT / "deploy" / "systemd" / "factortester-public-update.service.in"
    ).read_text(encoding="utf-8")
    timer = (
        ROOT / "deploy" / "systemd" / "factortester-public-update.timer"
    ).read_text(encoding="utf-8")
    updater = updater_path.read_text(encoding="utf-8")
    installer = installer_path.read_text(encoding="utf-8")

    assert updater_path.stat().st_mode & stat.S_IXUSR
    assert installer_path.stat().st_mode & stat.S_IXUSR
    assert "git --git-dir=\"$git_root/repo.git\" fetch" in updater
    assert "refs/heads/main:refs/heads/main" in updater
    assert "merge-base --is-ancestor" in updater
    assert "activate_public_revision.sh" in updater
    assert "2222" not in updater
    assert "ssh" not in updater
    assert "ExecStart=" in service
    assert "@DEPLOY_USER@" in service
    assert "OnCalendar=" in timer
    assert "Persistent=true" in timer
    assert "systemctl enable --now factortester-public-update.timer" in installer


def test_public_activation_staging_uses_deployer_writable_temp_directory() -> None:
    scripts = (
        ROOT / "scripts" / "server" / "publish_public_main.sh",
        ROOT / "scripts" / "server" / "auto_update_public_main.sh",
    )

    for path in scripts:
        script = path.read_text(encoding="utf-8")
        assert 'mktemp "$container_root/' not in script
        assert (
            'activation_script="$(mktemp '
            '"${TMPDIR:-/tmp}/factortester-activate.XXXXXX")"'
        ) in script


def test_public_activation_state_stays_in_deployer_owned_git_root() -> None:
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")

    assert 'deployment_log="$git_root/deployments.log"' in activate
    assert 'publish_lock="$git_root/.publish.lock"' in activate
    assert 'exec 9>"$publish_lock"' in activate
    assert '$container_root/deployments.log' not in activate
    assert '$container_root/.publish.lock' not in activate


def test_public_auto_update_fetches_and_activates_new_main(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    container_root = tmp_path / "container"
    production_env = tmp_path / "public.env"
    marker = tmp_path / "activated.txt"
    fake_bin = tmp_path / "bin"
    source.mkdir()
    container_root.mkdir()
    fake_bin.mkdir()

    subprocess.run(
        ["git", "init", "--initial-branch=main"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FactorTester Tests"],
        cwd=source,
        check=True,
    )
    activation = source / "scripts" / "server" / "activate_public_revision.sh"
    activation.parent.mkdir(parents=True)
    activation.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$FACTORTESTER_TEST_MARKER\"\n",
        encoding="utf-8",
    )
    activation.chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    old_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True,
    ).strip()

    subprocess.run(
        ["git", "init", "--bare", str(target / "repo.git")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git", f"--git-dir={target / 'repo.git'}", "fetch",
            str(source), f"{old_revision}:refs/heads/main",
        ],
        check=True,
        capture_output=True,
    )
    (source / "revision.txt").write_text("next\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-m", "next"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    new_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True,
    ).strip()
    production_env.write_text(
        f"FACTORTESTER_REVISION={old_revision}\n", encoding="utf-8",
    )
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    fake_sudo.chmod(0o755)

    environment = os.environ.copy()
    environment.update({
        "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
        "FACTORTESTER_REMOTE_GIT_ROOT": str(target),
        "FACTORTESTER_REMOTE_CONTAINER_ROOT": str(container_root),
        "FACTORTESTER_REMOTE_PUBLIC_ENV": str(production_env),
        "FACTORTESTER_PUBLIC_MAIN_REMOTE": str(source),
        "FACTORTESTER_TEST_MARKER": str(marker),
    })
    subprocess.run(
        [str(ROOT / "scripts" / "server" / "auto_update_public_main.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    arguments = marker.read_text(encoding="utf-8").splitlines()
    assert arguments == [
        new_revision,
        str(target),
        str(container_root),
        str(production_env),
        "3",
    ]
