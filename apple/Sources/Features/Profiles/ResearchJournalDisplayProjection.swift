import Foundation

extension ResearchJournalPresentation {
    static func displaySections(
        in document: ResearchJournalDocument,
        indexedBy indexSections: [ResearchReportSection],
        transitions: [ResearchTransitionStep] = []
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
        let checkpointNodeAnchors = checkpointNodeAnchors(in: verified)
        for section in verified {
            let physicalDisplayRef = displayCheckpointRef(
                for: section.checkpointRef,
                checkpoints: checkpoints,
                pureMigrationRefs: pureMigrationRefs
            )
            let displayCheckpointRef = semanticCheckpointRef(
                for: section,
                transitions: transitions,
                checkpointNodeAnchors: checkpointNodeAnchors
            ) ?? physicalDisplayRef
            let projected = sectionWithReadableTitle(
                section,
                checkpointRef: displayCheckpointRef,
                displayKind: pureMigrationRefs.contains(section.checkpointRef)
                    ? "graph_continuation" : "research",
                chapterRef: section.chapterRef ?? transitions.first {
                    $0.stepRef == section.checkpointRef
                }.map { "node:\($0.toNode)" }
            )
            result.append(projected)
        }
        return result
    }

    private static func semanticCheckpointRef(
        for section: ResearchJournalSection,
        transitions: [ResearchTransitionStep],
        checkpointNodeAnchors: [String: String]
    ) -> String? {
        let reportIDs = Set(section.blocks.compactMap {
            $0.reportBinding?.reportRequirementID
        })
        guard reportIDs.count == 1, let reportID = reportIDs.first else {
            return nil
        }
        if reportID.hasPrefix("report.edge.") {
            let edgeID = String(reportID.dropFirst("report.edge.".count))
            return nearestTransition(
                transitions.filter {
                $0.edgeRef == edgeID || $0.edgeRef == "graph-edge:\(edgeID)"
                },
                at: section.createdAt
            )?.stepRef
        }
        if reportID.hasPrefix("report.node.") {
            let suffix = reportID.dropFirst("report.node.".count)
            guard let nodeID = suffix.split(separator: ".").first.map(
                String.init
            ) else { return nil }
            return nearestTransition(
                transitions.filter { $0.toNode == nodeID },
                at: section.createdAt
            )?.stepRef
        }
        guard reportID.hasPrefix("report.requirement.") else { return nil }
        let requirementID = reportID.dropFirst(
            "report.requirement.".count
        )
        guard let categoryID = requirementID.split(separator: ".").first.map(
            String.init
        ) else { return nil }

        // The authoritative graph catalog owns a requirement's home node, but
        // schema-v4 local journals currently persist only the requirement ID.
        // A category that is itself a graph node is therefore an unambiguous
        // local anchor (for example factor_semantics.*). This must precede the
        // temporal fallback because reports may be submitted after the graph
        // has already advanced to its next node.
        let categoryCandidates = transitions.filter {
            $0.toNode == categoryID
        }
        if !categoryCandidates.isEmpty {
            return nearestTransition(
                categoryCandidates,
                at: section.createdAt
            )?.stepRef
        }

        // The producer normally writes requirement rows beside the node action
        // that owns them. Use that explicit sibling binding only when the
        // physical report checkpoint names exactly one node.
        if let nodeID = checkpointNodeAnchors[section.auditCheckpointRef] {
            return nearestTransition(
                transitions.filter { $0.toNode == nodeID },
                at: section.createdAt
            )?.stepRef
        }

        // Last-resort deterministic projection for legacy/current journals
        // whose report binding does not carry the catalog anchor. Never use a
        // future transition. Ambiguous latest transitions fail closed below.
        return nearestTransition(transitions, at: section.createdAt)?.stepRef
    }

    private static func checkpointNodeAnchors(
        in sections: [ResearchJournalSection]
    ) -> [String: String] {
        var candidates: [String: Set<String>] = [:]
        for section in sections {
            for block in section.blocks {
                guard let reportID = block.reportBinding?.reportRequirementID,
                      reportID.hasPrefix("report.node.") else { continue }
                let suffix = reportID.dropFirst("report.node.".count)
                guard let nodeID = suffix.split(separator: ".").first.map(
                    String.init
                ) else { continue }
                candidates[section.auditCheckpointRef, default: []]
                    .insert(nodeID)
            }
        }
        return candidates.reduce(into: [:]) { result, item in
            guard item.value.count == 1, let nodeID = item.value.first else {
                return
            }
            result[item.key] = nodeID
        }
    }

    private static func nearestTransition(
        _ candidates: [ResearchTransitionStep],
        at timestamp: Double
    ) -> ResearchTransitionStep? {
        let eligible = candidates.filter { $0.createdAt <= timestamp }
        guard let latestTime = eligible.map(\.createdAt).max() else {
            return nil
        }
        let latest = eligible.filter { $0.createdAt == latestTime }
        guard latest.count == 1 else { return nil }
        return latest[0]
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

    private static func sectionWithReadableTitle(
        _ section: ResearchJournalSection,
        checkpointRef: String,
        displayKind: String,
        chapterRef: String?
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
                ?? L10n.text("研究记录")
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
            displayKind: displayKind,
            chapterRef: chapterRef,
            sectionRole: section.sectionRole
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

}
