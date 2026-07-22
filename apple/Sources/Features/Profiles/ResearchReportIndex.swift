import Foundation

struct ResearchReportIndexDocument: Decodable {
    let schemaVersion: Int
    let sections: [ResearchReportSection]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sections
    }
}

struct ResearchReportSection: Identifiable, Decodable {
    let id: String
    let sectionID: String
    let checkpointRef: String
    let branchRef: String
    let title: String
    let summary: String
    let links: [ResearchDeepLinkModel]

    enum CodingKeys: String, CodingKey {
        case id = "section_ref"
        case sectionID = "section_id"
        case checkpointRef = "checkpoint_ref"
        case branchRef = "branch_ref"
        case title, summary, links
    }

    init(
        id: String,
        sectionID: String = "",
        checkpointRef: String = "",
        branchRef: String = "",
        title: String,
        summary: String,
        links: [ResearchDeepLinkModel]
    ) {
        self.id = id
        self.sectionID = sectionID
        self.checkpointRef = checkpointRef
        self.branchRef = branchRef
        self.title = title
        self.summary = summary
        self.links = links
    }
}

enum ResearchReportIndex {
    private static let maximumBytes = 512 * 1024
    private static let maximumSections = 100
    private static let maximumSummaryCharacters = 1_000

    static func load(
        artifact: ResearchArtifactModel
    ) async -> [ResearchReportSection] {
        (try? await loadVerified(artifact: artifact))
            ?? fallback(artifact: artifact)
    }

    static func loadVerified(
        artifact: ResearchArtifactModel
    ) async throws -> [ResearchReportSection] {
        guard let url = URL(string: artifact.indexRef),
              url.isFileURL else {
            throw ResearchReportIndexError.missingReference
        }
        return try await Task.detached {
            guard let attributes = try FileManager.default.attributesOfItem(
                atPath: url.path
            ) as [FileAttributeKey: Any]?,
            let size = attributes[.size] as? NSNumber,
            size.intValue <= maximumBytes else {
                throw ResearchReportIndexError.invalidContract
            }
            let data = try Data(contentsOf: url)
            let document = try JSONDecoder().decode(
                ResearchReportIndexDocument.self,
                from: data
            )
            guard document.schemaVersion == 2,
                  document.sections.count <= maximumSections,
                  document.sections.allSatisfy({ section in
                      section.id.hasPrefix("report-section:")
                          && !section.sectionID.isEmpty
                          && section.checkpointRef.hasPrefix("trace:")
                          && section.branchRef.hasPrefix("graph-branch:")
                          && section.summary.count <= maximumSummaryCharacters
                          && section.links.count <= 50
                  }) else {
                throw ResearchReportIndexError.invalidContract
            }
            return document.sections
        }.value
    }

    private static func fallback(
        artifact: ResearchArtifactModel
    ) -> [ResearchReportSection] {
        Dictionary(grouping: artifact.sectionRefs) { $0.sectionRef }
            .sorted { $0.key < $1.key }
            .prefix(maximumSections)
            .map { reference, links in
                ResearchReportSection(
                    id: reference,
                    title: reference,
                    summary: L10n.text(
                        "Legacy report section summary is unavailable."
                    ),
                    links: Array(links.prefix(50))
                )
            }
    }
}

enum ResearchReportIndexError: LocalizedError {
    case missingReference
    case invalidContract

    var errorDescription: String? {
        switch self {
        case .missingReference: return "研究报告索引不存在。"
        case .invalidContract: return "研究报告索引缺少章节与检查点的稳定映射。"
        }
    }
}
