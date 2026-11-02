"""Disposable, bounded CouchDB used by isolated integration checks."""
from __future__ import annotations

import base64
import os
import secrets
import subprocess
import time
import urllib.request
from contextlib import contextmanager


@contextmanager
def couchdb_sandbox():
    name, password = 'tr-report-couch-' + secrets.token_hex(6), secrets.token_urlsafe(24)
    started = False
    try:
        try:
            subprocess.run(['docker', 'run', '--rm', '-d', '--pull=never', '--name', name,
                '--memory=512m', '--cpus=1', '-p', '127.0.0.1::5984',
                '-e', 'COUCHDB_USER', '-e', 'COUCHDB_PASSWORD', 'couchdb:3'],
                env={**os.environ, 'COUCHDB_USER': 'tr-test', 'COUCHDB_PASSWORD': password},
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            raise RuntimeError('isolated CouchDB could not start') from None
        started = True
        address = subprocess.check_output(['docker', 'port', name, '5984/tcp'], text=True).strip()
        base = 'http://127.0.0.1:' + address.rsplit(':', 1)[1]
        header = 'Basic ' + base64.b64encode(('tr-test:' + password).encode()).decode()
        deadline = time.monotonic() + 45
        while True:
            try:
                request = urllib.request.Request(base + '/_up', headers={'Authorization': header})
                with urllib.request.urlopen(request, timeout=2): pass
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('isolated CouchDB did not start') from None
                time.sleep(0.5)
        request = urllib.request.Request(base + '/shared_reports', method='PUT', headers={'Authorization': header})
        with urllib.request.urlopen(request, timeout=5): pass
        yield {'url': base, 'username': 'tr-test', 'password': password, 'database': 'shared_reports'}
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
