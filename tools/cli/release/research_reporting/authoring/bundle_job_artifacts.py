"""Freeze full Job artifacts, including data omitted from table previews."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path
import re

from tools.cli.release.job_cache import (
    _cache_job_artifact_locked, cached_job_artifact, default_job_cache_root,
    job_cache_write_lock,
)

_URI = re.compile(r'factortester-artifact://jobs/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)')
_REF = re.compile(r'job-artifact:([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)')


def artifact_requests(snapshot):
    requests = {}
    def add(job, name, expected=''):
        if job in {".", ".."} or name in {".", ".."}:
            raise ValueError("Job artifact identity is invalid")
        key = (job, name)
        previous = requests.get(key, '')
        if previous and expected and previous != expected:
            raise ValueError('report references conflicting versions of one Job artifact')
        requests[key] = expected or previous
    def visit(value):
        if isinstance(value, dict):
            source = value.get('source')
            if isinstance(source, dict) and source.get('job_id') and source.get('artifact_ref'):
                match = _REF.fullmatch(source['artifact_ref'])
                if not match or match.group(1) != source['job_id']:
                    raise ValueError('table Job artifact identity is invalid')
                add(*match.groups(), source.get('content_hash', ''))
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, str):
            for match in _URI.finditer(value): add(*match.groups())
            if (match := _REF.fullmatch(value)) is not None: add(*match.groups())
    visit(snapshot.get('components', []))
    visit(snapshot.get('bindings', []))
    return requests


def export_job_artifacts(snapshot, capture, *, maximum_bytes):
    result = []
    for (job, name), expected in sorted(artifact_requests(snapshot).items()):
        cached = cached_job_artifact(job_id=job, name=name, expected_hash=expected, maximum_bytes=maximum_bytes)
        if cached is None:
            raise ValueError(f'full Job artifact is unavailable: {job}/{name}')
        result.append({'job_id': job, 'name': name, 'content_type': cached['content_type'],
                       **capture(cached['raw'], cached['file_name'])})
    return result


def restore_job_artifacts(items, files):
    # Acquire all affected Job locks in deterministic order before checking any
    # destination. Downloads use the same locks, so a successful preflight
    # cannot be invalidated by another client process before publication.
    jobs = sorted({item['job_id'] for item in items})
    with ExitStack() as locks:
        for job in jobs:
            locks.enter_context(job_cache_write_lock(job))
        _restore_job_artifacts_locked(items, files)


def _restore_job_artifacts_locked(items, files):
    # Check every collision first. A fork must not replace another local Job
    # version merely because it uses the same display name.
    destinations = {}
    already_present = set()
    for item in items:
        job, name, filename = item['job_id'], item['name'], item['filename']
        if (not _REF.fullmatch(f'job-artifact:{job}:{name}') or job in {'.', '..'} or name in {'.', '..'}
                or not isinstance(filename, str) or filename in {'', '.', '..'} or Path(filename).name != filename):
            raise ValueError('Job artifact destination is invalid')
        destination = default_job_cache_root() / job / filename
        if destination.parent.is_symlink() or destination.is_symlink():
            raise ValueError('Job artifact destination cannot be a symlink')
        previous = destinations.setdefault(destination, item['sha256'])
        if previous != item['sha256']:
            raise ValueError('Job artifacts conflict at one local filename')
        if destination.exists():
            if not destination.is_file():
                raise ValueError('Job artifact destination is not a file')
            with destination.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if digest != item['sha256']:
                raise ValueError('local Job artifact filename conflicts with imported content')
        cached = cached_job_artifact(job_id=item['job_id'], name=item['name'])
        if cached is not None and cached['content_hash'] != item['sha256']:
            raise ValueError('local Job artifact conflicts with the imported report version')
        if cached is not None:
            already_present.add((job, name))
    for item in items:
        if (item['job_id'], item['name']) in already_present:
            continue
        _cache_job_artifact_locked(job_id=item['job_id'], name=item['name'], filename=item['filename'],
                           content_type=item['content_type'], raw=files[item['sha256']], server_url='')
