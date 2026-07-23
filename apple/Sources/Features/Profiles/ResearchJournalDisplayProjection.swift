import Foundation

extension ResearchJournalPresentation {
    static func displaySections(
        in document: ResearchJournalDocument,
        indexedBy indexSections: [ResearchReportSection]
    ) throws -> [ResearchJournalSection] {
        let verified = try ResearchJournalLoader.sections(
            in: document,
            indexedBy: indexSections
        )
        let pureMigrationRefs = Set(document.checkpoints.compactMap {
            checkpoint -> String? in
            guard checkpoint.lineageRelation == "graph_continuation",
                  checkpoint.sections.allSatisfy(isPureMigrationSection)
            else { return nil }
            return checkpoint.checkpointRef
        })
        var result: [ResearchJournalSection] = []
        var fingerprints = Set<String>()
        for section in verified where !pureMigrationRefs.contains(
            section.checkpointRef
        ) {
            let fingerprint = "\(section.checkpointRef)|"
                + contentFingerprint(section)
            guard fingerprints.insert(fingerprint).inserted else { continue }
            result.append(sectionWithReadableTitle(section))
        }
        return result
    }

    private static func isPureMigrationSection(
        _ section: ResearchJournalSection
    ) -> Bool {
        guard section.blocks.allSatisfy({ $0.reportBinding == nil }) else {
            return false
        }
        let identity = "\(section.sectionID) \(section.title)".lowercased()
        return identity.contains("graph-continuation")
            || identity.contains("graph-v8-continuation")
            || identity.contains("研究图切换")
    }

    private static func contentFingerprint(
        _ section: ResearchJournalSection
    ) -> String {
        let blocks = section.blocks.map { block in
            [
                block.kind,
                block.text ?? "",
                block.latex ?? "",
                block.fallback ?? "",
                block.rows.map {
                    ($0.text ?? "") + "|" + $0.cells.joined(separator: "|")
                }.joined(separator: "\n"),
            ].joined(separator: "\u{1f}")
        }.joined(separator: "\u{1e}")
        let links = section.links.map {
            "\($0.linkID)|\($0.kind)|\($0.targetRef)|\($0.label ?? "")"
        }.joined(separator: "\u{1c}")
        return section.body + "\u{1d}" + blocks + "\u{1b}" + links
    }

    private static func sectionWithReadableTitle(
        _ section: ResearchJournalSection
    ) -> ResearchJournalSection {
        guard section.title.range(
            of: #"^当前节点报告项\s+\d+$"#,
            options: .regularExpression
        ) != nil else { return section }
        let firstText = section.blocks.lazy.compactMap { block in
            block.rows.first?.text ?? block.text ?? block.fallback
        }.first
        guard var title = firstText?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !title.isEmpty else { return section }
        for separator in ["。", "；", "："] {
            title = title.components(separatedBy: separator)[0]
        }
        if title.count > 44 {
            title = String(title.prefix(43)).trimmingCharacters(
                in: .whitespacesAndNewlines
            ) + "…"
        }
        return ResearchJournalSection(
            sectionID: section.sectionID,
            sectionRef: section.sectionRef,
            title: title,
            body: section.body,
            blocks: section.blocks,
            links: section.links,
            checkpointRef: section.checkpointRef,
            createdAt: section.createdAt,
            graphRef: section.graphRef,
            branchRef: section.branchRef,
            researchOccurredAt: section.researchOccurredAt,
            timeBasis: section.timeBasis,
            timeSourceRefs: section.timeSourceRefs
        )
    }
}
