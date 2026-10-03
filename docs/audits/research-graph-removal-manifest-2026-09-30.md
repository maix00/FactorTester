# Research Graph 移除候选文件清单

- 基线：`9d35ee47f33cbc756103626a9a9eaeeb57631030`（`origin/feat`；首次扫描时远端 fetch 暂时失败，随后 Issue #403 的认领记录确认 fresh fetch 成功；集成前仍需重新 fetch）。
- 生成方式：对 Git 跟踪文件执行 `git grep -IlE "research_graph|Research Graph|graph_id|graph_instance|trial_plan|TrialPlan"`，排除 `static/vendor/**` 与 `*.lock`。
- 候选文件：435 个。此清单是移除审计的起点；实现时逐个判定 Graph 专属代码与仍须保留的普通研究功能，不能因命中关键字而机械删除。
- Ownership：仅允许删除 Graph 专属文件，或修改候选文件中直接耦合 Graph 的部分；若需要修改清单外文件，先审计依赖并更新 Issue #403 的 Ownership。

## 候选数量（按目录）

| 路径前缀 | 文件数 |
| --- | ---: |
| `server/services/research_graph` | 97 |
| `tools/cli/agent-harness` | 33 |
| `tools/cli/release` | 32 |
| `tools/cli/commands` | 25 |
| `docs/research-decision-graph/grill` | 8 |
| `server/modules/single_factor_test` | 8 |
| `apple/Sources/Features` | 7 |
| `server/manager/web` | 6 |
| `server/manager/http` | 5 |
| `skills/research-obligation-cycle/references` | 5 |
| `tests/server/research_step` | 5 |
| `server/services/research_step` | 4 |
| `apple/Sources/Networking` | 3 |
| `docs/research-decision-graph/acceptance` | 3 |
| `skills/research-obligation-cycle/scripts` | 3 |
| `tools/cli/manager` | 3 |
| `server/manager/storage` | 2 |
| `server/services/research_evidence_catalog` | 2 |
| `CONTEXT-MAP.md` | 1 |
| `CONTEXT.md` | 1 |
| `apple/Resources/Shared` | 1 |
| `apple/Tests/ClientTabSelectionTests.swift` | 1 |
| `apple/Tests/LocalProfileControllerTests.swift` | 1 |
| `apple/Tests/LocalResearchGraphStoreTests.swift` | 1 |
| `apple/Tests/ProfileResearchServiceTests.swift` | 1 |
| `apple/Tests/ResearchDocumentReferenceDetailsTests.swift` | 1 |
| `apple/Tests/ResearchGraphBrowserTests.swift` | 1 |
| `apple/Tests/ResearchGraphCompatibilityTests.swift` | 1 |
| `docs/adr/040-derived-research-reports.md` | 1 |
| `docs/adr/047-workspace-work-package-branch-boundaries.md` | 1 |
| `docs/adr/061-long-file-module-boundary-audit.md` | 1 |
| `docs/adr/084-research-graph-yaml-network-view.md` | 1 |
| `docs/adr/095-research-folder-boundary-audit.md` | 1 |
| `docs/research-decision-graph-grill-log.md` | 1 |
| `docs/research-decision-graph-plan.md` | 1 |
| `docs/research-decision-graph/CONTEXT.md` | 1 |
| `docs/research-decision-graph/capability-detour-entry-resolution-boundary.md` | 1 |
| `docs/research-decision-graph/research-obligation-cycle-work-package.md` | 1 |
| `scripts/research/migrate_obligation_titles.py` | 1 |
| `server/__init__.py` | 1 |
| `server/jobs/repository` | 1 |
| `server/jobs/scheduling` | 1 |
| `server/manager/runtime.py` | 1 |
| `server/manager/services` | 1 |
| `server/services/agent_execution` | 1 |
| `server/services/agent_flow` | 1 |
| `server/services/backend_assurance_migration.py` | 1 |
| `server/services/direct_trial_plan_registry.py` | 1 |
| `server/services/direct_trial_plans.py` | 1 |
| `server/services/research_configurations.py` | 1 |
| `server/services/research_evidence_registry.py` | 1 |
| `server/services/research_evidence_scope.py` | 1 |
| `server/services/research_graphs.py` | 1 |
| `server/services/research_report_presentations.py` | 1 |
| `server/services/research_run_inputs.py` | 1 |
| `server/services/research_run_projections.py` | 1 |
| `server/services/research_run_report_binding.py` | 1 |
| `server/services/research_run_schema.py` | 1 |
| `server/services/research_runs.py` | 1 |
| `skills/cli-anything-factortester-manager/SKILL.md` | 1 |
| `skills/cli-anything-factortester-research/SKILL.md` | 1 |
| `skills/research-obligation-cycle/SKILL.md` | 1 |
| `tests/_report_removal_support.py` | 1 |
| `tests/cli/test_advance_detour_checkpoint_parent.py` | 1 |
| `tests/cli/test_client_research_commands.py` | 1 |
| `tests/cli/test_client_research_fork.py` | 1 |
| `tests/cli/test_direct_trial_workflow.py` | 1 |
| `tests/cli/test_factortester_client.py` | 1 |
| `tests/cli/test_graph_chapter_reconciliation.py` | 1 |
| `tests/cli/test_local_graph_navigation.py` | 1 |
| `tests/cli/test_research_commands.py` | 1 |
| `tests/cli/test_research_cycle_object_command.py` | 1 |
| `tests/cli/test_research_graph_chapter_contract.py` | 1 |
| `tests/cli/test_research_graph_checkpoint_report_output.py` | 1 |
| `tests/cli/test_research_graph_continuation_active_detour.py` | 1 |
| `tests/cli/test_research_graph_continuation_parent.py` | 1 |
| `tests/cli/test_research_graph_detour_report.py` | 1 |
| `tests/cli/test_research_graph_local_report.py` | 1 |
| `tests/cli/test_research_graph_navigation.py` | 1 |
| `tests/cli/test_research_graph_transition_report_retry.py` | 1 |
| `tests/cli/test_research_report_entry_requirement_authority.py` | 1 |
| `tests/cli/test_research_report_entry_requirements.py` | 1 |
| `tests/cli/test_research_report_export.py` | 1 |
| `tests/cli/test_research_report_history_obligations.py` | 1 |
| `tests/cli/test_research_report_history_reconciliation.py` | 1 |
| `tests/cli/test_research_report_history_report_refs.py` | 1 |
| `tests/cli/test_research_report_system_display_guard.py` | 1 |
| `tests/release/report_tree_fixtures.py` | 1 |
| `tests/release/test_checkpoint_operations.py` | 1 |
| `tests/release/test_direct_report_reference_authority.py` | 1 |
| `tests/release/test_entry_resolution_report_events.py` | 1 |
| `tests/release/test_factor_subject_refs.py` | 1 |
| `tests/release/test_generic_research_report.py` | 1 |
| `tests/release/test_job_artifacts.py` | 1 |
| `tests/release/test_local_client_profile.py` | 1 |
| `tests/release/test_release_materialization.py` | 1 |
| `tests/release/test_report_batch_replace_cli.py` | 1 |
| `tests/release/test_report_reference_authority.py` | 1 |
| `tests/release/test_report_reference_preflight.py` | 1 |
| `tests/release/test_report_rich_text.py` | 1 |
| `tests/release/test_report_rich_text_migration.py` | 1 |
| `tests/release/test_report_submission_cli.py` | 1 |
| `tests/release/test_report_submission_latest_binding.py` | 1 |
| `tests/release/test_research_graph_local_report_projection.py` | 1 |
| `tests/release/test_research_obligation_context.py` | 1 |
| `tests/release/test_research_obligation_ledger.py` | 1 |
| `tests/scripts/fixtures` | 1 |
| `tests/scripts/test_research_graph_visualization_assets.py` | 1 |
| `tests/scripts/test_submit_report_binding_without_trial_plan.py` | 1 |
| `tests/scripts/test_worktree_manager_agent_gateway.py` | 1 |
| `tests/scripts/test_worktree_manager_client_app.py` | 1 |
| `tests/server/data_contract_fixtures.py` | 1 |
| `tests/server/fixtures` | 1 |
| `tests/server/test_active_graph_final_cutover.py` | 1 |
| `tests/server/test_agent_execution.py` | 1 |
| `tests/server/test_backend_assurance_migration.py` | 1 |
| `tests/server/test_capability_detour_continuation.py` | 1 |
| `tests/server/test_capability_detour_resume.py` | 1 |
| `tests/server/test_capability_detour_single_episode.py` | 1 |
| `tests/server/test_capability_detour_topology.py` | 1 |
| `tests/server/test_capability_detour_transition.py` | 1 |
| `tests/server/test_current_report_checkpoint.py` | 1 |
| `tests/server/test_data_availability_schema.py` | 1 |
| `tests/server/test_data_availability_snapshots.py` | 1 |
| `tests/server/test_data_contract_evidence.py` | 1 |
| `tests/server/test_data_obligation_requirements.py` | 1 |
| `tests/server/test_direct_trial_routes.py` | 1 |
| `tests/server/test_direct_trial_runs.py` | 1 |
| `tests/server/test_entry_requirement_gate.py` | 1 |
| `tests/server/test_entry_resolution_frame.py` | 1 |
| `tests/server/test_entry_resolution_module.py` | 1 |
| `tests/server/test_entry_resolution_stack.py` | 1 |
| `tests/server/test_factor_research_trial_sequence.py` | 1 |
| `tests/server/test_factor_revision_lineage.py` | 1 |
| `tests/server/test_factor_semantics_evidence.py` | 1 |
| `tests/server/test_graph_profile_handoff.py` | 1 |
| `tests/server/test_graph_requirement_preflight.py` | 1 |
| `tests/server/test_graph_topology_preflight.py` | 1 |
| `tests/server/test_graph_version_continuation.py` | 1 |
| `tests/server/test_job_attempt_evidence.py` | 1 |
| `tests/server/test_job_graph_evidence.py` | 1 |
| `tests/server/test_job_repository.py` | 1 |
| `tests/server/test_legacy_cycle_continuation.py` | 1 |
| `tests/server/test_manager_research_graph_catalog.py` | 1 |
| `tests/server/test_obligation_title_migration.py` | 1 |
| `tests/server/test_profile_research_projection.py` | 1 |
| `tests/server/test_profile_research_report_placement.py` | 1 |
| `tests/server/test_profile_research_timeline_budget.py` | 1 |
| `tests/server/test_public_client_access_policy.py` | 1 |
| `tests/server/test_report_binding_without_trial_plan.py` | 1 |
| `tests/server/test_research_cycle_checkpoint_deltas.py` | 1 |
| `tests/server/test_research_cycle_closure_semantics.py` | 1 |
| `tests/server/test_research_cycle_object_read.py` | 1 |
| `tests/server/test_research_cycle_reopening.py` | 1 |
| `tests/server/test_research_cycle_replay.py` | 1 |
| `tests/server/test_research_evidence_graph_admission.py` | 1 |
| `tests/server/test_research_evidence_registry.py` | 1 |
| `tests/server/test_research_graph_branch_migration.py` | 1 |
| `tests/server/test_research_graph_cold_trace.py` | 1 |
| `tests/server/test_research_graph_history_recovery.py` | 1 |
| `tests/server/test_research_graph_objects.py` | 1 |
| `tests/server/test_research_graph_presentations.py` | 1 |
| `tests/server/test_research_graph_protocol_v2.py` | 1 |
| `tests/server/test_research_graph_schema.py` | 1 |
| `tests/server/test_research_graph_user_library.py` | 1 |
| `tests/server/test_research_human_gate_override.py` | 1 |
| `tests/server/test_research_job_lifecycle.py` | 1 |
| `tests/server/test_research_obligation_coverage.py` | 1 |
| `tests/server/test_research_obligation_cycle_protocol.py` | 1 |
| `tests/server/test_research_report_coverage.py` | 1 |
| `tests/server/test_research_report_presentations.py` | 1 |
| `tests/server/test_research_run_report_binding.py` | 1 |
| `tests/server/test_run_sample_identity.py` | 1 |
| `tests/server/test_successor_research_graph.py` | 1 |
| `tests/server/test_trial_execution_checkpoint.py` | 1 |
| `tests/server/test_trial_execution_checkpoint_api.py` | 1 |
| `tests/server/test_trial_execution_checkpoint_store.py` | 1 |
| `tests/server/test_trial_plan_action_run_binding.py` | 1 |
| `tests/server/test_trial_plan_binding.py` | 1 |
| `tests/server/test_trial_plan_contract_v5.py` | 1 |
| `tests/server/test_trial_plan_evidence_admission.py` | 1 |
| `tests/server/test_trial_plan_revision.py` | 1 |
| `tests/server/test_trial_plan_stage_contract.py` | 1 |
| `tests/server/test_trial_plan_stage_exposure.py` | 1 |
| `tests/server/test_trial_plan_stage_run_boundary.py` | 1 |
| `tests/server/test_trial_plan_stage_schema.py` | 1 |
| `tests/server/test_trial_plan_v5_action_budget.py` | 1 |
| `tests/server/test_trial_plan_v5_shared_cohort.py` | 1 |
| `tests/server/test_trial_plan_v5_shared_cohort_db.py` | 1 |
| `tests/server/test_v8_v10_descendant_continuation.py` | 1 |
| `tests/server/trial_plan_fixtures.py` | 1 |
| `tests/skills/test_factortester_research_report_authoring_skill.py` | 1 |
| `tests/skills/test_research_obligation_cycle_skill.py` | 1 |
| `tools/cli/app.py` | 1 |
| `tools/cli/client.py` | 1 |
| `tools/cli/client_research.py` | 1 |
| `tools/cli/client_research_graph.py` | 1 |
| `tools/cli/docs` | 1 |
| `tools/cli/local_graph_navigation.py` | 1 |
| `tools/cli/modules` | 1 |
| `tools/migrations/finalize_active_graph_cutover.py` | 1 |
| `tools/migrations/recover_research_graph_history.py` | 1 |

## 实现期间发现的补充依赖

候选扫描之外，实际差异另有 142 条差异记录，共覆盖 147 个具体路径（相对上述 origin/feat 基线，含修改、新增、删除与重命名）。这些文件支撑 Graph-free 的导航/报告/证据/运行身份、客户端和容器打包、维护文档与回归测试；已逐项审阅并纳入 Issue #403 Ownership。Graph 专属目录内整文件删除仍按下方已授权目录范围处理。状态前缀为 Git 差异状态，重命名同时记录源和目标。

- `M` `.githooks/pre-commit`
- `M` `apple/Sources/Navigation/ClientTab.swift`
- `M` `apple/Sources/Navigation/ClientTabSession.swift`
- `M` `apple/Sources/Navigation/ClientTabView.swift`
- `M` `apple/Sources/Navigation/Module.swift`
- `D` `apple/Sources/Stores/ProfileLiveProcessController.swift`
- `D` `apple/Sources/Stores/ResearchGraphBrowserController.swift`
- `M` `apple/Tests/ClientTabSessionTests.swift`
- `D` `apple/Tests/ResearchBranchPickerTests.swift`
- `M` `apple/Tests/ResearchDocumentTextBlockTests.swift`
- `D` `apple/Tests/ResearchHumanGateOverrideServiceTests.swift`
- `M` `apple/Tests/ResearchReportExportRendererTests.swift`
- `M` `deploy/docker/factortester-public/factortester-entrypoint.sh`
- `M` `deploy/docker/factortester-server/compose.yaml`
- `M` `docs/adr/094-local-research-runtime-and-shared-report-sync.md`
- `M` `docs/adr/142-研究根对象与证据访问边界.md`
- `M` `docs/adr/148-product-definitions-and-submission-snapshots.md`
- `M` `docs/adr/149-research-catalog-replication.md`
- `M` `docs/adr/154-research-principal-and-branch-identity.md`
- `A` `docs/adr/156-retire-research-graph-agent-workflow.md`
- `M` `docs/adr/README.md`
- `M` `docs/agents/factortester-server-maintenance.md`
- `A` `docs/audits/factor-research-architecture-audit-2026-09-30.md`
- `A` `docs/audits/research-graph-removal-manifest-2026-09-30.md`
- `M` `docs/research-report-collaboration.md`
- `M` `product_docs/concepts/core-objects.md`
- `M` `product_docs/concepts/research-model.md`
- `M` `product_docs/guides/automation-and-cli.md`
- `M` `product_docs/guides/research-workflow.md`
- `M` `product_docs/implementation/research-reports.md`
- `M` `product_docs/implementation/system-overview.md`
- `M` `product_docs/implementation/web-swift-navigation.md`
- `M` `product_docs/manifest.json`
- `M` `product_docs/reference/api-cli-reference.md`
- `M` `scripts/build_and_run.sh`
- `M` `scripts/install_factortester_pipx.sh`
- `M` `scripts/migrate_sqlite_control_to_postgres.py`
- `M` `scripts/release/assets.py`
- `M` `scripts/release/embed_runtime.py`
- `M` `scripts/release/manifest.py`
- `M` `scripts/release/package_layout.py`
- `M` `scripts/release/publish.py`
- `M` `scripts/research/migrate_report_evidence_links.py`
- `M` `scripts/research/migrate_report_root_hierarchy.py`
- `R066` `scripts/research/migrate_work_package_report_identity.py → scripts/research/migrate_report_workspace_identity.py`
- `M` `scripts/server/factortester_public_container.sh`
- `M` `scripts/test.sh`
- `M` `server/manager/domain/navigation_registry.py`
- `M` `server/manager/domain/product_groups.py`
- `M` `server/manager/skills/catalog.json`
- `M` `server/manager/state/processes.py`
- `M` `server/modules/products/product_group_store.py`
- `M` `server/services/protocol_manifest.py`
- `A` `server/services/research_evidence_envelope.py`
- `R100` `server/services/research_graph/trial_plan/components.py → server/services/trial_plan/components.py`
- `R100` `server/services/research_graph/trial_plan/fields.py → server/services/trial_plan/fields.py`
- `R059` `server/services/research_graph/trial_plan/sample_identity.py → server/services/research_sample_identity.py`
- `A` `server/services/research_sample_exposure.py`
- `A` `server/services/trial_plan/__init__.py`
- `A` `server/services/trial_plan/binding.py`
- `A` `server/services/trial_plan/contract.py`
- `M` `server/skills/factortester-server-maintenance/SKILL.md`
- `D` `server/skills/factortester-server-maintenance/references/graph-governance.md`
- `M` `server/skills/factortester-server-maintenance/references/infrastructure.md`
- `A` `skills/factortester-research-skill/SKILL.md`
- `D` `skills/research-obligation-cycle/agents/openai.yaml`
- `M` `tests/cli/test_business_domain_commands.py`
- `M` `tests/cli/test_client_profile_sync.py`
- `M` `tests/cli/test_manager_commands.py`
- `M` `tests/cli/test_product_commands.py`
- `M` `tests/cli/test_protocol_negotiation.py`
- `M` `tests/cli/test_research_catalog_commands.py`
- `M` `tests/cli/test_research_evidence_commands.py`
- `D` `tests/cli/test_research_report_cycle_authority.py`
- `D` `tests/cli/test_research_report_graph_guard.py`
- `D` `tests/cli/test_research_report_history_cleanup.py`
- `D` `tests/cli/test_research_step_cli.py`
- `M` `tests/conftest.py`
- `M` `tests/js/test_report_export.js`
- `M` `tests/products/test_product_group_subjects.py`
- `M` `tests/release/test_beta_release_pipeline.py`
- `M` `tests/release/test_bundled_runtime_activation.py`
- `D` `tests/release/test_capability_detour_report_projection.py`
- `D` `tests/release/test_checkpoint_explicit_report_parent.py`
- `M` `tests/release/test_client_wheel.py`
- `D` `tests/release/test_compact_entry_resolution_carrier.py`
- `D` `tests/release/test_current_node_narrative.py`
- `D` `tests/release/test_graph_continuation_entry_event_hierarchy.py`
- `D` `tests/release/test_graph_continuation_report_hierarchy.py`
- `D` `tests/release/test_graph_node_chapter_identity.py`
- `D` `tests/release/test_graph_packet_commands.py`
- `D` `tests/release/test_harness_wheel.py`
- `M` `tests/release/test_macos_release_settings.py`
- `M` `tests/release/test_public_research_assets.py`
- `M` `tests/release/test_public_research_outbox.py`
- `M` `tests/release/test_release_builder.py`
- `M` `tests/release/test_report_batch_replace.py`
- `M` `tests/release/test_report_binding_migration.py`
- `M` `tests/release/test_report_collaboration_workflow.py`
- `M` `tests/release/test_report_copy_cli.py`
- `M` `tests/release/test_report_hierarchy_contract.py`
- `D` `tests/release/test_report_historical_section_wrap.py`
- `M` `tests/release/test_report_lineage_migration.py`
- `M` `tests/release/test_report_pending_git_exclusion.py`
- `M` `tests/release/test_report_pending_write_closure.py`
- `M` `tests/release/test_report_semantic_audit.py`
- `M` `tests/release/test_report_special_section_contract.py`
- `D` `tests/release/test_report_submission_descriptor_retry.py`
- `M` `tests/release/test_report_tree.py`
- `M` `tests/release/test_report_tree_bundle.py`
- `M` `tests/release/test_report_tree_copy.py`
- `M` `tests/release/test_research_workspace.py`
- `M` `tests/release/test_unified_client_publish.py`
- `R072` `tests/release/test_work_package_report_identity_migration.py → tests/release/test_report_workspace_identity_migration.py`
- `M` `tests/scripts/test_local_container_deployment.py`
- `M` `tests/scripts/test_public_container_deployment.py`
- `M` `tests/scripts/test_worktree_flask_manager.py`
- `M` `tests/scripts/test_worktree_manager_product_groups.py`
- `M` `tests/scripts/test_worktree_manager_public_data.py`
- `M` `tests/scripts/test_worktree_manager_web_manifest.py`
- `M` `tests/server/test_agent_skills.py`
- `M` `tests/server/test_maintenance_cases.py`
- `A` `tests/server/test_remove_research_graph_migration.py`
- `M` `tests/server/test_report_collaboration_http.py`
- `M` `tests/server/test_report_collaboration_peers.py`
- `M` `tests/server/test_research_evidence_catalog.py`
- `M` `tests/server/test_research_evidence_routes.py`
- `A` `tests/server/test_research_sample_exposure.py`
- `M` `tests/server/test_server_research.py`
- `M` `tests/server/test_server_research_collaboration.py`
- `M` `tests/server/test_server_research_routes.py`
- `M` `tests/skills/test_factortester_server_maintenance_skill.py`
- `M` `tools/cli/client_agent_flow.py`
- `M` `tools/cli/client_research_evidence.py`
- `D` `tools/cli/client_research_step.py`
- `D` `tools/cli/protocols/research_step.py`
- `M` `tools/cli/pyproject.toml`
- `D` `tools/cli/research_graph_entry_assessment.py`
- `D` `tools/cli/research_graph_submission_contract.py`
- `D` `tools/cli/research_graph_target_capabilities.py`
- `A` `tools/migrations/remove_research_graph.py`
- `M` `tools/testers/settings/applications.py`

## 跟踪文件

- `CONTEXT-MAP.md`
- `CONTEXT.md`
- `apple/Resources/Shared/Localizable.xcstrings`
- `apple/Sources/Features/Profiles/ResearchDisplayText.swift`
- `apple/Sources/Features/Profiles/ResearchGraph/LocalResearchGraphStore.swift`
- `apple/Sources/Features/Profiles/ResearchRecordModel.swift`
- `apple/Sources/Features/Profiles/ResearchReport/Document/ResearchDocumentReferenceCatalog.swift`
- `apple/Sources/Features/Profiles/ResearchReport/Document/ResearchDocumentReferenceDetails.swift`
- `apple/Sources/Features/Profiles/ResearchReport/Document/ResearchDocumentReferenceOverlay.swift`
- `apple/Sources/Features/Profiles/ResearchReport/References/ResearchRunSpecConfigurationView.swift`
- `apple/Sources/Networking/ProfileResearchProjectionModels.swift`
- `apple/Sources/Networking/ProfileResearchService.swift`
- `apple/Sources/Networking/ResearchGraphModels.swift`
- `apple/Tests/ClientTabSelectionTests.swift`
- `apple/Tests/LocalProfileControllerTests.swift`
- `apple/Tests/LocalResearchGraphStoreTests.swift`
- `apple/Tests/ProfileResearchServiceTests.swift`
- `apple/Tests/ResearchDocumentReferenceDetailsTests.swift`
- `apple/Tests/ResearchGraphBrowserTests.swift`
- `apple/Tests/ResearchGraphCompatibilityTests.swift`
- `docs/adr/040-derived-research-reports.md`
- `docs/adr/047-workspace-work-package-branch-boundaries.md`
- `docs/adr/061-long-file-module-boundary-audit.md`
- `docs/adr/084-research-graph-yaml-network-view.md`
- `docs/adr/095-research-folder-boundary-audit.md`
- `docs/research-decision-graph-grill-log.md`
- `docs/research-decision-graph-plan.md`
- `docs/research-decision-graph/CONTEXT.md`
- `docs/research-decision-graph/acceptance/batch6-real-factor-plan.json`
- `docs/research-decision-graph/acceptance/batch6_case_specs.py`
- `docs/research-decision-graph/acceptance/generate_batch6_live_artifacts.py`
- `docs/research-decision-graph/capability-detour-entry-resolution-boundary.md`
- `docs/research-decision-graph/grill/0073-0093.md`
- `docs/research-decision-graph/grill/0094-current.md`
- `docs/research-decision-graph/grill/0143-cognitive-obligation-cycle.md`
- `docs/research-decision-graph/grill/0144-job-evidence-readiness.md`
- `docs/research-decision-graph/grill/0177-factor-expression-parameterization.md`
- `docs/research-decision-graph/grill/0178-graph-version-governance.md`
- `docs/research-decision-graph/grill/0179-v8-obligation-report-map.md`
- `docs/research-decision-graph/grill/evidence-registry.md`
- `docs/research-decision-graph/research-obligation-cycle-work-package.md`
- `scripts/research/migrate_obligation_titles.py`
- `server/__init__.py`
- `server/jobs/repository/detail.py`
- `server/jobs/scheduling/daemon.py`
- `server/manager/http/catalog_routes.py`
- `server/manager/http/profile_research_routes.py`
- `server/manager/http/request_security.py`
- `server/manager/http/research_graph_catalog_routes.py`
- `server/manager/http/research_object_routes.py`
- `server/manager/runtime.py`
- `server/manager/services/research_graph_catalog.py`
- `server/manager/storage/identity_migration_common.py`
- `server/manager/storage/identity_migration_sqlite.py`
- `server/manager/web/app/webmcp.js`
- `server/manager/web/core/icons.js`
- `server/manager/web/jobs/detail.js`
- `server/manager/web/research/graph-list.js`
- `server/manager/web/research/graph.js`
- `server/manager/web/research/reference.js`
- `server/modules/single_factor_test/__init__.py`
- `server/modules/single_factor_test/backtest_job_support.py`
- `server/modules/single_factor_test/direct_trial_routes.py`
- `server/modules/single_factor_test/profile_research_routes.py`
- `server/modules/single_factor_test/research_graph_routes.py`
- `server/modules/single_factor_test/research_jobs.py`
- `server/modules/single_factor_test/research_step_routes.py`
- `server/modules/single_factor_test/trial_plan_revision_routes.py`
- `server/services/agent_execution/__init__.py`
- `server/services/agent_flow/resume.py`
- `server/services/backend_assurance_migration.py`
- `server/services/direct_trial_plan_registry.py`
- `server/services/direct_trial_plans.py`
- `server/services/research_configurations.py`
- `server/services/research_evidence_catalog/lifecycle.py`
- `server/services/research_evidence_catalog/validation.py`
- `server/services/research_evidence_registry.py`
- `server/services/research_evidence_scope.py`
- `server/services/research_graph/__init__.py`
- `server/services/research_graph/active_pointer.py`
- `server/services/research_graph/branch/__init__.py`
- `server/services/research_graph/branch/capability_detour/replay.py`
- `server/services/research_graph/branch/capability_detour/storage.py`
- `server/services/research_graph/branch/context.py`
- `server/services/research_graph/branch/continuation.py`
- `server/services/research_graph/branch/continuation_store.py`
- `server/services/research_graph/branch/cycle_objects.py`
- `server/services/research_graph/branch/data_contract.py`
- `server/services/research_graph/branch/entry_requirements.py`
- `server/services/research_graph/branch/entry_resolution/events.py`
- `server/services/research_graph/branch/entry_resolution/initial.py`
- `server/services/research_graph/branch/entry_resolution/projection.py`
- `server/services/research_graph/branch/factor_semantics.py`
- `server/services/research_graph/branch/guards.py`
- `server/services/research_graph/branch/handoff.py`
- `server/services/research_graph/branch/human_gate_override.py`
- `server/services/research_graph/branch/job_attempt.py`
- `server/services/research_graph/branch/legacy_cycle.py`
- `server/services/research_graph/branch/migration.py`
- `server/services/research_graph/branch/next_packet.py`
- `server/services/research_graph/branch/obligation_coverage.py`
- `server/services/research_graph/branch/projection.py`
- `server/services/research_graph/branch/repository.py`
- `server/services/research_graph/branch/requirement_read.py`
- `server/services/research_graph/branch/research_cycle.py`
- `server/services/research_graph/branch/runtime.py`
- `server/services/research_graph/branch/schema.py`
- `server/services/research_graph/branch/topology_preflight.py`
- `server/services/research_graph/branch/trace_compaction.py`
- `server/services/research_graph/branch/transition.py`
- `server/services/research_graph/branch/version_lineage.py`
- `server/services/research_graph/current_report_checkpoint.py`
- `server/services/research_graph/evidence_admission.py`
- `server/services/research_graph/graph_objects.py`
- `server/services/research_graph/history_recovery.py`
- `server/services/research_graph/obligation_title_migration/content.py`
- `server/services/research_graph/obligation_title_migration/database.py`
- `server/services/research_graph/presentation_contract.py`
- `server/services/research_graph/presentations.py`
- `server/services/research_graph/product_scope.py`
- `server/services/research_graph/profile_research_projection/branch.py`
- `server/services/research_graph/profile_research_projection/indexes.py`
- `server/services/research_graph/profile_research_projection/queries/checkpoint.py`
- `server/services/research_graph/profile_research_projection/queries/detail.py`
- `server/services/research_graph/profile_research_projection/queries/listing.py`
- `server/services/research_graph/profile_research_projection/queries/timeline.py`
- `server/services/research_graph/profile_research_projection/refs.py`
- `server/services/research_graph/profile_research_projection/service.py`
- `server/services/research_graph/profile_research_projection/summary.py`
- `server/services/research_graph/profile_research_projection/timeline.py`
- `server/services/research_graph/profile_research_projection/timeline_links.py`
- `server/services/research_graph/profile_research_projection/timeline_placement.py`
- `server/services/research_graph/profile_research_projection/tree.py`
- `server/services/research_graph/protocol.py`
- `server/services/research_graph/report_checkpoint.py`
- `server/services/research_graph/research_cycle/adjudication.py`
- `server/services/research_graph/research_cycle/closure.py`
- `server/services/research_graph/research_cycle/contracts.py`
- `server/services/research_graph/research_cycle/data_availability_evidence.py`
- `server/services/research_graph/research_cycle/events.py`
- `server/services/research_graph/research_cycle/evidence.py`
- `server/services/research_graph/research_cycle/factor_semantics_evidence.py`
- `server/services/research_graph/research_cycle/replay.py`
- `server/services/research_graph/research_cycle/run_spec_objects.py`
- `server/services/research_graph/research_cycle/trace_replay.py`
- `server/services/research_graph/schema.py`
- `server/services/research_graph/trial_plan/__init__.py`
- `server/services/research_graph/trial_plan/adjudication_receipts.py`
- `server/services/research_graph/trial_plan/binding.py`
- `server/services/research_graph/trial_plan/components.py`
- `server/services/research_graph/trial_plan/contract.py`
- `server/services/research_graph/trial_plan/evidence_actions.py`
- `server/services/research_graph/trial_plan/evidence_admission.py`
- `server/services/research_graph/trial_plan/evidence_reuse.py`
- `server/services/research_graph/trial_plan/execution_checkpoint.py`
- `server/services/research_graph/trial_plan/execution_checkpoint_api.py`
- `server/services/research_graph/trial_plan/execution_checkpoint_contract.py`
- `server/services/research_graph/trial_plan/execution_checkpoint_repository.py`
- `server/services/research_graph/trial_plan/execution_checkpoint_store.py`
- `server/services/research_graph/trial_plan/fields.py`
- `server/services/research_graph/trial_plan/result_audit.py`
- `server/services/research_graph/trial_plan/retention.py`
- `server/services/research_graph/trial_plan/revision.py`
- `server/services/research_graph/trial_plan/run_action_binding.py`
- `server/services/research_graph/trial_plan/sample_identity.py`
- `server/services/research_graph/trial_plan/stage_policy.py`
- `server/services/research_graph/trial_plan/stage_projection.py`
- `server/services/research_graph/trial_plan/transition.py`
- `server/services/research_graph/trial_plan/v5_contract.py`
- `server/services/research_graph/trial_plan/v5_design.py`
- `server/services/research_graph/user_graph_preferences.py`
- `server/services/research_graph/user_graphs.py`
- `server/services/research_graph/versions.py`
- `server/services/research_graph/work_packages.py`
- `server/services/research_graph/yaml_export.py`
- `server/services/research_graphs.py`
- `server/services/research_report_presentations.py`
- `server/services/research_run_inputs.py`
- `server/services/research_run_projections.py`
- `server/services/research_run_report_binding.py`
- `server/services/research_run_schema.py`
- `server/services/research_runs.py`
- `server/services/research_step/inspect.py`
- `server/services/research_step/result_reporting/presentations.py`
- `server/services/research_step/result_reporting/projection.py`
- `server/services/research_step/result_reporting/service.py`
- `skills/cli-anything-factortester-manager/SKILL.md`
- `skills/cli-anything-factortester-research/SKILL.md`
- `skills/research-obligation-cycle/SKILL.md`
- `skills/research-obligation-cycle/references/evidence-adjudication.md`
- `skills/research-obligation-cycle/references/market-context-event-search.md`
- `skills/research-obligation-cycle/references/obligation-discovery.md`
- `skills/research-obligation-cycle/references/search-exhaustion.md`
- `skills/research-obligation-cycle/references/trial-synthesis.md`
- `skills/research-obligation-cycle/scripts/_proposal_validation.py`
- `skills/research-obligation-cycle/scripts/_trial_synthesis_validation.py`
- `skills/research-obligation-cycle/scripts/validate-trial-synthesis.py`
- `tests/_report_removal_support.py`
- `tests/cli/test_advance_detour_checkpoint_parent.py`
- `tests/cli/test_client_research_commands.py`
- `tests/cli/test_client_research_fork.py`
- `tests/cli/test_direct_trial_workflow.py`
- `tests/cli/test_factortester_client.py`
- `tests/cli/test_graph_chapter_reconciliation.py`
- `tests/cli/test_local_graph_navigation.py`
- `tests/cli/test_research_commands.py`
- `tests/cli/test_research_cycle_object_command.py`
- `tests/cli/test_research_graph_chapter_contract.py`
- `tests/cli/test_research_graph_checkpoint_report_output.py`
- `tests/cli/test_research_graph_continuation_active_detour.py`
- `tests/cli/test_research_graph_continuation_parent.py`
- `tests/cli/test_research_graph_detour_report.py`
- `tests/cli/test_research_graph_local_report.py`
- `tests/cli/test_research_graph_navigation.py`
- `tests/cli/test_research_graph_transition_report_retry.py`
- `tests/cli/test_research_report_entry_requirement_authority.py`
- `tests/cli/test_research_report_entry_requirements.py`
- `tests/cli/test_research_report_export.py`
- `tests/cli/test_research_report_history_obligations.py`
- `tests/cli/test_research_report_history_reconciliation.py`
- `tests/cli/test_research_report_history_report_refs.py`
- `tests/cli/test_research_report_system_display_guard.py`
- `tests/release/report_tree_fixtures.py`
- `tests/release/test_checkpoint_operations.py`
- `tests/release/test_direct_report_reference_authority.py`
- `tests/release/test_entry_resolution_report_events.py`
- `tests/release/test_factor_subject_refs.py`
- `tests/release/test_generic_research_report.py`
- `tests/release/test_job_artifacts.py`
- `tests/release/test_local_client_profile.py`
- `tests/release/test_release_materialization.py`
- `tests/release/test_report_batch_replace_cli.py`
- `tests/release/test_report_reference_authority.py`
- `tests/release/test_report_reference_preflight.py`
- `tests/release/test_report_rich_text.py`
- `tests/release/test_report_rich_text_migration.py`
- `tests/release/test_report_submission_cli.py`
- `tests/release/test_report_submission_latest_binding.py`
- `tests/release/test_research_graph_local_report_projection.py`
- `tests/release/test_research_obligation_context.py`
- `tests/release/test_research_obligation_ledger.py`
- `tests/scripts/fixtures/reference_page.js`
- `tests/scripts/test_research_graph_visualization_assets.py`
- `tests/scripts/test_submit_report_binding_without_trial_plan.py`
- `tests/scripts/test_worktree_manager_agent_gateway.py`
- `tests/scripts/test_worktree_manager_client_app.py`
- `tests/server/data_contract_fixtures.py`
- `tests/server/fixtures/factor_research_trial_sequence.json`
- `tests/server/research_step/TEST.md`
- `tests/server/research_step/test_contracts.py`
- `tests/server/research_step/test_result_reporting_e2e.py`
- `tests/server/research_step/test_result_reporting_projection.py`
- `tests/server/research_step/test_routes.py`
- `tests/server/test_active_graph_final_cutover.py`
- `tests/server/test_agent_execution.py`
- `tests/server/test_backend_assurance_migration.py`
- `tests/server/test_capability_detour_continuation.py`
- `tests/server/test_capability_detour_resume.py`
- `tests/server/test_capability_detour_single_episode.py`
- `tests/server/test_capability_detour_topology.py`
- `tests/server/test_capability_detour_transition.py`
- `tests/server/test_current_report_checkpoint.py`
- `tests/server/test_data_availability_schema.py`
- `tests/server/test_data_availability_snapshots.py`
- `tests/server/test_data_contract_evidence.py`
- `tests/server/test_data_obligation_requirements.py`
- `tests/server/test_direct_trial_routes.py`
- `tests/server/test_direct_trial_runs.py`
- `tests/server/test_entry_requirement_gate.py`
- `tests/server/test_entry_resolution_frame.py`
- `tests/server/test_entry_resolution_module.py`
- `tests/server/test_entry_resolution_stack.py`
- `tests/server/test_factor_research_trial_sequence.py`
- `tests/server/test_factor_revision_lineage.py`
- `tests/server/test_factor_semantics_evidence.py`
- `tests/server/test_graph_profile_handoff.py`
- `tests/server/test_graph_requirement_preflight.py`
- `tests/server/test_graph_topology_preflight.py`
- `tests/server/test_graph_version_continuation.py`
- `tests/server/test_job_attempt_evidence.py`
- `tests/server/test_job_graph_evidence.py`
- `tests/server/test_job_repository.py`
- `tests/server/test_legacy_cycle_continuation.py`
- `tests/server/test_manager_research_graph_catalog.py`
- `tests/server/test_obligation_title_migration.py`
- `tests/server/test_profile_research_projection.py`
- `tests/server/test_profile_research_report_placement.py`
- `tests/server/test_profile_research_timeline_budget.py`
- `tests/server/test_public_client_access_policy.py`
- `tests/server/test_report_binding_without_trial_plan.py`
- `tests/server/test_research_cycle_checkpoint_deltas.py`
- `tests/server/test_research_cycle_closure_semantics.py`
- `tests/server/test_research_cycle_object_read.py`
- `tests/server/test_research_cycle_reopening.py`
- `tests/server/test_research_cycle_replay.py`
- `tests/server/test_research_evidence_graph_admission.py`
- `tests/server/test_research_evidence_registry.py`
- `tests/server/test_research_graph_branch_migration.py`
- `tests/server/test_research_graph_cold_trace.py`
- `tests/server/test_research_graph_history_recovery.py`
- `tests/server/test_research_graph_objects.py`
- `tests/server/test_research_graph_presentations.py`
- `tests/server/test_research_graph_protocol_v2.py`
- `tests/server/test_research_graph_schema.py`
- `tests/server/test_research_graph_user_library.py`
- `tests/server/test_research_human_gate_override.py`
- `tests/server/test_research_job_lifecycle.py`
- `tests/server/test_research_obligation_coverage.py`
- `tests/server/test_research_obligation_cycle_protocol.py`
- `tests/server/test_research_report_coverage.py`
- `tests/server/test_research_report_presentations.py`
- `tests/server/test_research_run_report_binding.py`
- `tests/server/test_run_sample_identity.py`
- `tests/server/test_successor_research_graph.py`
- `tests/server/test_trial_execution_checkpoint.py`
- `tests/server/test_trial_execution_checkpoint_api.py`
- `tests/server/test_trial_execution_checkpoint_store.py`
- `tests/server/test_trial_plan_action_run_binding.py`
- `tests/server/test_trial_plan_binding.py`
- `tests/server/test_trial_plan_contract_v5.py`
- `tests/server/test_trial_plan_evidence_admission.py`
- `tests/server/test_trial_plan_revision.py`
- `tests/server/test_trial_plan_stage_contract.py`
- `tests/server/test_trial_plan_stage_exposure.py`
- `tests/server/test_trial_plan_stage_run_boundary.py`
- `tests/server/test_trial_plan_stage_schema.py`
- `tests/server/test_trial_plan_v5_action_budget.py`
- `tests/server/test_trial_plan_v5_shared_cohort.py`
- `tests/server/test_trial_plan_v5_shared_cohort_db.py`
- `tests/server/test_v8_v10_descendant_continuation.py`
- `tests/server/trial_plan_fixtures.py`
- `tests/skills/test_factortester_research_report_authoring_skill.py`
- `tests/skills/test_research_obligation_cycle_skill.py`
- `tools/cli/agent-harness/FACTORTESTER_RESEARCH.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/README.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/commands/graph.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/commands/graph_successor.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/commands/research.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/draft_graph.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/draft_graph_cycle.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/draft_graph_edges.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/evidence.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/observed_graph.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/plan.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/replay.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/slices.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/submission_contract.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/successor_graph/builder.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/successor_graph/resolver_contracts.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/trial_plan_fixture.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/core/trial_plan_fixture_dag.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/resources/capabilities.v1.json`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/SKILL.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/SKILL.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/references/evidence-adjudication.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/references/market-context-event-search.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/references/obligation-discovery.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/references/search-exhaustion.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/references/trial-synthesis.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/scripts/_proposal_validation.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/scripts/_trial_synthesis_validation.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/skills/research-obligation-cycle/scripts/validate-trial-synthesis.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/TEST.md`
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_core.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_entry_preparation.py`
- `tools/cli/agent-harness/cli_anything/factortester_research/tests/test_submission_contract.py`
- `tools/cli/app.py`
- `tools/cli/client.py`
- `tools/cli/client_research.py`
- `tools/cli/client_research_graph.py`
- `tools/cli/commands/client_research.py`
- `tools/cli/commands/client_research_fork.py`
- `tools/cli/commands/client_research_fork_local.py`
- `tools/cli/commands/direct_trial.py`
- `tools/cli/commands/research.py`
- `tools/cli/commands/research_evidence_query.py`
- `tools/cli/commands/research_graph.py`
- `tools/cli/commands/research_graph_chapter_reconciliation.py`
- `tools/cli/commands/research_graph_continuation_parent.py`
- `tools/cli/commands/research_graph_continuation_report.py`
- `tools/cli/commands/research_graph_local_report_projection.py`
- `tools/cli/commands/research_graph_navigation.py`
- `tools/cli/commands/research_graph_node_advance.py`
- `tools/cli/commands/research_graph_obligation_advance.py`
- `tools/cli/commands/research_graph_obligations.py`
- `tools/cli/commands/research_graph_report_policy.py`
- `tools/cli/commands/research_graph_report_sync.py`
- `tools/cli/commands/research_graph_transition_report.py`
- `tools/cli/commands/research_report_graph_guard.py`
- `tools/cli/commands/research_report_history_apply.py`
- `tools/cli/commands/research_report_history_reconciliation.py`
- `tools/cli/commands/research_report_job_binding.py`
- `tools/cli/commands/research_report_scope_identity.py`
- `tools/cli/commands/research_result_report.py`
- `tools/cli/commands/research_step.py`
- `tools/cli/docs/factor-research-cli.md`
- `tools/cli/local_graph_navigation.py`
- `tools/cli/manager/client.py`
- `tools/cli/manager/factortester_commands.py`
- `tools/cli/manager/skills/SKILL.md`
- `tools/cli/modules/products/controller.py`
- `tools/cli/release/local_profile.py`
- `tools/cli/release/local_profile_contracts.py`
- `tools/cli/release/profile_research_create.py`
- `tools/cli/release/report_link_kinds.py`
- `tools/cli/release/research_identity_migration.py`
- `tools/cli/release/research_obligations/evidence_uses.py`
- `tools/cli/release/research_obligations/packet.py`
- `tools/cli/release/research_obligations/scope_revalidation.py`
- `tools/cli/release/research_reporting/assets.py`
- `tools/cli/release/research_reporting/authoring/checkpoint_operations.py`
- `tools/cli/release/research_reporting/collaboration.py`
- `tools/cli/release/research_reporting/continuation_narrative.py`
- `tools/cli/release/research_reporting/job_artifact_mounts.py`
- `tools/cli/release/research_reporting/maintenance/legacy_binding_kinds.py`
- `tools/cli/release/research_reporting/markdown.py`
- `tools/cli/release/research_reporting/node_titles.py`
- `tools/cli/release/research_reporting/public_research/attachments.py`
- `tools/cli/release/research_reporting/public_research/client.py`
- `tools/cli/release/research_reporting/public_research/projection.py`
- `tools/cli/release/research_reporting/publisher/carrier.py`
- `tools/cli/release/research_reporting/publisher/current_node_carrier.py`
- `tools/cli/release/research_reporting/publisher/current_node_history.py`
- `tools/cli/release/research_reporting/publisher/narrative.py`
- `tools/cli/release/research_reporting/publisher/service.py`
- `tools/cli/release/research_reporting/publisher/snapshot.py`
- `tools/cli/release/research_reporting/references/authority.py`
- `tools/cli/release/research_reporting/references/cycle_authority.py`
- `tools/cli/release/research_reporting/references/entry_requirements.py`
- `tools/cli/release/research_reporting/references/object_identity_validation.py`
- `tools/cli/release/research_reporting/report_space.py`
- `tools/cli/release/research_reporting/schema.py`
- `tools/cli/release/research_reporting/workspace_schema.py`
- `tools/migrations/finalize_active_graph_cutover.py`
- `tools/migrations/recover_research_graph_history.py`
