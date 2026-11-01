import os
import stat
from types import SimpleNamespace

import pytest

from tools.cli.release.bounded_file import read_bounded_file


def test_file_limit_rejects_oversized_and_accepts_exact_size(tmp_path):
    path = tmp_path / 'resource'
    path.write_bytes(b'1234')
    assert read_bounded_file(path, 4) == b'1234'
    with pytest.raises(ValueError, match='size limit'):
        read_bounded_file(path, 3)


def test_file_limit_also_detects_growth_after_stat(tmp_path, monkeypatch):
    path = tmp_path / 'growing'
    path.write_bytes(b'12345')
    monkeypatch.setattr(os, 'fstat', lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=2))
    with pytest.raises(ValueError, match='size limit'):
        read_bounded_file(path, 4)


def test_job_cache_returns_the_bytes_it_verified_and_can_limit_reads(tmp_path, monkeypatch):
    from tools.cli.release import job_cache
    monkeypatch.setenv('TRADERESEARCH_JOB_CACHE_ROOT', str(tmp_path))
    job_cache.cache_job_artifact(job_id='job-1', name='evidence', filename='evidence.txt',
        content_type='text/plain', raw=b'abc', server_url='https://manager.test')
    monkeypatch.setattr(job_cache, '_digest_path', lambda _path: (_ for _ in ()).throw(AssertionError('second read')))
    assert job_cache.cached_job_artifact(job_id='job-1', name='evidence', maximum_bytes=3)['raw'] == b'abc'
    with pytest.raises(ValueError, match='size limit'):
        job_cache.cached_job_artifact(job_id='job-1', name='evidence', maximum_bytes=2)


def test_report_bundle_rejects_oversized_asset_before_materializing_it(tmp_path):
    from tests.release.test_report_tree_bundle import _source
    from tools.cli.release.research_reporting.authoring.tree_bundle import MAX_BUNDLE_BYTES, export_report_bundle
    source, head = _source(tmp_path)
    with (source / 'assets/plot.png').open('wb') as file:
        file.truncate(MAX_BUNDLE_BYTES + 1)
    with pytest.raises(ValueError, match='size limit'):
        export_report_bundle(package_root=source, branch_id='main',
            expected_generation=head['generation'], expected_root_ref=head['root_ref'])
