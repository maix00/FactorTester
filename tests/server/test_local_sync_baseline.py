from types import SimpleNamespace
import os

from tools.cli.release.research_reporting.local_sync_baseline import (
    _path, content_check_due, mark_content_checked, write_baseline,
)


def test_content_check_schedule_does_not_touch_replaced_receipt(tmp_path):
    store = SimpleNamespace(workspace_root=tmp_path)
    manager = 'a' * 64
    receipt = {'publication_id': 'p-1', 'revision': '1-a', 'generation': 1, 'local_root_ref': 'root'}
    write_baseline(store, report_id='report', manager_hash=manager, receipt=receipt, content_sha256='b' * 64)
    path = _path(store, 'report', manager)
    assert not content_check_due(store, report_id='report', manager_hash=manager)
    os.utime(path, (1, 1))
    assert content_check_due(store, report_id='report', manager_hash=manager)
    newer = {**receipt, 'revision': '2-a'}
    write_baseline(store, report_id='report', manager_hash=manager, receipt=newer, content_sha256='c' * 64)
    os.utime(path, (1, 1))
    mark_content_checked(store, report_id='report', manager_hash=manager, receipt=receipt, content_sha256='b' * 64)
    assert content_check_due(store, report_id='report', manager_hash=manager)
    mark_content_checked(store, report_id='report', manager_hash=manager, receipt=newer, content_sha256='c' * 64)
    assert not content_check_due(store, report_id='report', manager_hash=manager)
