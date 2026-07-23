import CryptoKit
import Foundation
import XCTest
@testable import FTClient

final class ResearchJournalTests: XCTestCase {
    func testUnitTestHostDoesNotLoadRealUserState() {
        XCTAssertFalse(AppRuntimePolicy.shouldLoadUserState(environment: [
            "XCTestConfigurationFilePath": "/tmp/session.xctestconfiguration",
        ]))
        XCTAssertTrue(AppRuntimePolicy.shouldLoadUserState(environment: [:]))
    }

    func testResearchRecordSelectsJournalCoveringCurrentCheckpoint() {
        let record = ResearchRecordModel(json: [
            "record_id": "work-package",
            "checkpoint_ref": "trace:latest",
            "artifacts": [
                [
                    "artifact_ref": "artifact:older",
                    "journal_ref": "file:///older/LOGICAL_JOURNAL.json",
                    "journal_hash": String(repeating: "a", count: 64),
                    "section_refs": [[
                        "link_id": "checkpoint-old",
                        "kind": "checkpoint",
                        "target_ref": "trace:older",
                        "section_ref": "report-section:old",
                    ]],
                ],
                [
                    "artifact_ref": "artifact:latest",
                    "journal_ref": "file:///latest/LOGICAL_JOURNAL.json",
                    "journal_hash": String(repeating: "b", count: 64),
                    "section_refs": [[
                        "link_id": "checkpoint-latest",
                        "kind": "checkpoint",
                        "target_ref": "trace:latest",
                        "section_ref": "report-section:latest",
                    ]],
                ],
            ],
        ])

        XCTAssertEqual(record.currentJournalArtifact?.id, "artifact:latest")
    }

    func testReportIndexAcceptsCurrentNodeReportCheckpoint() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: directory) }
        let indexURL = directory.appendingPathComponent("INDEX.json")
        try Data(
            """
            {"schema_version":2,"sections":[{
              "section_ref":"report-section:branch:semantics",
              "section_id":"semantics",
              "checkpoint_ref":"report-checkpoint:sha256:\(String(repeating: "a", count: 64))",
              "branch_ref":"graph-branch:instance:branch",
              "title":"因子语义",
              "summary":"当前节点增量报告",
              "links":[]
            }]}
            """.utf8
        ).write(to: indexURL)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "index_ref": indexURL.absoluteString,
        ])

        let sections = try await ResearchReportIndex.loadVerified(
            artifact: artifact
        )

        XCTAssertEqual(sections.count, 1)
        XCTAssertTrue(
            sections[0].checkpointRef.hasPrefix("report-checkpoint:")
        )
    }

    func testDecodesAndPartitionsEntryResolutionWithoutRawIDsInLabels() throws {
        let step = try JSONDecoder().decode(
            ResearchTransitionStep.self,
            from: Data(
                """
                {"step_ref":"trace:entry","edge_ref":"graph-edge:continue","from_node":"factor_semantics","to_node":"factor_semantics","created_at":1,"evidence_refs":[],"trial_plan_refs":[],"obligation_refs":[],"claim_refs":[],"job_refs":[],"run_refs":[],"obligation_changes":[],"claim_changes":[],"entry_resolution":{"reason":"graph_continuation","assessed_requirement_ids":["factor.expression"],"reused_requirement_ids":[],"reference_only_requirement_ids":["factor.expression"],"unresolved_requirement_ids":[],"items":[{"requirement_id":"factor.expression","title_zh":"因子表达式的经济语义是否成立","assessed":true,"change_kind":"revised","resolution_status":"reference_only"}],"resume_node":"factor_semantics"}}
                """.utf8
            )
        )

        let resolution = try XCTUnwrap(step.entryResolution)
        let groups = ResearchEntryResolutionPresentation.groups(resolution)
        XCTAssertEqual(groups.referenceOnly.map(\.titleZh), [
            "因子表达式的经济语义是否成立",
        ])
        XCTAssertTrue(groups.reviewed.isEmpty)
        XCTAssertTrue(groups.reused.isEmpty)
        XCTAssertEqual(
            ResearchEntryResolutionPresentation.changeLabel(
                groups.referenceOnly[0].changeKind
            ),
            "语义已修订"
        )
    }

    func testDecodesStructuredListAndTableWithRowLinks() throws {
        let document = try JSONDecoder().decode(
            ResearchJournalDocument.self,
            from: structuredJournalData()
        )
        let section = try XCTUnwrap(document.checkpoints.first?.sections.first)

        XCTAssertEqual(document.schemaVersion, 4)
        XCTAssertEqual(
            section.body,
            "本阶段先说明研究判断，再列出结构化结果。"
        )
        XCTAssertEqual(section.blocks.map(\.kind), ["paragraph", "list", "table"])
        XCTAssertEqual(section.blocks[0].linkIDs, ["obligation-row"])
        XCTAssertEqual(section.blocks[1].rows[0].linkIDs, ["evidence-row"])
        XCTAssertEqual(section.blocks[2].rows[0].cells.last, "0.42")
    }

    func testDecodesGenericFactorSemanticsMathBlock() throws {
        let block = try JSONDecoder().decode(
            ResearchJournalBlock.self,
            from: Data(
                #"{"kind":"math","latex":"S=(2P-H-L)/(H-L+\\epsilon)","fallback":"中心价格相对窗口高低点的位置强度。","link_ids":["paired-obligation"]}"#.utf8
            )
        )

        XCTAssertEqual(block.kind, "math")
        XCTAssertEqual(block.fallback, "中心价格相对窗口高低点的位置强度。")
        XCTAssertEqual(block.linkIDs, ["paired-obligation"])
    }

    func testDecodesHistoricalReportItemOccurrenceTime() throws {
        let block = try JSONDecoder().decode(
            ResearchJournalBlock.self,
            from: Data(
                #"{"kind":"paragraph","text":"完成语义审查。","report_timing":{"occurred_at":1.5,"time_basis":"historical_backfill","time_source_refs":["conversation:maxa-2"]}}"#.utf8
            )
        )

        let timing = try XCTUnwrap(block.reportTiming)
        XCTAssertEqual(timing.occurredAt, 1.5)
        XCTAssertEqual(timing.timeBasis, "historical_backfill")
        XCTAssertEqual(timing.timeSourceRefs, ["conversation:maxa-2"])
    }

    func testReportFacingIdentifiersAreAlwaysSimplifiedChinese() {
        XCTAssertEqual(ResearchDisplayText.node("capability_gap"), "能力缺口")
        XCTAssertEqual(ResearchDisplayText.linkKind("checkpoint"), "检查点")
        XCTAssertEqual(ResearchDisplayText.linkKind("trial_plan"), "试验计划")
        XCTAssertEqual(ResearchDisplayText.linkKind("evidence"), "证据")
        XCTAssertEqual(ResearchDisplayText.linkKind("profile_handoff"), "研究转接")
        XCTAssertEqual(
            ResearchDisplayText.productGroup("china_futures"),
            "中国期货"
        )
        XCTAssertEqual(
            ResearchDisplayText.reportTitle("SgCCS 因子研究报告"),
            "SgCCS 因子研究报告"
        )
    }

    func testAuditChipUsesChineseLabelInsteadOfStableReference() throws {
        let link = try JSONDecoder().decode(
            ResearchJournalLink.self,
            from: Data(
                """
                {"link_id":"cost","kind":"obligation","target_ref":"obligation:7ce46d1a-6bfd-43cc-a2ba-6b03e4617304","label":"交易成本后仍能存活吗？"}
                """.utf8
            )
        )
        let presentation = try JSONDecoder().decode(
            ResearchObligationPresentation.self,
            from: Data(
                """
                {"obligation_ref":"obligation:7ce46d1a-6bfd-43cc-a2ba-6b03e4617304","question_summary":"交易成本后仍能存活吗？"}
                """.utf8
            )
        )

        XCTAssertEqual(
            ResearchJournalPresentation.chipLabel(
                link,
                sectionTitle: "交易执行审查",
                obligations: [],
                obligationPresentations: [presentation]
            ),
            "研究义务 · 交易成本后仍能存活吗？"
        )
    }

    func testAuditChipHidesOpaqueLabelUntilPopover() throws {
        let link = try JSONDecoder().decode(
            ResearchJournalLink.self,
            from: Data(
                """
                {"link_id":"run","kind":"run","target_ref":"run:7ce46d1a-6bfd-43cc-a2ba-6b03e4617304","label":"7ce46d1a-6bfd-43cc-a2ba-6b03e4617304"}
                """.utf8
            )
        )

        XCTAssertEqual(
            ResearchJournalPresentation.chipLabel(
                link,
                sectionTitle: "回测结果",
                obligations: []
            ),
            "试验运行 · 回测结果试验结果"
        )
    }

    func testEvidenceChipUsesPersistedChineseSummaryAndNeverItsHash() throws {
        let link = try JSONDecoder().decode(
            ResearchJournalLink.self,
            from: Data(
                """
                {"link_id":"evidence","kind":"evidence","target_ref":"evidence:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}
                """.utf8
            )
        )
        let presentation = try JSONDecoder().decode(
            ResearchEvidencePresentation.self,
            from: Data(
                """
                {"evidence_ref":"evidence:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","title":"交易成本压力测试","claim_summary":"证明该因子在冻结成本假设下是否仍有净收益"}
                """.utf8
            )
        )

        XCTAssertEqual(
            ResearchJournalPresentation.chipLabel(
                link,
                sectionTitle: "回测结果",
                obligations: [],
                obligationPresentations: [],
                evidencePresentations: [presentation]
            ),
            "证据 · 交易成本压力测试：证明该因子在冻结成本假设下是否仍有净收益"
        )
    }

    func testEvidenceChipStatesDescriptionMissingInsteadOfShowingIdentifier() throws {
        let link = try JSONDecoder().decode(
            ResearchJournalLink.self,
            from: Data(
                """
                {"link_id":"evidence","kind":"evidence","target_ref":"evidence:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","label":"approval:1234"}
                """.utf8
            )
        )

        XCTAssertEqual(
            ResearchJournalPresentation.chipLabel(
                link,
                sectionTitle: "回测结果",
                obligations: [],
                obligationPresentations: [],
                evidencePresentations: []
            ),
            "证据 · 证据描述缺失"
        )
    }

    func testObligationCodeIsNotUsedAsReadableQuestion() {
        XCTAssertEqual(
            ResearchJournalPresentation.readableObligationQuestion(
                "sgccs-semantic-causal-role"
            ),
            "义务描述缺失"
        )
    }

    func testHistoricalObligationUsesCheckpointPersistedChineseQuestion() throws {
        let links = try JSONDecoder().decode(
            [ResearchJournalLink].self,
            from: Data(
                """
                [{"link_id":"semantic","kind":"obligation","target_ref":"obligation:sgccs-semantic-causal-role","label":"sgccs-semantic-causal-role"}]
                """.utf8
            )
        )
        let presentation = try JSONDecoder().decode(
            ResearchObligationPresentation.self,
            from: Data(
                """
                {"obligation_ref":"obligation:sgccs-semantic-causal-role","question_summary":"SgCCS 的语义和因果时点是否正确？"}
                """.utf8
            )
        )

        let rows = ResearchJournalPresentation.obligationRows(
            links: links,
            checkpointObligationRefs: [
                "obligation:sgccs-semantic-causal-role",
            ],
            obligations: [],
            obligationPresentations: [presentation],
            changes: []
        )

        XCTAssertEqual(rows[0].question, "SgCCS 的语义和因果时点是否正确？")
    }

    func testStageObligationsSeparateChangesFromInheritedQuestions() throws {
        let obligations = try decodeObligations(
            """
            [
              {"obligation_ref":"obligation:timing","status":"open","materiality":"high","question_summary":"信号时点是否满足因果约束？"},
              {"obligation_ref":"obligation:cost","status":"bounded","materiality":"critical","question_summary":"交易成本后是否仍然有效？"},
              {"obligation_ref":"obligation:parameter","status":"open","materiality":"high","question_summary":"固定价格列是否应参数化？"}
            ]
            """
        )
        let changes = try JSONDecoder().decode(
            [ResearchStateChange].self,
            from: Data(
                """
                [{"obligation_id":"cost","from_state":"open","to_state":"bounded"}]
                """.utf8
            )
        )
        let rows = ResearchJournalPresentation.obligationRows(
            links: [],
            checkpointObligationRefs: [
                "obligation:timing", "obligation:cost", "obligation:parameter",
            ],
            obligations: obligations,
            changes: changes
        )

        let stage = ResearchJournalPresentation.stageObligationRows(
            rows: rows,
            currentRefs: [
                "obligation:timing", "obligation:cost", "obligation:parameter",
            ],
            previousRefs: ["obligation:timing", "obligation:cost"],
            changes: changes
        )

        XCTAssertEqual(stage.active.map(\.question), [
            "交易成本后是否仍然有效？", "固定价格列是否应参数化？",
        ])
        XCTAssertEqual(stage.inherited.map(\.question), [
            "信号时点是否满足因果约束？",
        ])
    }

    func testObligationAndDeltaBecomeOneChineseTableRow() throws {
        let links = try JSONDecoder().decode(
            [ResearchJournalLink].self,
            from: Data(
                """
                [
                  {"link_id":"coverage","kind":"obligation","target_ref":"obligation:data-coverage"},
                  {"link_id":"coverage-change","kind":"delta","target_ref":"delta:step-1:obligation:data-coverage"}
                ]
                """.utf8
            )
        )
        let obligations = try JSONDecoder().decode(
            [ResearchObligationProjection].self,
            from: Data(
                """
                [{"obligation_ref":"obligation:data-coverage","status":"bounded","materiality":"critical","question_summary":"现有数据是否覆盖计划中的标的和时期？"}]
                """.utf8
            )
        )
        let changes = try JSONDecoder().decode(
            [ResearchStateChange].self,
            from: Data(
                """
                [{"obligation_id":"data-coverage","from_state":"open","to_state":"bounded"}]
                """.utf8
            )
        )

        let rows = ResearchJournalPresentation.obligationRows(
            links: links,
            obligations: obligations,
            changes: changes
        )

        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].question, "现有数据是否覆盖计划中的标的和时期？")
        XCTAssertEqual(rows[0].materiality, "关键")
        XCTAssertEqual(rows[0].change, "待验证 → 已收敛")
        XCTAssertEqual(rows[0].currentStatus, "已收敛")
        XCTAssertEqual(rows[0].obligationLink.linkID, "coverage")
        XCTAssertEqual(rows[0].deltaLink?.linkID, "coverage-change")
    }

    func testCheckpointRowsUseAllRefsAndPersistedChineseQuestions() throws {
        let links = try decodeLinks(
            """
            [{"link_id":"coverage","kind":"obligation","target_ref":"obligation:data-coverage","label":"Does data cover the plan?"}]
            """
        )
        let obligations = try decodeObligations(
            """
            [
              {"obligation_ref":"obligation:data-coverage","status":"bounded","materiality":"critical","question_summary":"Does data cover the plan?"},
              {"obligation_ref":"obligation:timing","status":"open","materiality":"high","question_summary":"Is timing causal?"}
            ]
            """
        )
        let presentations = try JSONDecoder().decode(
            [ResearchObligationPresentation].self,
            from: Data(
                """
                [
                  {"obligation_ref":"obligation:data-coverage","question_summary":"数据是否覆盖试验计划？"},
                  {"obligation_ref":"obligation:timing","question_summary":"信号与成交时点是否满足因果约束？"}
                ]
                """.utf8
            )
        )

        let rows = ResearchJournalPresentation.obligationRows(
            links: links,
            checkpointObligationRefs: [
                "obligation:data-coverage",
                "obligation:timing",
            ],
            obligations: obligations,
            obligationPresentations: presentations,
            changes: [],
            statusOverrides: [
                "data-coverage": "open",
                "timing": "open",
            ]
        )

        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows.map(\.question), [
            "数据是否覆盖试验计划？",
            "信号与成交时点是否满足因果约束？",
        ])
        XCTAssertEqual(rows.map(\.currentStatus), ["待验证", "待验证"])
        XCTAssertTrue(rows.allSatisfy { !$0.obligationLink.linkID.isEmpty })
    }

    func testDuplicateIndexJoinCannotCrashOrAmbiguouslyBindJournal() throws {
        let document = try JSONDecoder().decode(
            ResearchJournalDocument.self,
            from: journalData()
        )
        let section = ResearchReportSection(
            id: "report-section:b:progress",
            sectionID: "progress",
            checkpointRef: "trace:checkpoint-1",
            branchRef: "graph-branch:i:b",
            title: "研究进展",
            summary: "摘要",
            links: []
        )

        XCTAssertThrowsError(try ResearchJournalLoader.sections(
            in: document,
            indexedBy: [section, section]
        ))
    }

    func testDisplayProjectionHidesPureGraphMigrationAndDeduplicatesBindings()
        throws
    {
        let document = try JSONDecoder().decode(
            ResearchJournalDocument.self,
            from: Data(
                """
                {
                  "schema_version":4,"language":"zh-Hans",
                  "journal_kind":"work_package","work_package_id":"wp",
                  "branch_refs":["graph-branch:i:b"],"history_status":"complete",
                  "root_checkpoint_ref":"trace:research",
                  "checkpoints":[
                    {
                      "checkpoint_ref":"trace:research","created_at":1,
                      "carrier_hash":"\(String(repeating: "a", count: 64))",
                      "narrative_hash":"\(String(repeating: "b", count: 64))",
                      "section_hash":"\(String(repeating: "c", count: 64))",
                      "graph_ref":"factor-research@v9",
                      "instance_ref":"graph-instance:i",
                      "branch_ref":"graph-branch:i:b",
                      "lineage_status":"root","lineage_relation":"root",
                      "predecessor_checkpoint_ref":"","source_branch_ref":"",
                      "sections":[
                        {
                          "section_id":"current-node-report-1",
                          "title":"当前节点报告项 1",
                          "blocks":[{
                            "kind":"list",
                            "rows":[{"text":"因子公式的经济含义已经逐项核对。","link_ids":[]}],
                            "report_binding":{
                              "report_requirement_id":"report.requirement.semantics",
                              "subject_ref":"obligation:first"
                            }
                          }],
                          "links":[]
                        },
                        {
                          "section_id":"current-node-report-2",
                          "title":"当前节点报告项 2",
                          "blocks":[{
                            "kind":"list",
                            "rows":[{"text":"因子公式的经济含义已经逐项核对。","link_ids":[]}],
                            "report_binding":{
                              "report_requirement_id":"report.requirement.semantics",
                              "subject_ref":"obligation:second"
                            }
                          }],
                          "links":[]
                        }
                      ]
                    },
                    {
                      "checkpoint_ref":"trace:migration","created_at":2,
                      "carrier_hash":"\(String(repeating: "d", count: 64))",
                      "narrative_hash":"\(String(repeating: "e", count: 64))",
                      "section_hash":"\(String(repeating: "f", count: 64))",
                      "graph_ref":"factor-research@v10",
                      "instance_ref":"graph-instance:i",
                      "branch_ref":"graph-branch:i:b",
                      "lineage_status":"linked",
                      "lineage_relation":"graph_continuation",
                      "predecessor_checkpoint_ref":"trace:research",
                      "source_branch_ref":"graph-branch:i:old",
                      "sections":[{
                        "section_id":"graph-continuation-reentry",
                        "title":"研究图切换与当前节点重新进入",
                        "blocks":[{"kind":"paragraph","text":"只记录图版本变化。"}],
                        "links":[]
                      }]
                    }
                  ]
                }
                """.utf8
            )
        )
        let index = [
            ResearchReportSection(
                id: "report-section:one",
                sectionID: "current-node-report-1",
                checkpointRef: "trace:research",
                branchRef: "graph-branch:i:b",
                title: "当前节点报告项 1",
                summary: "摘要",
                links: []
            ),
            ResearchReportSection(
                id: "report-section:two",
                sectionID: "current-node-report-2",
                checkpointRef: "trace:research",
                branchRef: "graph-branch:i:b",
                title: "当前节点报告项 2",
                summary: "摘要",
                links: []
            ),
            ResearchReportSection(
                id: "report-section:migration",
                sectionID: "graph-continuation-reentry",
                checkpointRef: "trace:migration",
                branchRef: "graph-branch:i:b",
                title: "研究图切换与当前节点重新进入",
                summary: "摘要",
                links: []
            ),
        ]

        let sections = try ResearchJournalPresentation.displaySections(
            in: document,
            indexedBy: index
        )

        XCTAssertEqual(sections.count, 1)
        XCTAssertEqual(sections[0].title, "因子公式的经济含义已经逐项核对")
        XCTAssertEqual(
            sections[0].blocks[0].reportBinding?.subjectRef,
            "obligation:first"
        )
    }

    func testInlineLatexIsProjectedIntoRealMathComponents() {
        let components = ResearchReportTextProjection.components(
            #"原始公式为：\(X_t=\frac{P_t}{H_t-L_t}\)，其中 \(P_t\) 为价格。"#
        )

        XCTAssertEqual(components.map(\.kind), [
            .prose, .math, .prose, .math, .prose,
        ])
        XCTAssertEqual(components.filter { $0.kind == .math }.map(\.text), [
            #"X_t=\frac{P_t}{H_t-L_t}"#, "P_t",
        ])
    }

    func testCheckpointStatusRewindsOnlyLaterObligationChanges() throws {
        let obligations = try decodeObligations(
            """
            [{"obligation_ref":"obligation:data-coverage","status":"bounded","materiality":"critical","question_summary":"数据是否覆盖试验计划？"}]
            """
        )
        let steps = try JSONDecoder().decode(
            [ResearchTransitionStep].self,
            from: Data(
                """
                [
                  {"step_ref":"trace:early","edge_ref":"edge:1","from_node":"start","to_node":"plan","created_at":1,"evidence_refs":[],"trial_plan_refs":[],"obligation_refs":["obligation:data-coverage"],"claim_refs":[],"job_refs":[],"run_refs":[],"obligation_changes":[],"claim_changes":[]},
                  {"step_ref":"trace:later","edge_ref":"edge:2","from_node":"plan","to_node":"data","created_at":2,"evidence_refs":[],"trial_plan_refs":[],"obligation_refs":["obligation:data-coverage"],"claim_refs":[],"job_refs":[],"run_refs":[],"obligation_changes":[{"obligation_id":"data-coverage","from_state":"open","to_state":"bounded"}],"claim_changes":[]}
                ]
                """.utf8
            )
        )

        XCTAssertEqual(
            ResearchJournalPresentation.obligationStatuses(
                at: "trace:early",
                steps: steps,
                currentObligations: obligations
            )["data-coverage"],
            "open"
        )
        XCTAssertEqual(
            ResearchJournalPresentation.obligationStatuses(
                at: "trace:later",
                steps: steps,
                currentObligations: obligations
            )["data-coverage"],
            "bounded"
        )
    }

    func testEarlierCheckpointDoesNotShowFutureCreatedObligation() throws {
        let obligations = try decodeObligations(
            """
            [
              {"obligation_ref":"obligation:known","status":"open","materiality":"high","question_summary":"已知义务"},
              {"obligation_ref":"obligation:future","status":"open","materiality":"high","question_summary":"未来新增义务"}
            ]
            """
        )

        let rows = ResearchJournalPresentation.obligationRows(
            links: [],
            checkpointObligationRefs: ["obligation:known"],
            obligations: obligations,
            changes: [],
            statusOverrides: ["known": "open", "future": "open"]
        )

        XCTAssertEqual(rows.map(\.question), ["已知义务"])
    }

    func testUnknownInternalIdentifierIsNotExposedAsReportProse() {
        XCTAssertEqual(ResearchDisplayText.node("future_internal_node"), "研究进行中")
        XCTAssertEqual(ResearchDisplayText.linkKind("future_internal_link"), "审计对象")
        XCTAssertEqual(ResearchDisplayText.reportTitle("continuation-v7"), "因子研究报告")
        XCTAssertEqual(
            ResearchDisplayText.branchLabel(
                "continuation-v7",
                currentNode: "factor_semantics"
            ),
            "因子语义研究"
        )
        XCTAssertEqual(ResearchDisplayText.productGroup("unknown_group"), "其他产品组")
    }

    func testStoredWorkspaceAuthorizationSurvivesBookmarkReplacement() throws {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let root = home.appendingPathComponent(
            "Documents/FactorTester/users/18717974771",
            isDirectory: true
        )
        let report = root.appendingPathComponent(
            "profiles/maxa/research/example/REPORT.md"
        )

        XCTAssertEqual(
            PersonalWorkspaceAccessStore.storedAuthorizedRoot(
                path: root.path,
                for: report
            )?.path,
            root.path
        )
        XCTAssertNil(
            PersonalWorkspaceAccessStore.storedAuthorizedRoot(
                path: home.appendingPathComponent("Documents").path,
                for: report
            )
        )
        XCTAssertNil(
            PersonalWorkspaceAccessStore.storedAuthorizedRoot(
                path: root.appendingPathComponent("profiles/maxa").path,
                for: report
            )
        )
    }

    func testWorkspaceAccessScopeRemainsActiveForAsyncOperation() async throws {
        let target = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)

        let observed = try await PersonalWorkspaceAccessStore.withAccess(
            to: target
        ) {
            try await Task.sleep(for: .milliseconds(1))
            return target.path
        }

        XCTAssertEqual(observed, target.path)
    }

    func testLoadsVerifiedChineseJournalAndBindsCheckpointIdentity() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let data = journalData()
        let url = root.appendingPathComponent("JOURNAL.json")
        try data.write(to: url)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "format": "markdown",
            "status": "ready",
            "local_ref": root.appendingPathComponent("REPORT.md").absoluteString,
            "index_ref": root.appendingPathComponent("INDEX.json").absoluteString,
            "journal_ref": url.absoluteString,
            "journal_hash": sha256(data),
        ])

        let document = try await ResearchJournalLoader.load(artifact: artifact)
        let section = try XCTUnwrap(
            ResearchJournalLoader.sections(
                in: document,
                indexedBy: [ResearchReportSection(
                    id: "report-section:b:progress",
                    sectionID: "progress",
                    checkpointRef: "trace:checkpoint-1",
                    branchRef: "graph-branch:i:b",
                    title: "研究进展",
                    summary: "摘要",
                    links: []
                )]
            ).first
        )

        XCTAssertEqual(document.language, "zh-Hans")
        XCTAssertEqual(section.body, "本次检验尚未清除交易成本义务。")
        XCTAssertEqual(section.checkpointRef, "trace:checkpoint-1")
        XCTAssertEqual(section.links.first?.targetRef, "evidence:cost-1")
    }

    func testAcceptsProducerMaximumOfFiftyAuditLinks() async throws {
        var value = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: journalData())
                as? [String: Any]
        )
        var checkpoints = try XCTUnwrap(
            value["checkpoints"] as? [[String: Any]]
        )
        var sections = try XCTUnwrap(
            checkpoints[0]["sections"] as? [[String: Any]]
        )
        sections[0]["links"] = (0..<50).map { index in
            [
                "link_id": "evidence-\(index)",
                "kind": "evidence",
                "target_ref": "evidence:item-\(index)",
            ]
        }
        sections[0]["blocks"] = []
        checkpoints[0]["sections"] = sections
        value["checkpoints"] = checkpoints
        let data = try JSONSerialization.data(withJSONObject: value)
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("LOGICAL_JOURNAL.json")
        try data.write(to: url)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "journal_ref": url.absoluteString,
            "journal_hash": sha256(data),
        ])

        let document = try await ResearchJournalLoader.load(artifact: artifact)

        XCTAssertEqual(document.checkpoints[0].sections[0].links.count, 50)
    }

    func testRejectsJournalWhoseProfileHashDoesNotMatch() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("JOURNAL.json")
        try journalData().write(to: url)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "format": "markdown",
            "status": "ready",
            "journal_ref": url.absoluteString,
            "journal_hash": String(repeating: "0", count: 64),
        ])

        do {
            _ = try await ResearchJournalLoader.load(artifact: artifact)
            XCTFail("tampered journal should not be rendered")
        } catch let error as ResearchJournalError {
            guard case .hashMismatch = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    func testRejectsJournalWithoutProfileHashBeforeReadingFile() async throws {
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "format": "markdown",
            "status": "ready",
            "journal_ref": "file:///path/that/must/not/be/read/JOURNAL.json",
            "journal_hash": "",
        ])

        do {
            _ = try await ResearchJournalLoader.load(artifact: artifact)
            XCTFail("journal without a trusted hash must not be read")
        } catch let error as ResearchJournalError {
            guard case .missingReference = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    func testRejectsLegacyJournalWithoutTrustedRootLineage() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let data = legacyJournalData()
        let url = root.appendingPathComponent("JOURNAL.json")
        try data.write(to: url)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:legacy-report",
            "format": "markdown",
            "status": "ready",
            "journal_ref": url.absoluteString,
            "journal_hash": sha256(data),
        ])

        do {
            _ = try await ResearchJournalLoader.load(artifact: artifact)
            XCTFail("legacy journal must not impersonate complete history")
        } catch is DecodingError {
            // Schema v3 lacks physical graph and carrier ownership identity.
            // It must fail closed rather than be interpreted as v4 history.
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }

    func testRejectsJournalWithBrokenCheckpointPredecessor() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let data = brokenLineageJournalData()
        let url = root.appendingPathComponent("JOURNAL.json")
        try data.write(to: url)
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:broken-report",
            "format": "markdown",
            "status": "ready",
            "journal_ref": url.absoluteString,
            "journal_hash": sha256(data),
        ])

        do {
            _ = try await ResearchJournalLoader.load(artifact: artifact)
            XCTFail("a missing predecessor must stop report rendering")
        } catch let error as ResearchJournalError {
            guard case .historyIncomplete = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    func testRejectsSymlinkInsteadOfFollowingUntrustedJournalPath() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        defer { try? FileManager.default.removeItem(at: root) }
        let data = journalData()
        let target = root.appendingPathComponent("target.json")
        let link = root.appendingPathComponent("JOURNAL.json")
        try data.write(to: target)
        try FileManager.default.createSymbolicLink(
            at: link,
            withDestinationURL: target
        )
        let artifact = ResearchArtifactModel(json: [
            "artifact_ref": "artifact:report",
            "format": "markdown",
            "status": "ready",
            "journal_ref": link.absoluteString,
            "journal_hash": sha256(data),
        ])

        do {
            _ = try await ResearchJournalLoader.load(artifact: artifact)
            XCTFail("journal symlink should not be followed")
        } catch let error as ResearchJournalError {
            guard case .missingReference = error else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    private func journalData() -> Data {
        Data(
            """
            {"schema_version":4,"language":"zh-Hans","journal_kind":"work_package","work_package_id":"wp","branch_refs":["graph-branch:i:b"],"history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","graph_ref":"factor-research@v8","instance_ref":"graph-instance:i","branch_ref":"graph-branch:i:b","lineage_status":"root","lineage_relation":"root","predecessor_checkpoint_ref":"","source_branch_ref":"","sections":[{"section_id":"progress","title":"研究进展","body":"本次检验尚未清除交易成本义务。","blocks":[{"kind":"paragraph","text":"成本证据仍然有限。","link_ids":["cost"]}],"links":[{"link_id":"cost","kind":"evidence","target_ref":"evidence:cost-1"},{"link_id":"handoff","kind":"profile_handoff","target_ref":"profile-handoff:transfer-1"}]}]}]}
            """.utf8
        )
    }

    private func decodeLinks(_ json: String) throws -> [ResearchJournalLink] {
        try JSONDecoder().decode(
            [ResearchJournalLink].self,
            from: Data(json.utf8)
        )
    }

    private func decodeObligations(
        _ json: String
    ) throws -> [ResearchObligationProjection] {
        try JSONDecoder().decode(
            [ResearchObligationProjection].self,
            from: Data(json.utf8)
        )
    }

    private func structuredJournalData() -> Data {
        Data(
            """
            {"schema_version":4,"language":"zh-Hans","journal_kind":"work_package","work_package_id":"wp","branch_refs":["graph-branch:i:b"],"history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","graph_ref":"factor-research@v8","instance_ref":"graph-instance:i","branch_ref":"graph-branch:i:b","lineage_status":"root","lineage_relation":"root","predecessor_checkpoint_ref":"","source_branch_ref":"","sections":[{"section_id":"progress","title":"研究进展","body":"本阶段先说明研究判断，再列出结构化结果。","blocks":[{"kind":"paragraph","text":"该段结论受证据约束。","link_ids":["obligation-row"]},{"kind":"list","rows":[{"text":"交易成本义务仍未清除。","link_ids":["evidence-row"]}]},{"kind":"table","columns":["检验","指标","结果"],"rows":[{"cells":["成本后回测","夏普比率","0.42"],"link_ids":["evidence-row"]}]}],"links":[{"link_id":"obligation-row","kind":"obligation","target_ref":"obligation:cost"},{"link_id":"evidence-row","kind":"evidence","target_ref":"evidence:cost"}]}]}]}
            """.utf8
        )
    }

    private func legacyJournalData() -> Data {
        Data(
            """
            {"schema_version":3,"language":"zh-Hans","branch_id":"b","history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[]}
            """.utf8
        )
    }

    private func brokenLineageJournalData() -> Data {
        Data(
            """
            {"schema_version":4,"language":"zh-Hans","journal_kind":"work_package","work_package_id":"wp","branch_refs":["graph-branch:i:b"],"history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","graph_ref":"factor-research@v8","instance_ref":"graph-instance:i","branch_ref":"graph-branch:i:b","lineage_status":"root","lineage_relation":"root","predecessor_checkpoint_ref":"","source_branch_ref":"","sections":[{"section_id":"first","title":"起点","body":"从可信起点开始。","links":[]}]},{"checkpoint_ref":"trace:checkpoint-3","created_at":3,"carrier_hash":"\(String(repeating: "d", count: 64))","narrative_hash":"\(String(repeating: "e", count: 64))","section_hash":"\(String(repeating: "f", count: 64))","graph_ref":"factor-research@v8","instance_ref":"graph-instance:i","branch_ref":"graph-branch:i:b","lineage_status":"linked","lineage_relation":"transition","predecessor_checkpoint_ref":"trace:checkpoint-2","source_branch_ref":"","sections":[{"section_id":"third","title":"跳步","body":"中间检查点缺失。","links":[]}]}]}
            """.utf8
        )
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
