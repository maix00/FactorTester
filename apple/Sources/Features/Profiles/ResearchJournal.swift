import CryptoKit
import Darwin
import Foundation

struct ResearchJournalDocument: Decodable {
    let schemaVersion: Int
    let language: String
    let branchID: String
    let historyStatus: String?
    let rootCheckpointRef: String?
    let checkpoints: [ResearchJournalCheckpoint]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case language
        case branchID = "branch_id"
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
    let lineageStatus: String?
    let predecessorCheckpointRef: String?
    let sections: [ResearchJournalSection]

    var id: String { checkpointRef }

    enum CodingKeys: String, CodingKey {
        case checkpointRef = "checkpoint_ref"
        case createdAt = "created_at"
        case carrierHash = "carrier_hash"
        case narrativeHash = "narrative_hash"
        case sectionHash = "section_hash"
        case lineageStatus = "lineage_status"
        case predecessorCheckpointRef = "predecessor_checkpoint_ref"
        case sections
    }
}

struct ResearchJournalSection: Decodable, Identifiable {
    let sectionID: String
    let title: String
    let body: String
    let blocks: [ResearchJournalBlock]
    let links: [ResearchJournalLink]
    let checkpointRef: String
    let createdAt: Double

    var id: String { "\(checkpointRef)|\(sectionID)" }

    enum CodingKeys: String, CodingKey {
        case sectionID = "section_id"
        case title, body, blocks, links
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
        checkpointRef = ""
        createdAt = 0
    }

    init(
        sectionID: String,
        title: String,
        body: String,
        blocks: [ResearchJournalBlock],
        links: [ResearchJournalLink],
        checkpointRef: String,
        createdAt: Double
    ) {
        self.sectionID = sectionID
        self.title = title
        self.body = body
        self.blocks = blocks
        self.links = links
        self.checkpointRef = checkpointRef
        self.createdAt = createdAt
    }

    func bound(to checkpoint: ResearchJournalCheckpoint) -> Self {
        Self(
            sectionID: sectionID,
            title: title,
            body: body,
            blocks: blocks,
            links: links,
            checkpointRef: checkpoint.checkpointRef,
            createdAt: checkpoint.createdAt
        )
    }
}

struct ResearchJournalBlock: Decodable {
    let kind: String
    let text: String?
    let linkIDs: [String]
    let columns: [String]
    let rows: [ResearchJournalRow]

    enum CodingKeys: String, CodingKey {
        case kind, text, columns, rows
        case linkIDs = "link_ids"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try container.decode(String.self, forKey: .kind)
        text = try container.decodeIfPresent(String.self, forKey: .text)
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

    var id: String { linkID }

    enum CodingKeys: String, CodingKey {
        case linkID = "link_id"
        case kind
        case targetRef = "target_ref"
    }
}

enum ResearchJournalLoader {
    static let maximumBytes = 4 * 1024 * 1024
    static let maximumCheckpoints = 4_096
    private static let linkKinds: Set<String> = [
        "checkpoint", "trial_plan", "obligation", "claim", "evidence",
        "job", "run", "delta", "report_section",
    ]

    static func load(
        artifact: ResearchArtifactModel
    ) async throws -> ResearchJournalDocument {
        guard let url = URL(string: artifact.journalRef), url.isFileURL else {
            throw ResearchJournalError.missingReference
        }
        let expectedHash = artifact.journalHash
        return try await Task.detached {
            let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                try readBoundedRegularFile(url)
            }
            guard sha256(data) == expectedHash else {
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
        in document: ResearchJournalDocument
    ) -> [ResearchJournalSection] {
        document.checkpoints.flatMap { checkpoint in
            checkpoint.sections.map { $0.bound(to: checkpoint) }
        }
    }

    private static func validate(_ value: ResearchJournalDocument) throws {
        guard value.schemaVersion == 3,
              value.historyStatus == "complete",
              !value.checkpoints.isEmpty,
              value.rootCheckpointRef
                == value.checkpoints.first?.checkpointRef else {
            throw ResearchJournalError.historyIncomplete
        }
        guard value.language == "zh-Hans",
              !value.branchID.isEmpty,
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
                  !checkpoint.sections.isEmpty,
                  checkpoint.sections.count <= 8 else {
                throw ResearchJournalError.invalidContract
            }
            if let previousCheckpoint {
                guard checkpoint.lineageStatus == "linked",
                      checkpoint.predecessorCheckpointRef
                        == previousCheckpoint.checkpointRef,
                      checkpoint.createdAt >= previousCheckpoint.createdAt else {
                    throw ResearchJournalError.historyIncomplete
                }
            } else {
                guard checkpoint.lineageStatus == "root",
                      checkpoint.predecessorCheckpointRef == "" else {
                    throw ResearchJournalError.historyIncomplete
                }
            }
            for section in checkpoint.sections {
                guard !section.sectionID.isEmpty,
                      !section.title.isEmpty,
                      (!section.body.isEmpty || !section.blocks.isEmpty),
                      section.links.count <= 16,
                      sectionIDs.insert(
                        "\(checkpoint.checkpointRef)|\(section.sectionID)"
                    ).inserted else {
                    throw ResearchJournalError.invalidContract
                }
                try validateLinks(section.links)
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
        var usedLinkIDs = Set<String>()
        for block in section.blocks {
            switch block.kind {
            case "paragraph":
                guard let text = block.text, !text.isEmpty,
                      block.columns.isEmpty, block.rows.isEmpty,
                      Set(block.linkIDs).isSubset(of: linkIDs) else {
                    throw ResearchJournalError.invalidContract
                }
                usedLinkIDs.formUnion(block.linkIDs)
            case "list":
                guard block.text == nil, block.columns.isEmpty,
                      !block.rows.isEmpty, block.rows.count <= 64 else {
                    throw ResearchJournalError.invalidContract
                }
                for row in block.rows {
                    guard let text = row.text, !text.isEmpty,
                          row.cells.isEmpty,
                          !row.linkIDs.isEmpty,
                          Set(row.linkIDs).isSubset(of: linkIDs) else {
                        throw ResearchJournalError.invalidContract
                    }
                    usedLinkIDs.formUnion(row.linkIDs)
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
                          !row.linkIDs.isEmpty,
                          Set(row.linkIDs).isSubset(of: linkIDs) else {
                        throw ResearchJournalError.invalidContract
                    }
                    usedLinkIDs.formUnion(row.linkIDs)
                }
            default:
                throw ResearchJournalError.invalidContract
            }
        }
        if !section.blocks.isEmpty && usedLinkIDs != linkIDs {
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
