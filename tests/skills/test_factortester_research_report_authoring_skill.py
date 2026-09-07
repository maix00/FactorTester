from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "skills/cli-anything-factortester-research/SKILL.md"
PACKAGED = (
    ROOT
    / "tools/cli/agent-harness/cli_anything/factortester_research/skills"
    / "SKILL.md"
)


def test_research_agent_skill_requires_explicit_special_section_labels() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "--kind special" in canonical
    assert "--display-kind grill_resolution" in canonical
    assert "--display-kind external_review" in canonical
    assert "智能体必须自己创建 special 容器" in canonical
    assert "`--kind special --display-kind grill_resolution`" in canonical
    assert "不能将该容器发布为普通" in canonical
    assert "显式指定真实 `--parent-id`" in canonical
    assert "--before-component-id" in canonical
    assert "--after-component-id" in canonical
    assert "CLI 写入最后一章" in canonical
    assert "current chapter or detour container" not in canonical


def test_research_agent_skill_uses_frozen_factor_references() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "factor-library factors --json" in canonical
    assert "client catalog factor" not in canonical
    assert "temporary_objects" in canonical
    assert "原子提交" in canonical
    assert "不能回退到另一个 commit" in canonical
    assert "factortester://factor/factor-family%3A" in canonical
    assert "factortester://factor_family/" not in canonical
    assert "不另建 Profile 因子集合 manifest" in canonical
    assert "只有 `self`" in canonical
    assert "workspace user download|upload" in canonical
    assert "先从数据库库刷新 `download`" in canonical
    assert "将 `download` 合入 `upload`" in canonical
    assert "将已提交的 `agent/<profile>` 合入 `upload`" in canonical
    assert "upload hook 同步数据库" in canonical
    assert "因子成员不能代表整个集合" in canonical
    assert "factortester://run_spec/runspec%3Asha256%3A" in canonical
    assert "factortester://trial_plan/trial-plan%3Asha256%3A" in canonical
    assert "research workspaces timeline" in canonical
    assert "research graphs cycle-object" in canonical
    assert "不在正文或行内代码裸露稳定 ref" in canonical
    assert "正文或行内代码" in canonical
    assert "40/64 位 hash" in canonical


def test_research_agent_skill_requires_frozen_report_identity_for_trial_jobs() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "智能体不能为 Run 手写或猜测它" in canonical
    assert "CLI 从报告 HEAD 读取 `report_id`" in canonical
    assert (
        "报告 HEAD、generation、root、hash 与 parent"
        in canonical
    )
    assert "`--without-report`" in canonical


def test_research_agent_skill_keeps_uploaded_inputs_with_the_job() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "--run-input [purpose=]path" in canonical
    assert "strategy_configuration=cost-model.yaml" in canonical
    assert "这些文件作为 Job 输入保留" in canonical
    assert "到用户清理" in canonical
    assert "普通 `.py` 附件是数据，不授予执行权限" in canonical


def test_research_agent_skill_keeps_work_package_method_memory() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "research-methods/SKILL.md" in canonical
    assert "research-methods/references/<method-slug>.md" in canonical
    assert "不全局注册、不复制进 Profile registry" in canonical
    assert "建议者" in canonical
    assert "说明当前理由与范围" in canonical
    assert "描述性相对 Markdown 链接" in canonical
    assert "方法记忆不是 Evidence" in canonical
