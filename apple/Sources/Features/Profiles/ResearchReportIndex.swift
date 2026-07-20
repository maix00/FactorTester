import Foundation

struct ResearchReportSection: Identifiable {
    let id: String
    let title: String
    let summary: String
    let links: [ResearchDeepLinkModel]
}

enum ResearchReportIndex {
    private static let maximumBytes = 512 * 1024
    private static let maximumSections = 100
    private static let maximumSummaryCharacters = 1_000

    static func load(
        artifact: ResearchArtifactModel
    ) async -> [ResearchReportSection] {
        guard let url = URL(string: artifact.indexRef),
              url.isFileURL else {
            return fallback(artifact: artifact)
        }
        return await Task.detached {
            guard let attributes = try? FileManager.default.attributesOfItem(
                atPath: url.path
            ),
            let size = attributes[.size] as? NSNumber,
            size.intValue <= maximumBytes,
            let data = try? Data(contentsOf: url),
            let root = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any],
            root["schema_version"] as? Int == 1,
            let values = root["sections"] as? [[String: Any]] else {
                return fallback(artifact: artifact)
            }
            return values.prefix(maximumSections).compactMap { value in
                guard let reference = value["section_ref"] as? String,
                      !reference.isEmpty else { return nil }
                let rawSummary = value["summary"] as? String ?? ""
                let links = (value["links"] as? [[String: Any]] ?? [])
                    .prefix(50)
                    .map(ResearchDeepLinkModel.init)
                return ResearchReportSection(
                    id: reference,
                    title: value["title"] as? String ?? reference,
                    summary: String(
                        rawSummary.prefix(maximumSummaryCharacters)
                    ),
                    links: links
                )
            }
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
