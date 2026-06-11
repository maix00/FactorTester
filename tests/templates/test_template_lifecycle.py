"""
测试模板的完整生命周期：保存 → 列表 → 加载单个 → 重命名(覆盖) → 删除
以及 applySnapshot 中的 testerId 重映射逻辑 (步骤 3.5)。
"""

from __future__ import annotations

import copy
import os
import tempfile

import pytest

from server.modules.templates.common import (
    SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
    load_template_list,
    new_template_id,
    save_template_list,
)
from server.services.user_storage import user_template_path
from server.modules.templates.summary import build_snapshot_summary


# ═══════════════════════════════════════════════════════════════════════════
# Helpers — 模拟前端 snapshot 数据结构
# ═══════════════════════════════════════════════════════════════════════════


def _make_minimal_snapshot(*, submissions=None, base_groups=None, name="测试模板"):
    """构造一个最小但合法的快照，用于测试保存/加载。"""
    snap = {
        "time_data": {
            "start_date": "2024-01-01",
            "start_time": "09:00",
            "end_date": "2024-12-31",
            "end_time": "15:00",
            "is_trading_day": False,
            "is_cn_futures_day": False,
            "is_cn_futures_night": False,
            "timezone": "Asia/Shanghai",
        },
        "params_list": [{"window": "20", "factor_type": "MmRet"}],
        "submissions": submissions or [],
        "return_freqs": [],
        "group_settings": {},
        "fee_modifications": [],
    }
    if base_groups is not None:
        snap["group_settings"] = {
            "baseGroups": base_groups,
            "derivedGraph": [],
            "lsConfigs": [],
            "registrations": [],
        }
    return snap


def _make_submission_item(sid: str, label: str = "", paths: list | None = None):
    """构造一个 snapshot.submissions 数组中的元素（模拟 collectSnapshot 输出）。"""
    p = paths or [f"/futures/{sid}"]
    return {
        "id": sid,
        "label": label or f"Tester-{sid}",
        "product_group": "",
        "paths": p,
        "selected_paths": p,
        "pathsDescMap": {},
        "factor_tester_name": f"Tester-{sid}",
        "factor_tester_serial": f"#{sid}",
        "product_count": len(p),
        "count_desc": f"{len(p)} 个产品",
        "timestamp": "",
        "start_date": "",
        "end_date": "",
        "start_time": "",
        "end_time": "",
    }


def _make_base_group(tester_id: str, name: str = "G1", factor_alias: str = "Return",
                     group_count: int = 5, group_index: int = 0):
    """构造一个 baseGroup（模拟 groupSettings snapshot 输出）。"""
    return {
        "id": f"bg-{tester_id}-{name}",
        "name": name,
        "testerId": tester_id,
        "factorAlias": factor_alias,
        "groupCount": group_count,
        "groupIndex": group_index,
        "isAllGroups": False,
        "feeMode": "none",
        "feeRate": None,
        "feeMap": None,
        "useCloseToday": False,
        "rebalanceMode": "each_period",
        "needsRegenerate": True,
        "startDate": None,
        "endDate": None,
    }


def test_snapshot_summary_reads_new_group_settings_shape():
    snapshot = _make_minimal_snapshot()
    snapshot["group_settings"] = {
        "groups": [
            _make_base_group("tester-1", "A1", group_index=1),
            {
                "id": "derived-1",
                "name": "A1:1",
                "parentId": "bg-tester-1-A1",
            },
        ],
        "lsConfigs": [
            {
                "id": "ls-1",
                "name": "A1/A5",
                "longGroupId": "bg-tester-1-A1",
                "shortGroupId": "bg-tester-1-A5",
            }
        ],
    }

    summary = build_snapshot_summary(snapshot)

    assert "group_test" in summary
    assert summary["group_test"][0] == "基础组 1 个 · 派生组 1 个 · Long-Short 1 个"
    assert any("A1" in item for item in summary["group_test"])


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_storage(monkeypatch):
    """重定向 user_template_path 到临时目录，避免污染真实用户数据。"""
    tmpdir = tempfile.mkdtemp(prefix="template_test_")

    def _fake_path(username, kind, ff_alias, scope_key=None):
        if scope_key:
            directory = os.path.join(tmpdir, f'{kind}_templates', scope_key)
        else:
            directory = os.path.join(tmpdir, f'{kind}_templates')
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, f'{kind}_templates.json')

    monkeypatch.setattr(
        "server.services.user_storage.user_template_path", _fake_path
    )

    yield tmpdir

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 测试 1: 保存模板 → 列表 → 获取单个 → 更新 → 删除 (存储层完整生命周期)
# ═══════════════════════════════════════════════════════════════════════════


class TestTemplateStorageLifecycle:
    """直接测试 user_storage 层的模板 JSON 读写（不经过 Flask 路由）。"""

    USER = "testuser"
    SCOPE = "MmRet"

    def test_roundtrip_save_and_load(self, tmp_storage):
        """保存模板，加载列表，数据应完全一致。"""
        templates = [
            {
                "id": new_template_id(),
                "name": "模板A",
                "ff_alias": self.SCOPE,
                "snapshot": _make_minimal_snapshot(
                    submissions=[_make_submission_item("s1", "品种X")]
                ),
            },
            {
                "id": new_template_id(),
                "name": "模板B",
                "ff_alias": self.SCOPE,
                "snapshot": _make_minimal_snapshot(
                    submissions=[_make_submission_item("s2", "品种Y")]
                ),
            },
        ]
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, templates,
                           scope_key=self.SCOPE)

        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        assert len(loaded) == 2
        assert loaded[0]["name"] == "模板A"
        assert loaded[0]["snapshot"]["submissions"][0]["id"] == "s1"
        assert loaded[1]["name"] == "模板B"

    def test_get_single_by_id(self, tmp_storage):
        """通过 id 查找单个模板。"""
        tpl = {
            "id": new_template_id(),
            "name": "完整快照模板",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(
                submissions=[_make_submission_item("t1", "品种A")],
                base_groups=[_make_base_group("t1", "G1")],
            ),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl],
                           scope_key=self.SCOPE)

        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        found = next((t for t in loaded if t["id"] == tpl["id"]), None)
        assert found is not None
        assert found["name"] == "完整快照模板"
        snap = found["snapshot"]
        assert snap["time_data"]["start_date"] == "2024-01-01"
        assert len(snap["submissions"]) == 1
        assert snap["group_settings"]["baseGroups"][0]["testerId"] == "t1"

    def test_rename_template(self, tmp_storage):
        """更新模板的 name 字段。"""
        tpl = {
            "id": new_template_id(),
            "name": "旧名称",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl],
                           scope_key=self.SCOPE)

        # 重命名
        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        loaded[0]["name"] = "新名称"
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, loaded,
                           scope_key=self.SCOPE)

        # 验证
        reloaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                      scope_key=self.SCOPE)
        assert reloaded[0]["name"] == "新名称"

    def test_overwrite_snapshot_preserves_name(self, tmp_storage):
        """覆盖 snapshot 时，name 不变。"""
        tpl = {
            "id": new_template_id(),
            "name": "可覆盖模板",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl],
                           scope_key=self.SCOPE)

        # 只覆盖 snapshot
        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        loaded[0]["snapshot"] = _make_minimal_snapshot(
            submissions=[_make_submission_item("new-sub", "新品种")],
        )
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, loaded,
                           scope_key=self.SCOPE)

        # 验证：名称不变，snapshot 已更新
        reloaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                      scope_key=self.SCOPE)
        assert reloaded[0]["name"] == "可覆盖模板"
        assert reloaded[0]["snapshot"]["submissions"][0]["label"] == "新品种"

    def test_delete_removes_from_list(self, tmp_storage):
        """删除模板后列表不包含该项。"""
        tpl_a = {
            "id": new_template_id(),
            "name": "模板A",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        tpl_b = {
            "id": new_template_id(),
            "name": "模板B",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                           [tpl_a, tpl_b], scope_key=self.SCOPE)

        # 删除 tpl_a
        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        filtered = [t for t in loaded if t["id"] != tpl_a["id"]]
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, filtered,
                           scope_key=self.SCOPE)

        # 验证只剩 tpl_b
        reloaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                      scope_key=self.SCOPE)
        assert len(reloaded) == 1
        assert reloaded[0]["id"] == tpl_b["id"]

    def test_delete_nonexistent_is_noop(self, tmp_storage):
        """删除不存在的 id 不报错，列表不变。"""
        tpl = {
            "id": new_template_id(),
            "name": "唯一模板",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl],
                           scope_key=self.SCOPE)

        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        filtered = [t for t in loaded if t["id"] != "does-not-exist"]
        # 长度应不变
        assert len(filtered) == 1

    def test_rename_to_empty_name_still_writes(self, tmp_storage):
        """空名称不会在存储层被拦截（前端已做校验）。"""
        tpl = {
            "id": new_template_id(),
            "name": "",
            "ff_alias": self.SCOPE,
            "snapshot": _make_minimal_snapshot(),
        }
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl],
                           scope_key=self.SCOPE)

        loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                    scope_key=self.SCOPE)
        assert loaded[0]["name"] == ""

    def test_multiple_scopes_isolated(self, tmp_storage):
        """不同 scope_key（ff_alias）的模板互不干扰。"""
        tpl_mm = {
            "id": new_template_id(),
            "name": "Mm模板",
            "ff_alias": "MmRet",
            "snapshot": _make_minimal_snapshot(),
        }
        tpl_vl = {
            "id": new_template_id(),
            "name": "Vl模板",
            "ff_alias": "VlRS",
            "snapshot": _make_minimal_snapshot(),
        }

        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl_mm],
                           scope_key="MmRet")
        save_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND, [tpl_vl],
                           scope_key="VlRS")

        mm_loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                       scope_key="MmRet")
        vl_loaded = load_template_list(self.USER, SINGLE_FACTOR_SETTING_TEMPLATE_KIND,
                                       scope_key="VlRS")

        assert len(mm_loaded) == 1
        assert mm_loaded[0]["name"] == "Mm模板"
        assert len(vl_loaded) == 1
        assert vl_loaded[0]["name"] == "Vl模板"


# ═══════════════════════════════════════════════════════════════════════════
# 测试 5: testerId 重映射逻辑 (步骤 3.5)
# ═══════════════════════════════════════════════════════════════════════════


class TestTesterIdRemapping:
    """测试 applySnapshot 中的 testerId 重映射逻辑。

    这是纯逻辑测试 —— 模拟前端 JS 中步骤 3.5 的行为，
    不依赖 Flask 服务器。
    """

    def _remap_tester_ids(self, snapshot, cur_submissions):
        """模拟 global_template_module.js 步骤 3.5 的逻辑。"""
        snap = copy.deepcopy(snapshot)

        if not (snap.get("group_settings", {}).get("baseGroups") and snap.get("submissions")):
            return snap

        # 构建 {旧testerId → 新testerId}：按位置 i 匹配
        old_to_new = {}
        for i in range(len(snap["submissions"])):
            old_id = snap["submissions"][i].get("id")
            new_id = cur_submissions[i].get("id") if i < len(cur_submissions) else None
            if old_id and new_id:
                old_to_new[str(old_id)] = str(new_id)

        # 替换 baseGroups 中的 testerId
        for bg in snap["group_settings"]["baseGroups"]:
            if bg.get("testerId") and str(bg["testerId"]) in old_to_new:
                bg["testerId"] = old_to_new[str(bg["testerId"])]

        # 同样处理 registrations
        for reg_entry in snap["group_settings"].get("registrations", []):
            if reg_entry.get("testerId") and str(reg_entry["testerId"]) in old_to_new:
                reg_entry["testerId"] = old_to_new[str(reg_entry["testerId"])]

        return snap

    def test_simple_remap_single_tester(self):
        """单个 tester：baseGroup 的旧 testerId 应被替换为新 testerId。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-id-1", "品种A")],
            base_groups=[_make_base_group("old-id-1", "G1")],
        )
        cur_submissions = [_make_submission_item("new-id-1", "品种A")]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        assert result["group_settings"]["baseGroups"][0]["testerId"] == "new-id-1"

    def test_remap_multiple_testers_preserves_order(self):
        """多个 tester：按位置一一对应，不交叉。"""
        snapshot = _make_minimal_snapshot(
            submissions=[
                _make_submission_item("old-A", "品种A"),
                _make_submission_item("old-B", "品种B"),
                _make_submission_item("old-C", "品种C"),
            ],
            base_groups=[
                _make_base_group("old-A", "G1"),
                _make_base_group("old-B", "G2"),
                _make_base_group("old-C", "G3"),
            ],
        )
        # 模拟重建：新 id 按同顺序
        cur_submissions = [
            _make_submission_item("new-A", "品种A"),
            _make_submission_item("new-B", "品种B"),
            _make_submission_item("new-C", "品种C"),
        ]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        bgs = result["group_settings"]["baseGroups"]
        assert bgs[0]["testerId"] == "new-A"
        assert bgs[1]["testerId"] == "new-B"
        assert bgs[2]["testerId"] == "new-C"

    def test_multiple_base_groups_same_tester(self):
        """同一个 tester 下有多个 baseGroup，全部应被替换。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-tester", "品种A")],
            base_groups=[
                _make_base_group("old-tester", "G1", group_index=0),
                _make_base_group("old-tester", "G2", group_index=1),
                _make_base_group("old-tester", "G3", group_index=2),
            ],
        )
        cur_submissions = [_make_submission_item("new-tester", "品种A")]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        for bg in result["group_settings"]["baseGroups"]:
            assert bg["testerId"] == "new-tester"

    def test_unmatched_tester_id_preserved(self):
        """旧 testerId 在新 submissions 中无对应位置时，保持原值。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-A", "品种A")],
            base_groups=[
                _make_base_group("old-A", "G1"),
                _make_base_group("orphan-id", "G2"),  # 无对应
            ],
        )
        cur_submissions = [_make_submission_item("new-A", "品种A")]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        assert result["group_settings"]["baseGroups"][0]["testerId"] == "new-A"
        # orphan-id 不在映射中，保持不变（实际场景中这表示模板数据有问题）
        assert result["group_settings"]["baseGroups"][1]["testerId"] == "orphan-id"

    def test_empty_submissions_no_crash(self):
        """空 submissions 时不应崩溃。"""
        snapshot = _make_minimal_snapshot(submissions=[])
        result = self._remap_tester_ids(snapshot, [])
        assert result["group_settings"] == {}

    def test_no_base_groups_no_crash(self):
        """无 baseGroups 时不应崩溃。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-A", "品种A")],
        )
        result = self._remap_tester_ids(
            snapshot, [_make_submission_item("new-A", "品种A")]
        )
        assert result["group_settings"] == {}

    def test_registrations_tester_id_also_remapped(self):
        """registrations 中的 testerId 也应被重映射。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-A", "品种A")],
            base_groups=[_make_base_group("old-A", "G1")],
        )
        snapshot["group_settings"]["registrations"] = [
            {"testerId": "old-A", "lsConfigId": "ls1", "registrations": []}
        ]
        cur_submissions = [_make_submission_item("new-A", "品种A")]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        assert result["group_settings"]["registrations"][0]["testerId"] == "new-A"

    def test_position_change_preserves_correct_mapping(self):
        """位置调换后，映射仍按位置一一对应（不是按 ID 匹配）。

        场景：用户保存前调换了 A 和 B 的顺序。
        快照中 submissions = [B, A]，baseGroups 的 testerId 也对应 B 和 A。
        重建后 cur_submissions = [B', A'] 按同顺序。
        """
        snapshot = _make_minimal_snapshot(
            submissions=[
                _make_submission_item("old-B", "品种B"),  # 位置 0
                _make_submission_item("old-A", "品种A"),  # 位置 1
            ],
            base_groups=[
                _make_base_group("old-B", "G-B"),
                _make_base_group("old-A", "G-A"),
            ],
        )
        # 重建后按同顺序
        cur_submissions = [
            _make_submission_item("new-B", "品种B"),
            _make_submission_item("new-A", "品种A"),
        ]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        # 位置 0: old-B → new-B
        assert result["group_settings"]["baseGroups"][0]["testerId"] == "new-B"
        # 位置 1: old-A → new-A
        assert result["group_settings"]["baseGroups"][1]["testerId"] == "new-A"

    def test_partial_overlap_tester_ids(self):
        """新 tester 数量多于旧 tester 时（比如用户添加了新 tester），多余的新 tester 不影响旧映射。"""
        snapshot = _make_minimal_snapshot(
            submissions=[
                _make_submission_item("old-A", "品种A"),
                _make_submission_item("old-B", "品种B"),
            ],
            base_groups=[
                _make_base_group("old-A", "G1"),
                _make_base_group("old-B", "G2"),
            ],
        )
        cur_submissions = [
            _make_submission_item("new-A", "品种A"),
            _make_submission_item("new-B", "品种B"),
            _make_submission_item("new-C", "品种C"),  # 多出来的
        ]

        result = self._remap_tester_ids(snapshot, cur_submissions)

        assert result["group_settings"]["baseGroups"][0]["testerId"] == "new-A"
        assert result["group_settings"]["baseGroups"][1]["testerId"] == "new-B"


# ═══════════════════════════════════════════════════════════════════════════
# 测试 6: 端到端 — 完整 applySnapshot 流程模拟
# ═══════════════════════════════════════════════════════════════════════════


class TestApplySnapshotFullFlow:
    """模拟完整的 applySnapshot 流程：清空 + 重建 + 重映射 + 应用。

    这是前端 JS applySnapshot 的 Python 等价模拟，用于验证
    「删掉所有现有的 → 按模板顺序重建新 tester → baseGroups 指向新 testerId」
    的流程。
    """

    def _simulate_apply_snapshot(self, snapshot):
        """模拟 applySnapshot 的步骤 1-5。

        步骤 1: 设置时间范围 (skip, 不需要)
        步骤 2: 恢复参数 (skip, 不需要)
        步骤 3: 清空 + 重建 tester (模拟：生成新 id)
        步骤 3.5: 重映射 testerId
        步骤 5: 应用 group_settings (模拟：直接用重映射后的数据)
        """
        snap = copy.deepcopy(snapshot)

        # ── 步骤 3: 清空所有旧 tester，按 snapshot.submissions 顺序重建 ──
        # 模拟前端：id_time = Date.now() + '-' + i
        import time
        ts = str(int(time.time() * 1000))

        new_submissions = []
        for i, old_sub in enumerate(snap.get("submissions", [])):
            new_id = f"{ts}-{i}"
            new_sub = copy.deepcopy(old_sub)
            new_sub["id"] = new_id
            new_sub["factor_tester_serial"] = f"#{new_id}"
            new_submissions.append(new_sub)

        # ── 步骤 3.5: 重映射 testerId ──
        old_to_new = {}
        for i in range(len(snap.get("submissions", []))):
            old_id = snap["submissions"][i].get("id")
            new_id = new_submissions[i].get("id") if i < len(new_submissions) else None
            if old_id and new_id:
                old_to_new[str(old_id)] = str(new_id)

        if snap.get("group_settings", {}).get("baseGroups"):
            for bg in snap["group_settings"]["baseGroups"]:
                if bg.get("testerId") and str(bg["testerId"]) in old_to_new:
                    bg["testerId"] = old_to_new[str(bg["testerId"])]

        if snap.get("group_settings", {}).get("registrations"):
            for reg_entry in snap["group_settings"]["registrations"]:
                if reg_entry.get("testerId") and str(reg_entry["testerId"]) in old_to_new:
                    reg_entry["testerId"] = old_to_new[str(reg_entry["testerId"])]

        # ── 步骤 5: 应用 group_settings ──
        # 验证 baseGroups 的 testerId 都指向新 submissions 中的有效 id
        valid_ids = {s["id"] for s in new_submissions}
        orphan_bgs = []
        for bg in snap.get("group_settings", {}).get("baseGroups", []):
            if bg.get("testerId") not in valid_ids:
                orphan_bgs.append(bg)

        return {
            "new_submissions": new_submissions,
            "group_settings": snap.get("group_settings", {}),
            "orphan_base_groups": orphan_bgs,
            "old_to_new_map": old_to_new,
        }

    def test_all_base_groups_point_to_new_testers(self):
        """完整流程后，所有 baseGroup 的 testerId 应指向新 tester。"""
        snapshot = _make_minimal_snapshot(
            submissions=[
                _make_submission_item("old-A", "品种A"),
                _make_submission_item("old-B", "品种B"),
            ],
            base_groups=[
                _make_base_group("old-A", "G-A1", group_index=0),
                _make_base_group("old-A", "G-A2", group_index=1),
                _make_base_group("old-B", "G-B1", group_index=0),
            ],
        )

        result = self._simulate_apply_snapshot(snapshot)

        # 无孤儿 baseGroup
        assert result["orphan_base_groups"] == []

        # 所有 testerId 都在新 submissions 中
        valid_ids = {s["id"] for s in result["new_submissions"]}
        for bg in result["group_settings"]["baseGroups"]:
            assert bg["testerId"] in valid_ids

        # 旧 id 不应再出现
        for bg in result["group_settings"]["baseGroups"]:
            assert bg["testerId"] not in ("old-A", "old-B")

    def test_without_remap_base_groups_are_orphans(self):
        """如果没有步骤 3.5，baseGroups 会引用不存在的旧 testerId。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("old-A", "品种A")],
            base_groups=[_make_base_group("old-A", "G1")],
        )

        # 模拟只做步骤 3（重建 tester）不做步骤 3.5
        import time
        ts = str(int(time.time() * 1000))
        new_id = f"{ts}-0"
        new_submissions = [{"id": new_id}]

        # baseGroups 的 testerId 还是 "old-A"
        bgs = snapshot["group_settings"]["baseGroups"]
        # 检查：如果没有重映射，"old-A" 不在有效 id 中
        valid_ids = {s["id"] for s in new_submissions}
        assert bgs[0]["testerId"] not in valid_ids
        # 这就是步骤 3.5 要解决的问题

    def test_simple_group_config_remapped_correctly(self):
        """简单场景：保存一个 tester + 一个 baseGroup，加载后正确重映射。"""
        snapshot = _make_minimal_snapshot(
            submissions=[_make_submission_item("saved-id-001", "测试品种")],
            base_groups=[_make_base_group("saved-id-001", "测试分组", factor_alias="Return", group_count=5)],
        )

        result = self._simulate_apply_snapshot(snapshot)

        bg = result["group_settings"]["baseGroups"][0]
        new_sub = result["new_submissions"][0]

        assert bg["testerId"] == new_sub["id"]
        assert bg["name"] == "测试分组"
        assert bg["factorAlias"] == "Return"
        assert bg["groupCount"] == 5
        # 其他字段未被篡改
        assert bg["feeMode"] == "none"
        assert bg["rebalanceMode"] == "each_period"
