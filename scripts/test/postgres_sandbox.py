"""Disposable, resource-bounded PostgreSQL for isolated integration checks."""
from __future__ import annotations

import os
import secrets
import subprocess
import time
from contextlib import contextmanager

import psycopg


@contextmanager
def postgres_sandbox(prefix: str):
    name = prefix + '-' + secrets.token_hex(6)
    password = secrets.token_urlsafe(24)
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
        settings = {"host": "127.0.0.1", "port": int(address.rsplit(":", 1)[1]), "user": "postgres",
                    "password": password, "dbname": "postgres", "connect_timeout": 2}
        deadline = time.monotonic() + 45
        while True:
            try:
                with psycopg.connect(**settings):
                    break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError("temporary PostgreSQL did not start") from None
                time.sleep(0.5)
        yield settings
    finally:
        if started:
            subprocess.run(["docker", "rm", "-f", name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
