from pathlib import Path

from openpyxl import Workbook, load_workbook

from tests.calc import test_2c_wps_compute as wps_compute


def _make_test2a_workbook(path: Path) -> None:
    wb = Workbook()
    main = wb.active
    main.title = 'MAIN'
    main.cell(2, 1, 'trade_time')
    main.cell(2, 24, 'adjustment_mul')
    main.cell(3, 24, 1.0)

    sw = wb.create_sheet('_SWITCHES')
    sw.cell(2, 1, 'trading_day')
    sw.cell(3, 1, '2026-01-01')
    sw.cell(4, 1, '2026-01-02')
    wb.save(path)
    wb.close()


def test_patch_flag_writes_pre_open_save_handshake_formulas(tmp_path):
    path = tmp_path / 'A.xlsx'
    _make_test2a_workbook(path)

    wps_compute.patch_flag(path, save_target=7)

    wb = load_workbook(path, data_only=False)
    sw = wb['_SWITCHES']
    assert sw['Z1'].value == '=IF(ISNUMBER(MAIN!X4),"DONE","CALC")'
    assert sw['Z2'].value == '=IF(Z1="DONE",7,0)'
    wb.close()


def test_wps_save_and_check_requires_saved_target_and_done(monkeypatch, tmp_path):
    path = tmp_path / 'A.xlsx'
    calls = {'n': 0}

    def fake_run(*args, **kwargs):
        return None

    def fake_z2(_path):
        calls['n'] += 1
        return 3 if calls['n'] >= 2 else 0

    monkeypatch.setattr(wps_compute.subprocess, 'run', fake_run)
    monkeypatch.setattr(wps_compute, 'read_z2', fake_z2)
    monkeypatch.setattr(wps_compute, 'read_z1', lambda _path: 'DONE')
    monkeypatch.setattr(wps_compute.time, 'sleep', lambda _seconds: None)

    assert wps_compute.wps_save_and_check(path, save_target=3, timeout=1) == (True, True)


def test_next_save_target_is_greater_than_cached_count(monkeypatch, tmp_path):
    path = tmp_path / 'A.xlsx'

    monkeypatch.setattr(wps_compute, 'read_z2', lambda _path: 10)
    monkeypatch.setattr(wps_compute.time, 'time', lambda: 5)

    assert wps_compute.next_save_target(path) == 11


def test_wps_save_and_check_rejects_saved_count_without_done(monkeypatch, tmp_path):
    path = tmp_path / 'A.xlsx'
    times = iter([0, 0.5, 1.5])

    monkeypatch.setattr(wps_compute.subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(wps_compute, 'read_z2', lambda _path: 3)
    monkeypatch.setattr(wps_compute, 'read_z1', lambda _path: 'CALC')
    monkeypatch.setattr(wps_compute.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(wps_compute.time, 'time', lambda: next(times))

    assert wps_compute.wps_save_and_check(path, save_target=3, timeout=1) == (True, False)


def test_wps_quit_confirms_closed_from_system_events(monkeypatch):
    class Result:
        stdout = 'closed\n'

    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(wps_compute.subprocess, 'run', fake_run)

    assert wps_compute.wps_quit(timeout=1) is True
    assert calls


def test_process_one_skips_already_done_workbook(monkeypatch, tmp_path):
    called = {'patch': False, 'open': False}
    path = tmp_path / 'A.xlsx'
    path.touch()

    monkeypatch.setattr(wps_compute, 'TEST_2A_DIR', tmp_path)
    monkeypatch.setattr(wps_compute, 'check_done', lambda _path: True)
    monkeypatch.setattr(wps_compute, 'read_z2', lambda _path: 42)

    def fake_patch(*args, **kwargs):
        called['patch'] = True

    def fake_open(*args, **kwargs):
        called['open'] = True

    monkeypatch.setattr(wps_compute, 'patch_flag', fake_patch)
    monkeypatch.setattr(wps_compute, 'wps_open', fake_open)

    assert wps_compute.process_one('A') is True
    assert called == {'patch': False, 'open': False}


def test_inspect_workbook_reports_done_status(tmp_path):
    path = tmp_path / 'A.xlsx'
    _make_test2a_workbook(path)

    wb = load_workbook(path)
    sw = wb['_SWITCHES']
    sw['Z1'] = 'DONE'
    sw['Z2'] = 9
    wb.save(path)
    wb.close()

    status = wps_compute.inspect_workbook(path)

    assert status.product == 'A'
    assert status.done is True
    assert status.z1 == 'DONE'
    assert status.z2 == 9
    assert wps_compute.status_ok(status)
