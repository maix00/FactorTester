import hashlib
import json
from types import SimpleNamespace

import pytest

from tools.cli.release.research_reporting import local_sync_baseline as baseline


@pytest.fixture
def store(tmp_path):
    return SimpleNamespace(workspace_root=tmp_path)


@pytest.fixture
def receipt():
    return {'publication_id': 'p-' + 'a' * 64, 'revision': '1-a', 'generation': 2,
            'local_root_ref': 'nodes/root/abc.json'}


def test_baseline_is_bound_to_receipt_manager_and_report(store, receipt):
    manager = hashlib.sha256(b'manager-a').hexdigest()
    other_manager = hashlib.sha256(b'manager-b').hexdigest()
    baseline.write_baseline(store, report_id='report-a', manager_hash=manager,
                            receipt=receipt, content_sha256='c' * 64)
    assert baseline.read_baseline(store, report_id='report-a', manager_hash=manager, receipt=receipt) == 'c' * 64
    assert baseline.read_baseline(store, report_id='report-b', manager_hash=manager, receipt=receipt) is None
    assert baseline.read_baseline(store, report_id='report-a', manager_hash=other_manager, receipt=receipt) is None
    for changed in ({'revision': '2-b'}, {'local_root_ref': 'another'}, {'generation': 3},
                    {'publication_id': 'p-' + 'b' * 64}):
        assert baseline.read_baseline(store, report_id='report-a', manager_hash=manager,
                                      receipt={**receipt, **changed}) is None


def test_interrupted_baseline_write_keeps_prior_confirmed_value(store, receipt, monkeypatch):
    manager = hashlib.sha256(b'manager').hexdigest()
    baseline.write_baseline(store, report_id='report', manager_hash=manager,
                            receipt=receipt, content_sha256='c' * 64)
    def fail_replace(*_args):
        raise OSError('interrupted')
    monkeypatch.setattr(baseline.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='interrupted'):
        baseline.write_baseline(store, report_id='report', manager_hash=manager,
                                receipt=receipt, content_sha256='d' * 64)
    assert baseline.read_baseline(store, report_id='report', manager_hash=manager, receipt=receipt) == 'c' * 64
    assert not list((store.workspace_root / '.report-baselines').glob('.baseline-*'))


def test_invalid_or_symlink_baseline_is_never_used(store, receipt, tmp_path):
    manager = hashlib.sha256(b'manager').hexdigest()
    path = baseline._path(store, 'report', manager)
    path.parent.mkdir()
    path.write_text('{"unexpected":true}')
    assert baseline.read_baseline(store, report_id='report', manager_hash=manager, receipt=receipt) is None
    path.write_text(json.dumps({**receipt, 'generation': True, 'content_sha256': 'c' * 64}))
    assert baseline.read_baseline(store, report_id='report', manager_hash=manager,
                                  receipt={**receipt, 'generation': 1}) is None
    path.unlink()
    outside = tmp_path / 'outside'
    outside.write_text('preserve')
    path.symlink_to(outside)
    assert baseline.read_baseline(store, report_id='report', manager_hash=manager, receipt=receipt) is None
    with pytest.raises(ValueError, match='symbolic link'):
        baseline.write_baseline(store, report_id='report', manager_hash=manager,
                                receipt=receipt, content_sha256='c' * 64)
    assert outside.read_text() == 'preserve'
