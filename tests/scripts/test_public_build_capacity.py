from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.server import public_build_capacity as capacity


class FakePath:
    def __init__(self, name, device):
        self.name, self.device = name, device

    def stat(self):
        return SimpleNamespace(st_dev=self.device)

    def __str__(self):
        return self.name


def test_same_disk_adds_only_unallocated_snapshot_and_build_budgets(monkeypatch):
    monkeypatch.setattr(capacity, "_existing", lambda path: FakePath(str(path), 1))
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda path: SimpleNamespace(free=19 * 1024**3))
    common = dict(root=Path("/"), docker_root=Path("/docker"), cache_root=Path("/cache"),
                  reserve_mib=10240, build_mib=5120)
    cold = capacity.capacity_plan(**common, snapshot_mib=2048)
    warm = capacity.capacity_plan(**common, snapshot_mib=0)
    assert len(cold) == 1 and cold[0]["required_mib"] == 17408 and cold[0]["free_mib"] == 19456
    assert warm[0]["required_mib"] == 15360
    assert capacity.capacity_plan(**common, snapshot_mib=2048, minimum_mib=20480)[0]["required_mib"] == 20480


def test_distinct_filesystems_keep_separate_reserves(monkeypatch):
    devices = {"/": 1, "/docker": 2, "/cache": 3}
    monkeypatch.setattr(capacity, "_existing", lambda path: FakePath(str(path), devices[str(path)]))
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda path: SimpleNamespace(free=30 * 1024**3))
    plan = capacity.capacity_plan(root=Path("/"), docker_root=Path("/docker"), cache_root=Path("/cache"),
                                  reserve_mib=10240, build_mib=5120, snapshot_mib=2048)
    assert {tuple(item["uses"]): item["required_mib"] for item in plan} == {
        ("host",): 10240, ("build",): 15360, ("snapshot",): 12288,
    }


def test_memory_headroom_is_enforced_without_counting_swap(tmp_path):
    info = tmp_path / "meminfo"
    info.write_text("MemAvailable: 1048576 kB\nSwapFree: 99999999 kB\n")
    with pytest.raises(RuntimeError, match="2048 MiB"):
        capacity.check_memory(info)
    info.write_text("MemAvailable: 3145728 kB\n")
    capacity.check_memory(info)
