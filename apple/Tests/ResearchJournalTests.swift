import CryptoKit
import Foundation
import XCTest
@testable import FTClient

final class ResearchJournalTests: XCTestCase {
    func testDecodesStructuredListAndTableWithRowLinks() throws {
        let document = try JSONDecoder().decode(
            ResearchJournalDocument.self,
            from: structuredJournalData()
        )
        let section = try XCTUnwrap(document.checkpoints.first?.sections.first)

        XCTAssertEqual(document.schemaVersion, 2)
        XCTAssertEqual(
            section.body,
            "本阶段先说明研究判断，再列出结构化结果。"
        )
        XCTAssertEqual(section.blocks.map(\.kind), ["paragraph", "list", "table"])
        XCTAssertEqual(section.blocks[0].linkIDs, ["obligation-row"])
        XCTAssertEqual(section.blocks[1].rows[0].linkIDs, ["evidence-row"])
        XCTAssertEqual(section.blocks[2].rows[0].cells.last, "0.42")
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

        XCTAssertEqual(
            ResearchJournalPresentation.chipLabel(
                link,
                sectionTitle: "交易执行审查",
                obligations: []
            ),
            "研究义务 · 交易成本后仍能存活吗？"
        )
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
            ResearchJournalLoader.sections(in: document).first
        )

        XCTAssertEqual(document.language, "zh-Hans")
        XCTAssertEqual(section.body, "本次检验尚未清除交易成本义务。")
        XCTAssertEqual(section.checkpointRef, "trace:checkpoint-1")
        XCTAssertEqual(section.links.first?.targetRef, "evidence:cost-1")
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
        let data = structuredJournalData()
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
        } catch let error as ResearchJournalError {
            guard case .historyIncomplete = error else {
                return XCTFail("unexpected error: \(error)")
            }
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
            {"schema_version":3,"language":"zh-Hans","branch_id":"b","history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","lineage_status":"root","predecessor_checkpoint_ref":"","sections":[{"section_id":"progress","title":"研究进展","body":"本次检验尚未清除交易成本义务。","blocks":[{"kind":"paragraph","text":"成本证据仍然有限。","link_ids":["cost"]}],"links":[{"link_id":"cost","kind":"evidence","target_ref":"evidence:cost-1"},{"link_id":"handoff","kind":"profile_handoff","target_ref":"profile-handoff:transfer-1"}]}]}]}
            """.utf8
        )
    }

    private func structuredJournalData() -> Data {
        Data(
            """
            {"schema_version":2,"language":"zh-Hans","branch_id":"b","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","sections":[{"section_id":"progress","title":"研究进展","body":"本阶段先说明研究判断，再列出结构化结果。","blocks":[{"kind":"paragraph","text":"该段结论受证据约束。","link_ids":["obligation-row"]},{"kind":"list","rows":[{"text":"交易成本义务仍未清除。","link_ids":["evidence-row"]}]},{"kind":"table","columns":["检验","指标","结果"],"rows":[{"cells":["成本后回测","夏普比率","0.42"],"link_ids":["evidence-row"]}]}],"links":[{"link_id":"obligation-row","kind":"obligation","target_ref":"obligation:cost"},{"link_id":"evidence-row","kind":"evidence","target_ref":"evidence:cost"}]}]}]}
            """.utf8
        )
    }

    private func brokenLineageJournalData() -> Data {
        Data(
            """
            {"schema_version":3,"language":"zh-Hans","branch_id":"b","history_status":"complete","root_checkpoint_ref":"trace:checkpoint-1","checkpoints":[{"checkpoint_ref":"trace:checkpoint-1","created_at":1,"carrier_hash":"\(String(repeating: "a", count: 64))","narrative_hash":"\(String(repeating: "b", count: 64))","section_hash":"\(String(repeating: "c", count: 64))","lineage_status":"root","predecessor_checkpoint_ref":"","sections":[{"section_id":"first","title":"起点","body":"从可信起点开始。","links":[]}]},{"checkpoint_ref":"trace:checkpoint-3","created_at":3,"carrier_hash":"\(String(repeating: "d", count: 64))","narrative_hash":"\(String(repeating: "e", count: 64))","section_hash":"\(String(repeating: "f", count: 64))","lineage_status":"linked","predecessor_checkpoint_ref":"trace:checkpoint-2","sections":[{"section_id":"third","title":"跳步","body":"中间检查点缺失。","links":[]}]}]}
            """.utf8
        )
    }

    private func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
