import CryptoKit
import Darwin
import Foundation

struct ResearchJournalDocument: Decodable {
    let schemaVersion: Int
    let language: String
    let branchID: String
    let checkpoints: [ResearchJournalCheckpoint]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case language
        case branchID = "branch_id"
        case checkpoints
    }
}

struct ResearchJournalCheckpoint: Decodable, Identifiable {
    let checkpointRef: String
    let createdAt: Double
    let carrierHash: String
    let narrativeHash: String
    let sectionHash: String
    let sections: [ResearchJournalSection]

    var id: String { checkpointRef }

    enum CodingKeys: String, CodingKey {
        case checkpointRef = "checkpoint_ref"
        case createdAt = "created_at"
        case carrierHash = "carrier_hash"
        case narrativeHash = "narrative_hash"
        case sectionHash = "section_hash"
        case sections
    }
}

struct ResearchJournalSection: Decodable, Identifiable {
    let sectionID: String
    let title: String
    let body: String
    let links: [ResearchJournalLink]
    let checkpointRef: String
    let createdAt: Double

    var id: String { "\(checkpointRef)|\(sectionID)" }

    enum CodingKeys: String, CodingKey {
        case sectionID = "section_id"
        case title, body, links
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sectionID = try container.decode(String.self, forKey: .sectionID)
        title = try container.decode(String.self, forKey: .title)
        body = try container.decode(String.self, forKey: .body)
        links = try container.decode([ResearchJournalLink].self, forKey: .links)
        checkpointRef = ""
        createdAt = 0
    }

    init(
        sectionID: String,
        title: String,
        body: String,
        links: [ResearchJournalLink],
        checkpointRef: String,
        createdAt: Double
    ) {
        self.sectionID = sectionID
        self.title = title
        self.body = body
        self.links = links
        self.checkpointRef = checkpointRef
        self.createdAt = createdAt
    }

    func bound(to checkpoint: ResearchJournalCheckpoint) -> Self {
        Self(
            sectionID: sectionID,
            title: title,
            body: body,
            links: links,
            checkpointRef: checkpoint.checkpointRef,
            createdAt: checkpoint.createdAt
        )
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
        guard value.schemaVersion == 1,
              value.language == "zh-Hans",
              !value.branchID.isEmpty,
              value.checkpoints.count <= maximumCheckpoints else {
            throw ResearchJournalError.invalidContract
        }
        var checkpointRefs = Set<String>()
        var sectionIDs = Set<String>()
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
            for section in checkpoint.sections {
                guard !section.sectionID.isEmpty,
                      !section.title.isEmpty,
                      !section.body.isEmpty,
                      section.links.count <= 16,
                      sectionIDs.insert(
                        "\(checkpoint.checkpointRef)|\(section.sectionID)"
                      ).inserted else {
                    throw ResearchJournalError.invalidContract
                }
            }
        }
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
        case .invalidContract:
            return "研究报告格式不受支持。"
        }
    }
}
