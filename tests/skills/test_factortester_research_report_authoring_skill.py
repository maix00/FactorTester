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
    assert "the Agent must create" in canonical
    assert "the container itself with `--kind special`" in canonical
    assert "Do not publish that container as an ordinary" in canonical
    assert "must name its actual `--parent-id`" in canonical
    assert "--before-component-id" in canonical
    assert "--after-component-id" in canonical
    assert "tree's last chapter" in canonical
    assert "current chapter or detour container" not in canonical


def test_research_agent_skill_uses_frozen_factor_references() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "factor-library profile reference" in canonical
    assert "client catalog factor" not in canonical
    assert "--source-file '<custom_factors-or-public_factors>/<family>.py'" in canonical
    assert "--revision <commit>" in canonical
    assert "--identity '<complete-factor-alias>'" in canonical
    assert "Use the returned `target_ref`" in canonical
    assert "Do not fall back to an older commit" in canonical
    assert "factortester://factor/factor-family%3A" in canonical
    assert "factortester://factor_family/" not in canonical
    assert "factor-library profile factor-set create" in canonical
    assert "factor-library profile factor-set reference" in canonical
    assert "factor-set sync" in canonical
    assert "factor-set registered" in canonical
    assert "factor-set unsync" in canonical
    assert "refresh `download` from the database factor library" in canonical
    assert "merge `download` into `upload`" in canonical
    assert "merge the committed `agent/<profile>` branch into `upload`" in canonical
    assert "upload` hook to synchronize back" in canonical
    assert "A member factor never implies coverage of the whole set" in canonical
    assert "factortester://run_spec/runspec%3Asha256%3A" in canonical
    assert "factortester://trial_plan/trial-plan%3Asha256%3A" in canonical
    assert "research workspaces timeline" in canonical
    assert "research graphs cycle-object" in canonical
    assert "Never expose an Evidence, Job, RunSpec, TrialPlan" in canonical
    assert "ordinary prose or inline" in canonical
    assert "40/64-character" in canonical


def test_research_agent_skill_requires_frozen_report_identity_for_trial_jobs() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "does not invent or pass `report_id`" in canonical
    assert "reads `report_id` from the current branch report HEAD" in canonical
    assert (
        "report generation, root reference, HEAD hash, and parent ID"
        in canonical
    )
    assert "`--without-report`" in canonical


def test_research_agent_skill_keeps_uploaded_inputs_with_the_job() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "--run-input [purpose=]path" in canonical
    assert "strategy_configuration=cost-model.yaml" in canonical
    assert "retained beside generated Job artifacts" in canonical
    assert "until the user clears the Job files" in canonical
    assert "generic\n  `.py` dependency is data, not executable authority" in canonical


def test_research_agent_skill_keeps_work_package_method_memory() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")

    assert PACKAGED.read_text(encoding="utf-8") == canonical
    assert "research-methods/SKILL.md" in canonical
    assert "research-methods/references/<method-slug>.md" in canonical
    assert "Do not register this Work Package-local Skill globally" in canonical
    assert "who recommended it" in canonical
    assert "why it applies to the current research decision" in canonical
    assert "ordinary relative Markdown link" in canonical
    assert "The method file is rationale memory, not primary Evidence" in canonical
