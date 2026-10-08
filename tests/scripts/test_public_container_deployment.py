from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

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
    dockerignore = (DEPLOYMENT / "FactorTester.Dockerfile.dockerignore").read_text(
        encoding="utf-8",
    )

    assert "COPY apple/Resources apple/Resources" in dockerfile
    assert "COPY templates templates" not in dockerfile
    assert "!templates/" not in dockerignore
    assert "COPY skills skills" in dockerfile
    assert "COPY product_docs product_docs" in dockerfile
    assert "!product_docs/" in dockerignore
    assert "!product_docs/**" in dockerignore
    assert "!skills/" in dockerignore
    assert "!skills/**" in dockerignore
    assert re.search(r"(?m)^\s+git \\?$", dockerfile)


def test_public_image_contains_every_technical_doc_canonical_path() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    ).replace("\\\n", " ")
    copied_roots: set[str] = set()
    for line in dockerfile.splitlines():
        if not line.startswith("COPY "):
            continue
        tokens = shlex.split(line)
        copied_roots.update(token.rstrip("/") for token in tokens[1:-1])

    manifest = json.loads(
        (ROOT / "product_docs" / "manifest.json").read_text(encoding="utf-8")
    )
    canonical_paths = {
        path.rstrip("/")
        for section in manifest["sections"]
        for page in section["pages"]
        for path in page.get("canonical_paths", [])
    }

    for relative in canonical_paths:
        assert (ROOT / relative).exists(), relative
        assert any(
            relative == root or relative.startswith(f"{root}/")
            for root in copied_roots
        ), f"public image omits technical-documentation path: {relative}"


def test_public_agent_image_pins_codex_and_exposes_only_research_cli() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )
    compose = _compose()["services"]["factortester-public"]
    args = compose["build"]["args"]

    assert "nodejs" not in dockerfile
    assert "npm install" not in dockerfile
    assert "ARG CODEX_VERSION=0.147.0" in dockerfile
    assert "ARG CODEX_NPM_REGISTRY=https://registry.npmjs.org" in dockerfile
    assert "codex-${CODEX_VERSION}-${codex_platform}.tgz" in dockerfile
    assert "codex_sha512=" in dockerfile
    assert "Codex platform package integrity check failed" in dockerfile
    assert 'test "$(codex --version)" = "codex-cli ${CODEX_VERSION}"' in dockerfile
    assert "COPY tools tools" in dockerfile
    assert "AS factortester-cli-builder" in dockerfile
    assert "AS factortester-public-deps" in dockerfile
    assert "FROM factortester-public-deps AS factortester-cli-builder" in dockerfile
    assert "FROM factortester-public-deps AS factortester-public" in dockerfile
    assert "COPY tools/cli /runtime/tools/cli" in dockerfile
    cli_builder_stage = dockerfile.split(
        "FROM factortester-public-deps AS factortester-cli-builder", 1
    )[1].split("FROM factortester-public-deps AS factortester-public", 1)[0]
    assert "pip install" not in cli_builder_stage
    assert "python -m compileall -q -b /runtime" in dockerfile
    assert "find /runtime -type f -name '*.py' -delete" in dockerfile
    assert "COPY --from=factortester-cli-builder /runtime" in dockerfile
    assert "COPY deploy/docker/factortester-public/factortester-cli" in dockerfile
    runtime_stage = dockerfile.split(
        "FROM factortester-public-deps AS factortester-public", 1
    )[1]
    assert "PyInstaller" not in runtime_stage
    assert "pyinstaller==" not in runtime_stage
    assert "binutils" not in runtime_stage
    assert "/opt/factortester/app" not in (
        DEPLOYMENT / "factortester-cli"
    ).read_text(encoding="utf-8")
    assert "rm -f /usr/local/bin/factortester-manager" in dockerfile
    assert "test -x /usr/local/bin/factortester" in dockerfile
    assert args["CODEX_VERSION"] == "${FACTORTESTER_CODEX_VERSION:-0.147.0}"
    assert args["CODEX_NPM_REGISTRY"] == (
        "${FACTORTESTER_CODEX_NPM_REGISTRY:-https://registry.npmjs.org}"
    )


def test_public_agent_image_installs_cc_switch_from_verified_local_archives() -> None:
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )
    dockerignore = (DEPLOYMENT / "FactorTester.Dockerfile.dockerignore").read_text(
        encoding="utf-8",
    )
    archives = {
        "cc-switch-cli-linux-x64-musl-v5.10.2.tar.gz": (
            "8065c5bae9eda270747c1766cefbb2091d9625655dbf409ad7764eb47c0a8635"
        ),
        "cc-switch-cli-linux-arm64-musl-v5.10.2.tar.gz": (
            "b25c77f7eebbe3968c53022e1b5e703e324203e94e5c6379320bcd1bbe268e63"
        ),
    }

    assert "github.com/SaladDay/cc-switch-cli/releases" not in dockerfile
    for name, expected_digest in archives.items():
        archive = DEPLOYMENT / name
        assert archive.is_file()
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_digest
        assert f"!deploy/docker/factortester-public/{name}" in dockerignore
        assert f"COPY deploy/docker/factortester-public/{name}" in dockerfile
        assert expected_digest in dockerfile


def test_public_agent_uses_codex_secure_container_profile() -> None:
    services = _compose()["services"]
    service = services["factortester-public"]
    database = services["postgresql-control"]
    dockerfile = (DEPLOYMENT / "FactorTester.Dockerfile").read_text(
        encoding="utf-8",
    )

    assert {
        "SYS_ADMIN",
        "SYS_CHROOT",
        "SETUID",
        "SETGID",
        "SYS_PTRACE",
        "NET_ADMIN",
        "NET_RAW",
    }.issubset(set(service["cap_add"]))
    assert service["security_opt"] == [
        "seccomp=unconfined",
        "apparmor=unconfined",
    ]
    assert service.get("privileged", False) is not True
    assert "no-new-privileges:true" not in service["security_opt"]
    assert "chmod u+s /usr/bin/bwrap" in dockerfile
    assert "SYS_ADMIN" not in database.get("cap_add", [])
    assert database["security_opt"] == ["no-new-privileges:true"]


def test_public_manager_can_import_vendored_research_contracts() -> None:
    entrypoint = (DEPLOYMENT / "factortester-entrypoint.sh").read_text(
        encoding="utf-8",
    )

    assert (
        "PYTHONPATH=/opt/factortester/app"
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
    assert "FACTORTESTER_PUBLIC_CACHE_FROM" in (
        services["factortester-public"]["build"]["cache_from"][0]
    )
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


def test_public_restore_check_uses_pre_migration_table_count() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")

    assert "control_table_count" in script
    assert "control-table-count" in script
    assert 'restore_check "$@"' in script
    assert "postgres_table_count_before" in activate
    assert 'restore-check \"$postgres_table_count_before\"' in activate


def test_public_factor_identity_migration_is_explicit_and_rollback_safe() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")

    assert "migrate-factor-identities" in script
    assert "migrate_factor_source_metadata" in script
    assert "migrate_factor_formula_identity" in script
    assert "--discard-incompatible" not in script
    assert "migrate_factor_catalog_projection --apply" in script
    assert "--control-plan /state/factor-v2-control-plan.json" in script
    assert "migrate-factor-control-identities" in script
    assert "restore-factor-control-identities" in script
    assert "PRAGMA integrity_check" in script
    assert "schema_version=1" in script
    assert "legacy factor revision manifests" in script
    # Historical upgrades remain explicit maintenance commands. Ordinary
    # publication and application rollback must not mutate factor identities.
    for command in (
        "migrate-factor-identities", "migrate-factor-control-identities",
        "restore-factor-identities", "restore-factor-control-identities",
        "finalize-factor-identities",
    ):
        assert command not in activate
    stop_index = activate.index('bash "$public_script" stop-app')
    preflight_index = activate.index('bash "$public_script" graph-removal-dry-run')
    apply_index = activate.index('bash "$public_script" graph-removal-apply')
    switch_index = activate.index('sudo mv "$switch_env" "$production_env"')
    verify_index = activate.index('bash "$public_script" verify')
    assert stop_index < preflight_index < apply_index < switch_index < verify_index
    assert "run --rm --no-deps --entrypoint /bin/sh factortester-public" in script


def test_public_graph_cutover_is_offline_verified_and_rollback_safe() -> None:
    script = (
        ROOT / "scripts" / "server" / "factortester_public_container.sh"
    ).read_text(encoding="utf-8")
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")
    migration = (
        ROOT / "tools" / "migrations" / "remove_research_graph.py"
    ).read_text(encoding="utf-8")

    assert "graph-removal-dry-run" in script
    assert "--backup '$backup' --files-backup '$files_backup'" in script
    assert "--restore-backup --summary-only" in script
    assert "graph_migration_started=1" in activate
    assert 'bash "$public_script" restore-graph-removal "$graph_migration_attempt"' in activate
    assert "Graph-free post-cutover inventory failed" in activate
    assert "ordinary table row counts changed during Graph cutover" in activate
    rollback = activate[activate.index("rollback() {"):activate.index("trap rollback ERR INT TERM")]
    assert rollback.index("stop-app") < rollback.index("restore-graph-removal")
    assert rollback.index("restore-graph-removal") < rollback.index("restart-app")
    assert "def restore_backup(" in migration
    assert "PRAGMA integrity_check" in migration
    assert "os.replace(database_staging, database)" in migration


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
    assert "FACTORTESTER_PUBLIC_CACHE_FROM" in activate
    assert "factortester-public:$old_revision" in activate
    assert activate.index(" backup") < activate.index("restart-app")
    assert activate.index("restart-app") < activate.index(" verify")
    assert "101.133.144.27" not in publish
    assert "/Users/maxdeux/.ssh" not in publish


def test_public_release_is_direct_push_driven_without_remote_git_fetch() -> None:
    publish = (
        ROOT / "scripts" / "server" / "publish_public_main.sh"
    ).read_text(encoding="utf-8")
    activate = (
        ROOT / "scripts" / "server" / "activate_public_revision.sh"
    ).read_text(encoding="utf-8")

    assert '"$remote:$remote_git_root/repo.git"' in publish
    assert 'main:refs/heads/main' in publish
    assert publish.index('"$remote:$remote_git_root/repo.git"') < publish.index(
        "remote_exec bash -s --",
    )
    assert "nohup" not in publish
    assert "install_public_auto_update" not in activate
    assert not (
        ROOT / "scripts" / "server" / "auto_update_public_main.sh"
    ).exists()
    assert not (
        ROOT / "scripts" / "server" / "install_public_auto_update.sh"
    ).exists()
    assert not (
        ROOT / "deploy" / "systemd" / "factortester-public-update.service.in"
    ).exists()
    assert not (
        ROOT / "deploy" / "systemd" / "factortester-public-update.timer"
    ).exists()


def test_legacy_push_entrypoint_delegates_to_synchronous_container_publish(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    server = scripts / "server"
    server.mkdir(parents=True)
    legacy = scripts / "push_main_to_server.sh"
    shutil.copy2(ROOT / "scripts" / legacy.name, legacy)
    publisher = server / "publish_public_main.sh"
    publisher.write_text(
        "#!/usr/bin/env bash\nprintf 'synchronous-publication\\n'\n",
        encoding="utf-8",
    )
    publisher.chmod(0o755)
    synchronizer = server / "sync_public_field_history.sh"
    synchronizer.write_text(
        "#!/usr/bin/env bash\nprintf 'field-history-synchronization\\n'\n",
        encoding="utf-8",
    )
    synchronizer.chmod(0o755)

    result = subprocess.run(
        [str(legacy), "--start"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == (
        "synchronous-publication\n"
        "field-history-synchronization\n"
    )
    assert result.stderr == ""


def test_field_history_sync_rotates_completed_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "field history"
    backup_dir.mkdir()
    paths = []
    for index in range(5):
        path = backup_dir / f"unifieddata-before-2026082{index}T000000Z.sqlite"
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (index, index))
        paths.append(path)

    result = subprocess.run(
        [
            str(ROOT / "scripts/server/prune_field_history_backups.sh"),
            str(backup_dir),
            "3",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "field_history_backups_retained=3 pruned=2\n"
    assert sorted(path.name for path in backup_dir.glob("*.sqlite")) == [
        path.name for path in paths[-3:]
    ]


def test_field_history_sync_declares_bounded_backup_retention() -> None:
    sync = (
        ROOT / "scripts/server/sync_public_field_history.sh"
    ).read_text(encoding="utf-8")

    assert "FACTORTESTER_FIELD_HISTORY_BACKUP_RETENTION:-3" in sync
    assert "/scripts/server/prune_field_history_backups.sh" in sync


def test_public_activation_staging_uses_deployer_writable_temp_directory() -> None:
    scripts = (ROOT / "scripts" / "server" / "publish_public_main.sh",)

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


def test_public_publish_refuses_without_authorization_before_transport(tmp_path: Path) -> None:
    script = ROOT / "scripts/server/publish_public_main.sh"
    env = dict(os.environ)
    env.pop("FACTORTESTER_PUBLISH_AUTHORIZED", None)
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 2
    assert "explicit release authorization is required" in result.stderr
    assert "Pushing" not in result.stdout
