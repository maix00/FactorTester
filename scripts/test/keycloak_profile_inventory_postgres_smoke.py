"""Exercise Profile PostgreSQL inventory in a disposable, bounded container.

Uses an already installed postgres:17-alpine image; never downloads an image or
connects to an existing database. No credentials or Profile payloads are logged.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time

import psycopg

from scripts.migrations.keycloak_profile_inventory import build_inventory, read_postgres


def main():
    name, password = "tr-profile-inventory-" + secrets.token_hex(6), secrets.token_urlsafe(24)
    started = False
    try:
        try:
            subprocess.run(["docker", "run", "--detach", "--rm", "--pull=never", "--name", name,
                "--memory=256m", "--cpus=0.5", "-p", "127.0.0.1::5432",
                "-e", "POSTGRES_PASSWORD", "postgres:17-alpine"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                env={**os.environ, "POSTGRES_PASSWORD": password})
        except subprocess.CalledProcessError:
            raise RuntimeError("temporary PostgreSQL could not start") from None
        started = True
        address = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True).strip()
        port = int(address.rsplit(":", 1)[1])
        settings = {"host": "127.0.0.1", "port": port, "user": "postgres", "password": password,
                    "dbname": "postgres", "connect_timeout": 2}
        deadline = time.monotonic() + 45
        while True:
            try:
                writer = psycopg.connect(**settings)
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError("temporary PostgreSQL did not start") from None
                time.sleep(0.5)
        with writer:
            writer.execute("""CREATE TABLE control_profiles (
                principal text,profile_id text,payload jsonb,PRIMARY KEY(principal,profile_id))""")
            writer.execute("""CREATE TABLE control_account_domain_entities (
                principal text,entity_type text,entity_id text,payload jsonb,deleted boolean,
                origin_manager_id text,visibility text,authorized_users jsonb,
                PRIMARY KEY(principal,entity_type,entity_id))""")
            payload = {"profile_id": "work", "visibility": "private", "authorized_users": [],
                       "session_binding": {"principal_ref": "alice"},
                       "conversation": "SECRET-CONTENT-MUST-NOT-BE-EXPORTED"}
            writer.execute("INSERT INTO control_profiles VALUES (%s,%s,%s::jsonb)",
                           ("alice", "work", json.dumps(payload)))
            writer.execute("INSERT INTO control_profiles VALUES (%s,%s,%s::jsonb)",
                           ("bob", "other", json.dumps({"profile_id": "other"})))
            writer.execute("INSERT INTO control_account_domain_entities VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb)",
                           ("alice", "profile", "work", json.dumps(payload), False, "manager-a",
                            "authorized", json.dumps(["bob"])))
            writer.commit()

            class Cursor:
                def __init__(self, cursor, change): self.cursor, self.change = cursor, change
                def __enter__(self): self.cursor.__enter__(); return self
                def __exit__(self, *args): return self.cursor.__exit__(*args)
                def __getattr__(self, key): return getattr(self.cursor, key)
                def fetchmany(self, size):
                    result = self.cursor.fetchmany(size)
                    if result and self.change:
                        self.change = False
                        writer.execute("UPDATE control_account_domain_entities SET authorized_users=%s::jsonb",
                                       (json.dumps(["late"]),))
                        writer.commit()
                    return result

            with psycopg.connect(**settings) as reader:
                class ConcurrentReader:
                    def transaction(self): return reader.transaction()
                    def execute(self, query): return reader.execute(query)
                    def cursor(self, *, name): return Cursor(reader.cursor(name=name), name.endswith("0"))
                rows, snapshot = read_postgres(ConcurrentReader(), principals=["alice"])
            assert len(rows) == 3 and all(row["principal"] == "alice" for row in rows)
            envelope = next(row for row in rows if row["source"] == "postgres_account_acl")
            assert envelope["authorized_users"] == ["bob"]  # writer changed to late mid-scan
            assert writer.execute("SELECT authorized_users FROM control_account_domain_entities").fetchone()[0] == ["late"]
            assert "SECRET-CONTENT" not in json.dumps(rows)
            inventory = build_inventory(rows, manager_id="manager-a", pending=set(), conflicts=set(),
                sharing={}, referenced=set(), principals=["alice"], postgres_snapshot=snapshot)
            assert inventory["postgres_checked"] and not inventory["cross_source_atomic"]
            assert "projection_authorization_conflict" in inventory["objects"][0]["reasons"]
        print(json.dumps({"real_postgres": True, "repeatable_snapshot": True,
                          "principal_scoped": True, "payload_omitted": True,
                          "postgres_observations": len(rows), "cutover_ready": False}, sort_keys=True))
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


if __name__ == "__main__":
    main()
