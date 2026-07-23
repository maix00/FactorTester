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
        let checkpoints = Dictionary(
            uniqueKeysWithValues: document.checkpoints.map {
                ($0.checkpointRef, $0)
            }
        )
        var result: [ResearchJournalSection] = []
        var fingerprintIndexes: [String: Int] = [:]
        for section in verified {
            let displayCheckpointRef = displayCheckpointRef(
                for: section.checkpointRef,
                checkpoints: checkpoints,
                pureMigrationRefs: pureMigrationRefs
            )
            let projected = sectionWithReadableTitle(
                section,
                checkpointRef: displayCheckpointRef,
                displayKind: pureMigrationRefs.contains(section.checkpointRef)
                    ? "graph_continuation" : "research"
            )
            let fingerprint = "\(displayCheckpointRef)|"
                + contentFingerprint(section)
            if let index = fingerprintIndexes[fingerprint] {
                result[index] = sectionWithMergedLinks(
                    result[index],
                    projected.links
                )
                continue
            }
            fingerprintIndexes[fingerprint] = result.count
            result.append(projected)
        }
        return result
    }

    /// Report-only checkpoints are immutable audit events, not graph nodes.
    /// Their prose is displayed as a subsection of the nearest substantive
    /// graph checkpoint. Pure graph migration events are skipped as well.
    private static func displayCheckpointRef(
        for checkpointRef: String,
        checkpoints: [String: ResearchJournalCheckpoint],
        pureMigrationRefs: Set<String>
    ) -> String {
        var candidate = checkpointRef
        var visited = Set<String>()
        while visited.insert(candidate).inserted,
              let checkpoint = checkpoints[candidate],
              candidate.hasPrefix("report-checkpoint:")
                || pureMigrationRefs.contains(candidate),
              let predecessor = checkpoint.predecessorCheckpointRef,
              !predecessor.isEmpty {
            candidate = predecessor
        }
        return candidate
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
        return section.body + "\u{1d}" + blocks
    }

    private static func sectionWithReadableTitle(
        _ section: ResearchJournalSection,
        checkpointRef: String,
        displayKind: String
    ) -> ResearchJournalSection {
        var title = section.title
        if section.title.range(
            of: #"^当前节点报告项\s+\d+$"#,
            options: .regularExpression
        ) != nil {
            let bindingTitle = section.blocks.lazy.compactMap {
                $0.reportBinding?.reportRequirementID
            }.first.flatMap(ResearchDisplayText.reportRequirement)
            let firstText = section.blocks.lazy.compactMap { block in
                block.rows.first?.text ?? block.text ?? block.fallback
            }.first
            title = bindingTitle ?? readableTitle(from: firstText)
                ?? "研究记录"
        }
        return ResearchJournalSection(
            sectionID: section.sectionID,
            sectionRef: section.sectionRef,
            title: title,
            body: section.body,
            blocks: section.blocks,
            links: section.links,
            checkpointRef: checkpointRef,
            auditCheckpointRef: section.auditCheckpointRef,
            createdAt: section.createdAt,
            graphRef: section.graphRef,
            branchRef: section.branchRef,
            researchOccurredAt: section.researchOccurredAt,
            timeBasis: section.timeBasis,
            timeSourceRefs: section.timeSourceRefs,
            displayKind: displayKind
        )
    }

    private static func readableTitle(from value: String?) -> String? {
        guard var title = value?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !title.isEmpty else { return nil }
        for separator in ["。", "；", "："] {
            title = title.components(separatedBy: separator)[0]
        }
        if title.count > 44 {
            title = String(title.prefix(43)).trimmingCharacters(
                in: .whitespacesAndNewlines
            ) + "…"
        }
        return title
    }

    private static func sectionWithMergedLinks(
        _ section: ResearchJournalSection,
        _ additional: [ResearchJournalLink]
    ) -> ResearchJournalSection {
        let links = (section.links + additional).reduce(
            into: [ResearchJournalLink]()
        ) { result, link in
            if !result.contains(where: { $0.linkID == link.linkID }) {
                result.append(link)
            }
        }
        return ResearchJournalSection(
            sectionID: section.sectionID,
            sectionRef: section.sectionRef,
            title: section.title,
            body: section.body,
            blocks: section.blocks,
            links: links,
            checkpointRef: section.checkpointRef,
            auditCheckpointRef: section.auditCheckpointRef,
            createdAt: section.createdAt,
            graphRef: section.graphRef,
            branchRef: section.branchRef,
            researchOccurredAt: section.researchOccurredAt,
            timeBasis: section.timeBasis,
            timeSourceRefs: section.timeSourceRefs,
            displayKind: section.displayKind
        )
    }
}
