# 架构决策记录

本目录记录 FactorTester 的架构决策。ADR 是当前实现的可审计说明，不是脱离源码
长期维护的愿望清单；每次架构迁移都必须同时说明已落地边界、尚未迁移的遗留和验收条件。

## 编号与文件

- 每条 ADR 使用唯一的三位数字前缀，文件名为 `<编号>-<短名称>.md`。
- 文件重命名或编号迁移不改变历史决策。迁移后的文件必须在正文开头保留“编号迁移说明”，
  写明旧文件名、冲突原因和新的编号。
- 被后续决策取代的 ADR 不删除；在状态中标记“已被 ADR-xxx 取代”，并保留历史背景，避免
  把已废弃实现误当成当前规范。
- 标题、章节和说明使用中文；代码符号、API 路径、CLI 命令、类名和文件名保留原文，以便
  与源码和检索结果逐字对应。

## 状态写法

- **已接受**：当前实现遵循该决策，或决策是仍有效的约束。
- **部分实施，存在代码偏离**：目标已确定，但源码仍有明确遗留；必须列出遗留位置和迁移条件。
- **分阶段迁移**：新旧边界同时存在，必须说明当前 canonical 路径和允许保留的过渡面。
- **已被取代**：后续 ADR 已成为当前规范；本文只作为历史记录，不得继续指导新代码。
- **草案**：只有在确实尚未接受且没有当前实现约束时使用；已被取代的计划不能继续标为“草案未开始”。

## 按主题索引

本文件只登记主题和 ADR，不重复维护 API、CLI、目录或实现状态。编号迁移原因只记在迁移后 ADR 的正文中，
不在这里重复。

| 主题 | 正在施行的 ADR | 已废弃/被取代的 ADR |
| --- | --- | --- |
| 因子表达式、参数、执行和身份 | [ADR-001](001-expression-tree-factor-engine.md)、[ADR-002](002-factor-getattr-proxy.md)、[ADR-004](004-vectorized-parameter-batch.md)、[ADR-005](005-intermediate-neg-and-storage.md)、[ADR-010](010-factor-ir-cross-framework.md)、[ADR-015](015-explicit-factor-author-sdk.md)、[ADR-022](022-factor-execution-backends.md)、[ADR-048](048-frozen-factor-identity.md)、[ADR-052](052-legacy-live-factor-lookback-buffer.md)、[ADR-053](053-native-runtime-hotpath-caches.md)、[ADR-118](118-factor-ref-runspec-v3.md) | — |
| 产品、数据源、分类和产品范围 | [ADR-006](006-product-group-explicit-exclusions.md)、[ADR-007](007-session-aware-window-semantics.md)、[ADR-012](012-data-source-driven-product-catalog.md)、[ADR-014](014-observed-futures-sessions-and-pipeline.md)、[ADR-016](016-provider-scoped-derived-market-artifacts.md)、[ADR-017](017-product-classification-and-series-variants.md)、[ADR-025](025-product-path-selection-boundaries.md)、[ADR-049](049-device-local-market-data-source-boundary.md)、[ADR-085](085-explicit-product-category-bindings.md)、[ADR-116](116-canonical-shared-product-scope.md)、[ADR-131](131-client-local-catalog-and-binding-snapshots.md) | — |
| 测试 authoring、回测、订单、账本和运行生命周期 | [ADR-003](003-open-to-open-return-alignment.md)、[ADR-008](008-test-result-lifecycle-and-idle-eviction.md)、[ADR-009](009-page-scoped-submission-runtime-state.md)、[ADR-013](013-row-based-lazy-template-storage.md)、[ADR-018](018-causal-event-runtime.md)、[ADR-019](019-group-test-strategy-semantics.md)、[ADR-020](020-liquidity-execution-semantics.md)、[ADR-021](021-fee-calculation-and-journal.md)、[ADR-023](023-rebalance-allocation-data-quality-and-evaluation-ranges.md)、[ADR-024](024-backtest-module-ownership-and-rqalpha-adapter.md)、[ADR-026](026-native-run-state-and-flow-context-boundaries.md)、[ADR-027](027-order-flow-ledger-and-snapshot-boundary.md)、[ADR-029](029-native-flow-order-and-run-state-naming-audit.md)、[ADR-030](030-framework-execution-bridge.md)、[ADR-031](031-order-sizing-pipeline-and-settlement-notices.md)、[ADR-032](032-strategy-book-and-counterparty-boundary.md)、[ADR-033](033-native-run-state-config-cash-pool-boundaries.md)、[ADR-034](034-flow-definition-binding-and-explicit-order-settlement.md)、[ADR-035](035-strategy-book-policy-slots.md)、[ADR-037](037-research-run-job-persistence-boundary.md)、[ADR-038](038-single-host-research-scheduler-and-data-affinity.md)、[ADR-039](039-research-result-artifacts-and-user-quotas.md)、[ADR-041](041-strategy-intent-policy-and-selection-tools.md)、[ADR-042](042-margin-budget-and-buying-power-hooks.md)、[ADR-043](043-exchange-style-close-open-order-lifecycle.md)、[ADR-044](044-native-strategy-hooks-and-market-event-kinds.md)、[ADR-045](045-strategy-spec-actor-and-cli-boundary.md)、[ADR-046](046-factor-gate-and-stateful-policy-gaps.md)、[ADR-050](050-causal-bar-visibility-contract.md)、[ADR-051](051-composite-lookback-and-incremental-kernels.md)、[ADR-055](055-native-performance-audit-2026-08-11.md)、[ADR-108](108-test-workbench-run-observability.md)、[ADR-109](109-multi-select-draft-commit-and-run-panel-empty-state.md)、[ADR-110](110-nested-strategy-editor-scope.md)、[ADR-120](120-job-result-tabs-and-test-domain-results.md)、[ADR-121](121-backtest-result-surfaces-and-lazy-analysis.md)、[ADR-129](129-external-precomputed-factor-artifacts.md)、[ADR-132](132-test-workbench-and-job-detail-boundary.md)、[ADR-133](133-typed-ic-core-matrix-and-analysis-graph.md) | [ADR-028](028-native-broker-policy-boundary.md)、[ADR-036](036-durable-research-job-lifecycle.md)、[ADR-127](127-backtest-pipeline-hooks.md)、[ADR-128](128-native-broker-policy-implementation-plan.md) |
| 策略库、策略源码与配置内临时策略 | [ADR-143](143-策略库与配置内临时策略.md) | — |
| Manager、联邦、网络和对象传输 | [ADR-054](054-registry-and-client-asset-boundary.md)、[ADR-056](056-federated-manager-routing.md)、[ADR-057](057-artifact-data-plane.md)、[ADR-058](058-manager-control-event-sync.md)、[ADR-059](059-manager-server-module-boundaries.md)、[ADR-061](061-long-file-module-boundary-audit.md)、[ADR-062](062-public-manager-http-and-certificate-boundary.md)、[ADR-063](063-server-federation-and-control-database-settings.md)、[ADR-064](064-control-database-requires-utf8.md)、[ADR-066](066-containerized-server-runtime.md)、[ADR-068](068-wireguard-direct-transfer-surfaces.md)、[ADR-069](069-public-two-container-cutover.md)、[ADR-070](070-federation-bootstrap-and-wireguard-key-governance.md)、[ADR-071](071-manager-frozen-federated-run-context.md)、[ADR-072](072-public-ngrok-ingress.md)、[ADR-073](073-public-visitor-entry-origin.md)、[ADR-074](074-public-network-and-visitor-catalog-visibility.md)、[ADR-077](077-ngrok-canonical-ip-device-entry.md)、[ADR-078](078-federated-public-data-projections.md)、[ADR-079](079-profile-projection-offline-cache.md)、[ADR-080](080-offline-login-uses-existing-local-sqlite.md)、[ADR-081](081-manager-session-sqlite-lifecycle.md)、[ADR-082](082-profile-control-projection-sync.md)、[ADR-087](087-account-domain-sync.md)、[ADR-089](089-object-data-plane-adapters.md)、[ADR-092](092-transfer-telemetry.md)、[ADR-097](097-native-client-visitor-entry-policy.md)、[ADR-102](102-bounded-public-visitor-login.md)、[ADR-103](103-public-visitor-access-control.md)、[ADR-111](111-dynamic-host-lan-heartbeat.md)、[ADR-136](136-server-owned-management-access.md) | [ADR-060](060-one-time-public-device-authorization.md)、[ADR-065](065-federated-artifact-endpoint.md)、[ADR-067](067-federated-transfer-control-and-data-plane.md)、[ADR-075](075-public-device-origin-session-handoff.md)、[ADR-076](076-public-device-session-origin-binding.md) |
| 研究、报告分支、Agent WorkflowRun、客户端和本地缓存 | [ADR-040](040-derived-research-reports.md)、[ADR-047](047-workspace-work-package-branch-boundaries.md)、[ADR-083](083-unified-backend-navigation.md)、[ADR-086](086-swift-client-web-shell.md)、[ADR-088](088-client-build-and-public-manager-selection.md)、[ADR-090](090-client-manager-bootstrap-and-network-preference.md)、[ADR-091](091-swift-bootstrap-fallback-and-research-object-data-plane.md)、[ADR-093](093-cli-skill-boundary-split.md)、[ADR-094](094-local-research-runtime-and-shared-report-sync.md)、[ADR-095](095-research-folder-boundary-audit.md)、[ADR-098](098-app-managed-cli-environment.md)、[ADR-099](099-tab-local-view-cache.md)、[ADR-100](100-client-local-run-boundary.md)、[ADR-101](101-local-docker-lifecycle.md)、[ADR-117](117-direct-parent-agent-history-access.md)、[ADR-122](122-multicurrency-account-and-cash-pool-valuation.md)、[ADR-123](123-client-profile-connection-boundary.md)、[ADR-130](130-client-release-artifact-split.md)、[ADR-134](134-web-site-icon.md)、[ADR-135](135-web-swift-icon-contract.md)、[ADR-137](137-beta-version-resolved-from-live-channel.md)、[ADR-138](138-browser-local-tab-workspace-cache.md)、[ADR-139](139-research-report-provenance-and-sharing.md)、[ADR-140](140-public-technical-documentation.md)、[ADR-142](142-研究根对象与证据访问边界.md)、[ADR-156](156-retire-research-graph-agent-workflow.md) | [ADR-084](084-research-graph-yaml-network-view.md)、[ADR-096](096-cli-runtime-ownership-and-pipx.md) |
| Profile Agent、助手、Skill 和安全边界 | [ADR-011](011-page-state-debug-registration.md)、[ADR-104](104-profile-runtime-and-agent-claims.md)、[ADR-105](105-server-installed-profile-skills.md)、[ADR-106](106-mihomo-super-admin-dashboard.md)、[ADR-107](107-public-agent-runtime-dependencies.md)、[ADR-112](112-profile-agent-chat-ui-resource.md)、[ADR-113](113-profile-agent-conversation-catalog.md)、[ADR-114](114-public-codex-bwrap-container-sandbox.md)、[ADR-115](115-profile-agent-local-cli-auth.md)、[ADR-119](119-profile-agent-cc-switch-gateway.md)、[ADR-124](124-webmcp-browser-action-surface.md)、[ADR-125](125-page-state-and-profile-agent-assistance.md)、[ADR-126](126-profile-agent-isolation-and-assistance-drafts.md)、[ADR-147](147-workspace-page-assistance.md) | — |
| API、CLI、实现包名和文件夹层级迁移 | [ADR-141](141-api-cli-and-implementation-layout-migration.md) | — |

## 更新要求

研究根对象及关系的跨服务器复制补充见 [ADR-149](149-research-catalog-replication.md)（实施中）。

修改 ADR 时先核对当前源码、路由注册、CLI 命令树、Web/Swift 调用方、测试和部署 manifest。
如果实现与文字不一致，优先改状态和迁移边界；只有源码也应改变时才同时开代码任务。不要为了
让目录看起来整齐而删除仍被 import、历史数据或 capability 使用的内部模块。

ADR-156 对 ADR-040、ADR-047、ADR-094、ADR-142 的 Graph 专属约束作部分取代；报告正文、ReportBranch、
跨服务器身份与 Evidence 访问规则仅在不与 ADR-156 冲突的范围内继续有效。Graph 产品数据不迁移保留。

- [153 — 因子集合登记生命周期与成员事件](153-factor-set-membership-history.md)
- [155 — 作用域分区聚合（groupby_scope）](155-scope-partitioned-aggregation.md)
- [156 — 退役 Research Graph，采用 Agent WorkflowRun 与独立研究对象](156-retire-research-graph-agent-workflow.md)
