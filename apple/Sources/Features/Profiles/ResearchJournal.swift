import CryptoKit
import Darwin
import Foundation

struct ResearchJournalDocument: Decodable {
    let schemaVersion: Int
    let language: String
    let journalKind: String
    let workPackageID: String
    let branchRefs: [String]
    let historyStatus: String?
    let rootCheckpointRef: String?
    let checkpoints: [ResearchJournalCheckpoint]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case language
        case journalKind = "journal_kind"
        case workPackageID = "work_package_id"
        case branchRefs = "branch_refs"
        case historyStatus = "history_status"
        case rootCheckpointRef = "root_checkpoint_ref"
        case checkpoints
    }
}

struct ResearchJournalCheckpoint: Decodable, Identifiable {
    let checkpointRef: String
    let createdAt: Double
    let carrierHash: String
    let narrativeHash: String
    let sectionHash: String
    let graphRef: String
    let instanceRef: String
    let branchRef: String
    let lineageStatus: String?
    let lineageRelation: String
    let predecessorCheckpointRef: String?
    let sourceBranchRef: String
    let sections: [ResearchJournalSection]

    var id: String { checkpointRef }

    enum CodingKeys: String, CodingKey {
        case checkpointRef = "checkpoint_ref"
        case createdAt = "created_at"
        case carrierHash = "carrier_hash"
        case narrativeHash = "narrative_hash"
        case sectionHash = "section_hash"
        case graphRef = "graph_ref"
        case instanceRef = "instance_ref"
        case branchRef = "branch_ref"
        case lineageStatus = "lineage_status"
        case lineageRelation = "lineage_relation"
        case predecessorCheckpointRef = "predecessor_checkpoint_ref"
        case sourceBranchRef = "source_branch_ref"
        case sections
    }
}

struct ResearchJournalSection: Decodable, Identifiable {
    let sectionRef: String
    let sectionID: String
    let title: String
    let body: String
    let blocks: [ResearchJournalBlock]
    let links: [ResearchJournalLink]
    let checkpointRef: String
    /// Immutable checkpoint that owns this prose. `checkpointRef` may be a
    /// display anchor when a report-only checkpoint is grouped below a graph
    /// node.
    let auditCheckpointRef: String
    let createdAt: Double
    let graphRef: String
    let branchRef: String
    let researchOccurredAt: Double?
    let timeBasis: String?
    let timeSourceRefs: [String]
    let displayKind: String

    var id: String { sectionRef }

    enum CodingKeys: String, CodingKey {
        case sectionID = "section_id"
        case title, body, blocks, links
        case researchOccurredAt = "research_occurred_at"
        case timeBasis = "time_basis"
        case timeSourceRefs = "time_source_refs"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sectionID = try container.decode(String.self, forKey: .sectionID)
        title = try container.decode(String.self, forKey: .title)
        body = try container.decodeIfPresent(String.self, forKey: .body) ?? ""
        blocks = try container.decodeIfPresent(
            [ResearchJournalBlock].self,
            forKey: .blocks
        ) ?? []
        links = try container.decode([ResearchJournalLink].self, forKey: .links)
        researchOccurredAt = try container.decodeIfPresent(
            Double.self,
            forKey: .researchOccurredAt
        )
        timeBasis = try container.decodeIfPresent(String.self, forKey: .timeBasis)
        timeSourceRefs = try container.decodeIfPresent(
            [String].self,
            forKey: .timeSourceRefs
        ) ?? []
        sectionRef = ""
        checkpointRef = ""
        auditCheckpointRef = ""
        createdAt = 0
        graphRef = ""
        branchRef = ""
        displayKind = "research"
    }

    init(
        sectionID: String,
        sectionRef: String,
        title: String,
        body: String,
        blocks: [ResearchJournalBlock],
        links: [ResearchJournalLink],
        checkpointRef: String,
        auditCheckpointRef: String? = nil,
        createdAt: Double,
        graphRef: String = "",
        branchRef: String = "",
        researchOccurredAt: Double? = nil,
        timeBasis: String? = nil,
        timeSourceRefs: [String] = [],
        displayKind: String = "research"
    ) {
        self.sectionID = sectionID
        self.sectionRef = sectionRef
        self.title = title
        self.body = body
        self.blocks = blocks
        self.links = links
        self.checkpointRef = checkpointRef
        self.auditCheckpointRef = auditCheckpointRef ?? checkpointRef
        self.createdAt = createdAt
        self.graphRef = graphRef
        self.branchRef = branchRef
        self.researchOccurredAt = researchOccurredAt
        self.timeBasis = timeBasis
        self.timeSourceRefs = timeSourceRefs
        self.displayKind = displayKind
    }

    func bound(
        to checkpoint: ResearchJournalCheckpoint,
        sectionRef: String
    ) -> Self {
        Self(
            sectionID: sectionID,
            sectionRef: sectionRef,
            title: title,
            body: body,
            blocks: blocks,
            links: links,
            checkpointRef: checkpoint.checkpointRef,
            auditCheckpointRef: checkpoint.checkpointRef,
            createdAt: checkpoint.createdAt,
            graphRef: checkpoint.graphRef,
            branchRef: checkpoint.branchRef,
            researchOccurredAt: researchOccurredAt,
            timeBasis: timeBasis,
            timeSourceRefs: timeSourceRefs,
            displayKind: displayKind
        )
    }
}

struct ResearchJournalBlock: Decodable {
    let kind: String
    let text: String?
    let latex: String?
    let fallback: String?
    let asset: ResearchJournalAsset?
    let linkIDs: [String]
    let columns: [String]
    let rows: [ResearchJournalRow]
    let reportTiming: ResearchOccurrenceTiming?
    let reportBinding: ResearchJournalReportBinding?

    enum CodingKeys: String, CodingKey {
        case kind, text, latex, fallback, asset, columns, rows
        case linkIDs = "link_ids"
        case reportTiming = "report_timing"
        case reportBinding = "report_binding"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try container.decode(String.self, forKey: .kind)
        text = try container.decodeIfPresent(String.self, forKey: .text)
        latex = try container.decodeIfPresent(String.self, forKey: .latex)
        fallback = try container.decodeIfPresent(String.self, forKey: .fallback)
        asset = try container.decodeIfPresent(
            ResearchJournalAsset.self,
            forKey: .asset
        )
        linkIDs = try container.decodeIfPresent(
            [String].self, forKey: .linkIDs
        ) ?? []
        columns = try container.decodeIfPresent(
            [String].self,
            forKey: .columns
        ) ?? []
        rows = try container.decodeIfPresent(
            [ResearchJournalRow].self,
            forKey: .rows
        ) ?? []
        reportTiming = try container.decodeIfPresent(
            ResearchOccurrenceTiming.self,
            forKey: .reportTiming
        )
        reportBinding = try container.decodeIfPresent(
            ResearchJournalReportBinding.self,
            forKey: .reportBinding
        )
    }
}

struct ResearchJournalReportBinding: Decodable {
    let reportRequirementID: String
    let subjectRef: String
    let reportItemRef: String?

    enum CodingKeys: String, CodingKey {
        case reportRequirementID = "report_requirement_id"
        case subjectRef = "subject_ref"
        case reportItemRef = "report_item_ref"
    }
}

struct ResearchJournalAsset: Decodable, Equatable {
    let assetRef: String
    let contentHash: String
    let mediaType: String
    let filename: String
    let caption: String
    let altText: String
    let availability: String
    let provenanceRefs: [String]

    enum CodingKeys: String, CodingKey {
        case assetRef = "asset_ref"
        case contentHash = "content_hash"
        case mediaType = "media_type"
        case filename, caption
        case altText = "alt_text"
        case availability
        case provenanceRefs = "provenance_refs"
    }
}

struct ResearchOccurrenceTiming: Decodable {
    let occurredAt: Double
    let timeBasis: String
    let timeSourceRefs: [String]

    enum CodingKeys: String, CodingKey {
        case occurredAt = "occurred_at"
        case timeBasis = "time_basis"
        case timeSourceRefs = "time_source_refs"
    }
}

struct ResearchJournalRow: Decodable {
    let text: String?
    let cells: [String]
    let linkIDs: [String]

    enum CodingKeys: String, CodingKey {
        case text, cells
        case linkIDs = "link_ids"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        text = try container.decodeIfPresent(String.self, forKey: .text)
        cells = try container.decodeIfPresent(
            [String].self,
            forKey: .cells
        ) ?? []
        linkIDs = try container.decodeIfPresent(
            [String].self,
            forKey: .linkIDs
        ) ?? []
    }
}

struct ResearchJournalLink: Decodable, Identifiable, Hashable {
    let linkID: String
    let kind: String
    let targetRef: String
    let label: String?

    var id: String { linkID }

    enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case kind
        case targetRef = "target_ref"
        case label
    }
}

enum ResearchJournalPresentation {
    static func hasReadableEvidencePresentation(
        _ link: ResearchJournalLink,
        in presentations: [ResearchEvidencePresentation]
    ) -> Bool {
        evidenceSummary(for: link, in: presentations) != nil
    }

    static func chipLabel(
        _ link: ResearchJournalLink,
        sectionTitle: String,
        obligations: [ResearchObligationProjection],
        obligationPresentations: [ResearchObligationPresentation] = [],
        evidencePresentations: [ResearchEvidencePresentation] = []
    ) -> String {
        let summary: String
        if link.kind == "evidence" {
            summary = evidenceSummary(
                for: link,
                in: evidencePresentations
            ) ?? "证据描述缺失"
        } else if link.kind == "obligation" {
            summary = obligationSummary(
                for: link,
                in: obligationPresentations
            )
                ?? obligationSummary(for: link, in: obligations)
                ?? "义务描述缺失"
        } else {
            summary = link.label.flatMap(displayAlias)
                ?? contextualSummary(
                    for: link.kind,
                    sectionTitle: sectionTitle
                )
        }
        return "\(ResearchDisplayText.linkKind(link.kind)) · \(summary)"
    }

    private static func obligationSummary(
        for link: ResearchJournalLink,
        in presentations: [ResearchObligationPresentation]
    ) -> String? {
        guard link.kind == "obligation" else { return nil }
        return presentations.first {
            $0.obligationRef == link.targetRef
        }.flatMap { chineseSummary($0.questionSummary) }
    }

    private static func obligationSummary(
        for link: ResearchJournalLink,
        in obligations: [ResearchObligationProjection]
    ) -> String? {
        guard link.kind == "obligation" else { return nil }
        return obligations.first {
            $0.obligationRef == link.targetRef
        }.flatMap { nonEmpty($0.questionSummary) }
    }

    private static func evidenceSummary(
        for link: ResearchJournalLink,
        in presentations: [ResearchEvidencePresentation]
    ) -> String? {
        guard let presentation = presentations.first(where: {
            $0.evidenceRef == link.targetRef
        }) else { return nil }
        let title = chineseSummary(presentation.title)
        let claim = chineseSummary(presentation.claimSummary)
        switch (title, claim) {
        case let (title?, claim?): return "\(title)：\(claim)"
        case let (title?, nil): return title
        case let (nil, claim?): return claim
        case (nil, nil): return nil
        }
    }

    private static func contextualSummary(
        for kind: String,
        sectionTitle: String
    ) -> String {
        let section = nonEmpty(sectionTitle) ?? "本步骤"
        switch kind {
        case "checkpoint": return "\(section)检查点"
        case "trial_plan": return "\(section)试验计划"
        case "obligation": return "\(section)待回答问题"
        case "claim": return "\(section)研究主张"
        case "evidence": return "\(section)研究证据"
        case "job": return "\(section)计算任务"
        case "run": return "\(section)试验结果"
        case "delta": return "\(section)状态变化"
        case "profile_handoff": return "\(section)研究转接"
        case "report_section": return "\(section)报告章节"
        default: return "\(section)审计详情"
        }
    }

    private static func displayAlias(_ value: String) -> String? {
        guard let text = nonEmpty(value) else { return nil }
        let opaque = text.range(
            of: #"^(?:[0-9a-f]{32,64}|[0-9a-f]{8}-[0-9a-f-]{27,})$"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
        return opaque ? nil : text
    }

    private static func chineseSummary(_ value: String) -> String? {
        guard let text = nonEmpty(value),
              text.range(
                of: #"\p{Han}"#,
                options: .regularExpression
              ) != nil else {
            return nil
        }
        return text
    }

    static func statusLabel(_ status: String) -> String {
        switch status.lowercased() {
        case "open": return "待验证"
        case "bounded": return "已收敛"
        case "discharged": return "已清除"
        case "reopened": return "重新开启"
        case "blocked": return "受阻"
        case "unknown": return "未知"
        default: return "待审查"
        }
    }

    static func materialityLabel(_ materiality: String?) -> String {
        switch materiality?.lowercased() {
        case "critical": return "关键"
        case "high": return "重要"
        case "medium": return "中等"
        case "low": return "一般"
        default: return "待评估"
        }
    }

    private static func nonEmpty(_ value: String) -> String? {
        let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }
}

enum ResearchJournalLoader {
    static let maximumBytes = 4 * 1024 * 1024
    static let maximumCheckpoints = 4_096
    static let maximumSectionsPerCheckpoint = 64
    static let maximumLinksPerSection = 50
    private static let linkKinds: Set<String> = [
        "checkpoint", "trial_plan", "obligation", "claim", "evidence",
        "job", "run", "delta", "profile_handoff", "report_section",
    ]

    static func load(
        artifact: ResearchArtifactModel
    ) async throws -> ResearchJournalDocument {
        guard let url = URL(string: artifact.journalRef), url.isFileURL,
              !artifact.journalHash.isEmpty else {
            throw ResearchJournalError.missingReference
        }
        return try await Task.detached {
            let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                try readBoundedRegularFile(url)
            }
            guard sha256(data) == artifact.journalHash else {
                throw ResearchJournalError.hashMismatch
            }
            let decoded = try JSONDecoder().decode(
                ResearchJournalDocument.self,
                from: data
            )
            try validate(decoded)
            return decoded
        }.value
    }

    private static func readBoundedRegularFile(_ url: URL) throws -> Data {
        let descriptor: Int32 = url.withUnsafeFileSystemRepresentation {
            path -> Int32 in
            guard let path else { return -1 }
            return Darwin.open(
                path,
                O_RDONLY | O_CLOEXEC | O_NOFOLLOW
            )
        }
        guard descriptor >= 0 else {
            throw ResearchJournalError.missingReference
        }
        let handle = FileHandle(
            fileDescriptor: descriptor,
            closeOnDealloc: true
        )
        defer { try? handle.close() }

        var metadata = Darwin.stat()
        guard Darwin.fstat(descriptor, &metadata) == 0,
              metadata.st_size >= 0,
              metadata.st_size <= maximumBytes,
              metadata.st_mode & S_IFMT == S_IFREG else {
            throw ResearchJournalError.invalidSize
        }

        var data = Data()
        while data.count <= maximumBytes {
            let remaining = maximumBytes + 1 - data.count
            guard remaining > 0,
                  let chunk = try handle.read(
                    upToCount: min(remaining, 64 * 1024)
                  ),
                  !chunk.isEmpty else { break }
            data.append(chunk)
        }
        guard data.count <= maximumBytes else {
            throw ResearchJournalError.invalidSize
        }
        return data
    }

    static func sections(
        in document: ResearchJournalDocument,
        indexedBy indexSections: [ResearchReportSection]
    ) throws -> [ResearchJournalSection] {
        var refs: [String: ResearchReportSection] = [:]
        for section in indexSections {
            let key = "\(section.checkpointRef)|\(section.sectionID)"
            guard refs.updateValue(section, forKey: key) == nil else {
                throw ResearchJournalError.historyIncomplete
            }
        }
        var result: [ResearchJournalSection] = []
        let latestRevisions = latestCurrentNodeRevisions(
            in: document.checkpoints
        )
        for checkpoint in document.checkpoints {
            for section in checkpoint.sections {
                if let key = currentNodeRevisionKey(
                    checkpoint: checkpoint,
                    section: section
                ), latestRevisions[key] != SectionIdentity(
                    checkpointRef: checkpoint.checkpointRef,
                    sectionID: section.sectionID
                ) {
                    continue
                }
                let key = "\(checkpoint.checkpointRef)|\(section.sectionID)"
                guard let indexed = refs[key],
                      indexed.branchRef == checkpoint.branchRef else {
                    throw ResearchJournalError.historyIncomplete
                }
                result.append(section.bound(
                    to: checkpoint,
                    sectionRef: indexed.id
                ))
            }
        }
        guard result.count == indexSections.count else {
            throw ResearchJournalError.historyIncomplete
        }
        return result
    }

    /// `LOGICAL_JOURNAL` is the immutable audit lineage. `INDEX` and REPORT
    /// deliberately project only the latest revision of each current-node
    /// report requirement/subject pair. Mirror the writer's deterministic
    /// projection before joining the two verified objects; never require an
    /// index row for an intentionally superseded audit revision.
    private static func latestCurrentNodeRevisions(
        in checkpoints: [ResearchJournalCheckpoint]
    ) -> [CurrentNodeRevisionKey: SectionIdentity] {
        var latest: [CurrentNodeRevisionKey: SectionIdentity] = [:]
        for checkpoint in checkpoints {
            for section in checkpoint.sections {
                guard let key = currentNodeRevisionKey(
                    checkpoint: checkpoint,
                    section: section
                ) else { continue }
                latest[key] = SectionIdentity(
                    checkpointRef: checkpoint.checkpointRef,
                    sectionID: section.sectionID
                )
            }
        }
        return latest
    }

    private static func currentNodeRevisionKey(
        checkpoint: ResearchJournalCheckpoint,
        section: ResearchJournalSection
    ) -> CurrentNodeRevisionKey? {
        guard checkpoint.checkpointRef.hasPrefix(
            "report-checkpoint:sha256:"
        ), section.sectionID.contains("-current-node-"),
              section.blocks.count == 1,
              let binding = section.blocks[0].reportBinding,
              !binding.reportRequirementID.isEmpty,
              !binding.subjectRef.isEmpty else {
            return nil
        }
        return CurrentNodeRevisionKey(
            reportRequirementID: binding.reportRequirementID,
            subjectRef: binding.subjectRef
        )
    }

    private struct CurrentNodeRevisionKey: Hashable {
        let reportRequirementID: String
        let subjectRef: String
    }

    private struct SectionIdentity: Equatable {
        let checkpointRef: String
        let sectionID: String
    }

    private static func validate(_ value: ResearchJournalDocument) throws {
        guard value.schemaVersion == 4,
              value.journalKind == "work_package",
              value.historyStatus == "complete",
              !value.checkpoints.isEmpty,
              value.rootCheckpointRef
                == value.checkpoints.first?.checkpointRef else {
            throw ResearchJournalError.historyIncomplete
        }
        guard value.language == "zh-Hans",
              !value.workPackageID.isEmpty,
              !value.branchRefs.isEmpty,
              value.checkpoints.count <= maximumCheckpoints else {
            throw ResearchJournalError.invalidContract
        }
        var checkpointRefs = Set<String>()
        var sectionIDs = Set<String>()
        var previousCheckpoint: ResearchJournalCheckpoint?
        for checkpoint in value.checkpoints {
            guard checkpointRefs.insert(checkpoint.checkpointRef).inserted,
                  checkpoint.createdAt.isFinite,
                  checkpoint.createdAt >= 0,
                  isSHA256(checkpoint.carrierHash),
                  isSHA256(checkpoint.narrativeHash),
                  isSHA256(checkpoint.sectionHash),
                  checkpoint.graphRef.contains("@v"),
                  checkpoint.instanceRef.hasPrefix("graph-instance:"),
                  checkpoint.branchRef.hasPrefix("graph-branch:"),
                  value.branchRefs.contains(checkpoint.branchRef),
                  !checkpoint.sections.isEmpty,
                  checkpoint.sections.count <= maximumSectionsPerCheckpoint
            else {
                throw ResearchJournalError.invalidContract
            }
            if let previousCheckpoint {
                guard checkpoint.lineageStatus == "linked",
                      checkpoint.predecessorCheckpointRef
                        == previousCheckpoint.checkpointRef,
                      checkpoint.createdAt >= previousCheckpoint.createdAt else {
                    throw ResearchJournalError.historyIncomplete
                }
                let crossedBranch = checkpoint.branchRef
                    != previousCheckpoint.branchRef
                if crossedBranch {
                    guard ["branch_fork", "graph_continuation"].contains(
                        checkpoint.lineageRelation
                    ), checkpoint.sourceBranchRef
                        == previousCheckpoint.branchRef else {
                        throw ResearchJournalError.historyIncomplete
                    }
                } else {
                    guard checkpoint.lineageRelation == "transition",
                          checkpoint.sourceBranchRef.isEmpty else {
                        throw ResearchJournalError.historyIncomplete
                    }
                }
            } else {
                guard checkpoint.lineageStatus == "root",
                      checkpoint.lineageRelation == "root",
                      checkpoint.predecessorCheckpointRef == "",
                      checkpoint.sourceBranchRef.isEmpty else {
                    throw ResearchJournalError.historyIncomplete
                }
            }
            for section in checkpoint.sections {
                guard !section.sectionID.isEmpty,
                      !section.title.isEmpty,
                      (!section.body.isEmpty || !section.blocks.isEmpty),
                      section.links.count <= maximumLinksPerSection,
                      sectionIDs.insert(
                        "\(checkpoint.checkpointRef)|\(section.sectionID)"
                    ).inserted else {
                    throw ResearchJournalError.invalidContract
                }
                try validateLinks(section.links)
                try validateTiming(
                    occurredAt: section.researchOccurredAt,
                    timeBasis: section.timeBasis,
                    timeSourceRefs: section.timeSourceRefs,
                    recordedAt: checkpoint.createdAt
                )
                try validateBlocks(section)
            }
            previousCheckpoint = checkpoint
        }
    }

    private static func validateBlocks(
        _ section: ResearchJournalSection
    ) throws {
        guard section.blocks.count <= 32 else {
            throw ResearchJournalError.invalidContract
        }
        let linkIDs = Set(section.links.map(\.linkID))
        for block in section.blocks {
            if let timing = block.reportTiming {
                try validateTiming(
                    occurredAt: timing.occurredAt,
                    timeBasis: timing.timeBasis,
                    timeSourceRefs: timing.timeSourceRefs,
                    recordedAt: section.createdAt
                )
            }
            switch block.kind {
            case "math":
                guard block.text == nil,
                      let latex = block.latex, !latex.isEmpty,
                      let fallback = block.fallback, !fallback.isEmpty,
                      block.columns.isEmpty, block.rows.isEmpty,
                      !block.linkIDs.isEmpty,
                      Set(block.linkIDs).isSubset(of: linkIDs) else {
                    throw ResearchJournalError.invalidContract
                }
            case "paragraph":
                guard let text = block.text, !text.isEmpty,
                      block.columns.isEmpty, block.rows.isEmpty,
                      Set(block.linkIDs).isSubset(of: linkIDs) else {
                    throw ResearchJournalError.invalidContract
                }
            case "figure":
                guard block.text == nil, block.latex == nil,
                      block.fallback == nil,
                      let asset = block.asset,
                      validateAsset(asset),
                      block.columns.isEmpty, block.rows.isEmpty,
                      !block.linkIDs.isEmpty,
                      Set(block.linkIDs).isSubset(of: linkIDs) else {
                    throw ResearchJournalError.invalidContract
                }
            case "list":
                guard block.text == nil, block.columns.isEmpty,
                      !block.rows.isEmpty, block.rows.count <= 64 else {
                    throw ResearchJournalError.invalidContract
                }
                for row in block.rows {
                    guard let text = row.text, !text.isEmpty,
                          row.cells.isEmpty,
                          Set(row.linkIDs).isSubset(of: linkIDs) else {
                        throw ResearchJournalError.invalidContract
                    }
                }
            case "table":
                guard block.text == nil,
                      !block.columns.isEmpty, block.columns.count <= 12,
                      !block.rows.isEmpty, block.rows.count <= 64 else {
                    throw ResearchJournalError.invalidContract
                }
                for row in block.rows {
                    guard row.text == nil,
                          row.cells.count == block.columns.count,
                          Set(row.linkIDs).isSubset(of: linkIDs) else {
                        throw ResearchJournalError.invalidContract
                    }
                }
            default:
                throw ResearchJournalError.invalidContract
            }
        }
        // A link may intentionally remain section-level so the report renders
        // it as a standalone audit chip below the prose. Every inline
        // reference must resolve, but a valid checkpoint/evidence link does
        // not need to be forced into an unrelated sentence or table row.
    }

    private static func validateAsset(
        _ asset: ResearchJournalAsset
    ) -> Bool {
        let extensions = [
            "image/svg+xml": "svg",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
        ]
        guard let pathExtension = extensions[asset.mediaType],
              isSHA256(asset.contentHash),
              asset.assetRef
                == "report-asset:sha256:\(asset.contentHash)",
              asset.filename
                == "\(asset.contentHash).\(pathExtension)",
              asset.availability == "available",
              !asset.caption.isEmpty,
              asset.provenanceRefs.count <= 16 else {
            return false
        }
        return true
    }

    private static func validateTiming(
        occurredAt: Double?,
        timeBasis: String?,
        timeSourceRefs: [String],
        recordedAt: Double
    ) throws {
        guard occurredAt != nil || timeBasis != nil || !timeSourceRefs.isEmpty
        else { return }
        guard let occurredAt,
              let timeBasis,
              occurredAt.isFinite,
              occurredAt >= 0,
              occurredAt <= recordedAt,
              Set(["transition", "historical_backfill"]).contains(timeBasis),
              Set(timeSourceRefs).count == timeSourceRefs.count,
              timeSourceRefs == timeSourceRefs.sorted(),
              timeBasis != "transition" || occurredAt == recordedAt,
              timeBasis != "historical_backfill" || !timeSourceRefs.isEmpty
        else {
            throw ResearchJournalError.invalidContract
        }
    }

    private static func validateLinks(
        _ links: [ResearchJournalLink]
    ) throws {
        var identifiers = Set<String>()
        for link in links {
            guard !link.linkID.isEmpty,
                  identifiers.insert(link.linkID).inserted,
                  linkKinds.contains(link.kind),
                  isStableReference(link.targetRef) else {
                throw ResearchJournalError.invalidContract
            }
        }
    }

    private static func isStableReference(_ value: String) -> Bool {
        guard value.count <= 512,
              !value.isEmpty,
              !value.contains("\\"),
              !value.contains("?"),
              !value.contains("#"),
              !value.hasPrefix("/"),
              !value.hasPrefix("~") else {
            return false
        }
        let parts = value.split(separator: ":", maxSplits: 1)
        guard parts.count == 2,
              !parts[0].isEmpty,
              !parts[1].isEmpty,
              parts[0].allSatisfy({ $0.isLetter || $0.isNumber || $0 == "+" || $0 == "." || $0 == "-" }),
              !value.contains("://") else {
            return false
        }
        return !value.contains("/../") && !value.hasSuffix("/..")
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.allSatisfy {
            $0.isNumber || ("a"..."f").contains(String($0))
        }
    }
}

enum ResearchJournalError: LocalizedError {
    case missingReference
    case workspaceAccessRequired
    case invalidSize
    case hashMismatch
    case historyIncomplete
    case invalidContract

    var errorDescription: String? {
        switch self {
        case .missingReference:
            return "该研究记录尚无完整中文报告。"
        case .workspaceAccessRequired:
            return "请先在“设置 → 个人工作区”中选择当前用户目录，授权 FTClient 读取中文研究报告。"
        case .invalidSize:
            return "研究报告超出本地安全读取上限。"
        case .hashMismatch:
            return "研究报告完整性校验失败。"
        case .historyIncomplete:
            return "研究报告未能从可信起点连续重建，需要从根起点重新研究。"
        case .invalidContract:
            return "研究报告格式不受支持。"
        }
    }
}
