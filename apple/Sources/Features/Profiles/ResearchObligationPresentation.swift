import Foundation

struct ResearchObligationTableRow: Identifiable {
    let obligationLink: ResearchJournalLink
    let deltaLink: ResearchJournalLink?
    let question: String
    let materiality: String
    let change: String
    let currentStatus: String

    var id: String { obligationLink.id }
}

struct ResearchStageObligationRows {
    let active: [ResearchObligationTableRow]
    let inherited: [ResearchObligationTableRow]
}

extension ResearchJournalPresentation {
    static func chapterStartIndexes(
        _ sections: [ResearchJournalSection]
    ) -> Set<Int> {
        var seen = Set<String>()
        return Set(sections.indices.filter {
            seen.insert(chapterRef(for: sections[$0])).inserted
        })
    }

    static func auditCheckpointStartIndexes(
        _ sections: [ResearchJournalSection]
    ) -> Set<Int> {
        var seen = Set<String>()
        return Set(sections.indices.filter {
            seen.insert(sections[$0].auditCheckpointRef).inserted
        })
    }

    static func obligationChangeOwners(
        _ sections: [ResearchJournalSection]
    ) -> [String: Set<String>] {
        var claimed = Set<String>()
        var result: [String: Set<String>] = [:]
        for section in sections {
            for obligationID in boundObligationIDs(in: section) {
                let identity = "\(section.auditCheckpointRef)|\(obligationID)"
                guard claimed.insert(identity).inserted else { continue }
                result[section.sectionRef, default: []].insert(obligationID)
            }
        }
        return result
    }

    static func chapterRef(for section: ResearchJournalSection) -> String {
        if let value = section.chapterRef, value.hasPrefix("node:") {
            return value
        }
        for block in section.blocks {
            guard let binding = block.reportBinding else { continue }
            if binding.subjectRef.hasPrefix("node:") {
                return binding.subjectRef
            }
            if binding.reportRequirementID.hasPrefix("report.node.") {
                let suffix = binding.reportRequirementID.dropFirst(
                    "report.node.".count
                )
                if let nodeID = suffix.split(separator: ".").first {
                    return "node:\(nodeID)"
                }
            }
            if binding.reportRequirementID.hasPrefix("report.edge.") {
                let edgeID = binding.reportRequirementID.dropFirst(
                    "report.edge.".count
                )
                if let source = edgeID.split(separator: "__").first {
                    return "node:\(source)"
                }
            }
            if binding.reportRequirementID.hasPrefix("report.requirement.") {
                let requirement = binding.reportRequirementID.dropFirst(
                    "report.requirement.".count
                )
                if let category = requirement.split(separator: ".").first,
                   let node = legacyRequirementHomeNodes[String(category)] {
                    return "node:\(node)"
                }
            }
        }
        return "checkpoint:\(section.checkpointRef)"
    }

    static func boundObligationIDs(
        in section: ResearchJournalSection
    ) -> Set<String> {
        Set(section.blocks.compactMap { block in
            guard let subject = block.reportBinding?.subjectRef,
                  subject.hasPrefix("obligation:") else { return nil }
            return obligationObjectID(subject)
        })
    }

    /// A report carrier is not a Research Cycle state. Select the immutable
    /// transition snapshot that existed when the section was recorded, while
    /// keeping the section's semantic chapter and physical audit checkpoint
    /// as separate identities.
    static func obligationSnapshotStep(
        for section: ResearchJournalSection,
        steps: [ResearchTransitionStep]
    ) -> ResearchTransitionStep? {
        let eligible = steps.filter { $0.createdAt <= section.createdAt }
        guard let latestTime = eligible.map(\.createdAt).max() else {
            return nil
        }
        let latest = eligible.filter { $0.createdAt == latestTime }
        guard latest.count == 1 else { return nil }
        return latest[0]
    }

    static func readableObligationQuestion(_ value: String?) -> String {
        chineseText(value) ?? L10n.text("义务描述缺失")
    }

    static func stageObligationRows(
        rows: [ResearchObligationTableRow],
        currentRefs: [String],
        previousRefs: [String]?,
        changes: [ResearchStateChange]
    ) -> ResearchStageObligationRows {
        guard let previousRefs else {
            return ResearchStageObligationRows(active: rows, inherited: [])
        }
        let previous = Set(previousRefs.map(obligationObjectID))
        let changed = Set(changes.map { obligationObjectID($0.objectID) })
        let activeIDs = Set(currentRefs.map(obligationObjectID).filter {
            !previous.contains($0)
        }).union(changed)
        var active: [ResearchObligationTableRow] = []
        var inherited: [ResearchObligationTableRow] = []
        for row in rows {
            let objectID = obligationObjectID(row.obligationLink.targetRef)
            if activeIDs.contains(objectID) {
                active.append(row)
            } else {
                inherited.append(row)
            }
        }
        return ResearchStageObligationRows(
            active: active,
            inherited: inherited
        )
    }

    static func obligationRows(
        links: [ResearchJournalLink],
        checkpointObligationRefs: [String]? = nil,
        obligations: [ResearchObligationProjection],
        obligationPresentations: [ResearchObligationPresentation] = [],
        changes: [ResearchStateChange],
        statusOverrides: [String: String] = [:]
    ) -> [ResearchObligationTableRow] {
        let linkedObligations = links.filter { $0.kind == "obligation" }
        let linkByObjectID = Dictionary(
            linkedObligations.map { (obligationObjectID($0.targetRef), $0) },
            uniquingKeysWith: { first, _ in first }
        )
        let references = checkpointObligationRefs
            ?? linkedObligations.map(\.targetRef)

        return references.map { reference in
            let objectID = obligationObjectID(reference)
            let link = linkByObjectID[objectID] ?? ResearchJournalLink(
                linkID: "checkpoint-obligation|\(objectID)",
                kind: "obligation",
                targetRef: reference,
                label: nil
            )
            let obligation = obligations.first {
                obligationObjectID($0.obligationRef) == objectID
            }
            let presentation = obligationPresentations.first {
                obligationObjectID($0.obligationRef) == objectID
            }
            let change = changes.first {
                obligationObjectID($0.objectID) == objectID
            }
            let delta = links.first {
                $0.kind == "delta"
                    && ($0.targetRef.hasSuffix(":" + reference)
                        || $0.targetRef.hasSuffix(":" + objectID))
            }
            return ResearchObligationTableRow(
                obligationLink: link,
                deltaLink: delta,
                question: presentation.flatMap {
                        chineseText($0.questionSummary)
                    }
                    ?? obligation.flatMap {
                        chineseText($0.questionSummary)
                    }
                    ?? readableObligationQuestion(nil),
                materiality: materialityLabel(obligation?.materiality),
                change: change.map(obligationChangeLabel)
                    ?? L10n.text("本步骤未变化"),
                currentStatus: statusLabel(
                    statusOverrides[objectID]
                        ?? change?.toState
                        ?? obligation?.status
                        ?? "unknown"
                )
            )
        }
    }

    private static func obligationChangeLabel(
        _ change: ResearchStateChange
    ) -> String {
        if change.fromState != change.toState {
            return L10n.format(
                "%@ → %@",
                L10n.text(statusLabel(change.fromState)),
                L10n.text(statusLabel(change.toState))
            )
        }
        if change.fromRequirementRefs != change.toRequirementRefs {
            return L10n.text("义务分类已更新")
        }
        return L10n.text("义务内容已更新")
    }

    static func obligationStatuses(
        at checkpointRef: String,
        steps: [ResearchTransitionStep],
        currentObligations: [ResearchObligationProjection]
    ) -> [String: String] {
        var statuses = Dictionary(
            currentObligations.map {
                (obligationObjectID($0.obligationRef), $0.status)
            },
            uniquingKeysWith: { first, _ in first }
        )
        let ordered = steps.sorted {
            if $0.createdAt != $1.createdAt {
                return $0.createdAt < $1.createdAt
            }
            return $0.stepRef < $1.stepRef
        }
        guard let targetIndex = ordered.firstIndex(where: {
            $0.stepRef == checkpointRef
        }), targetIndex + 1 < ordered.count else {
            return statuses
        }
        for step in ordered[(targetIndex + 1)...].reversed() {
            for change in step.obligationChanges.reversed() {
                let objectID = obligationObjectID(change.objectID)
                guard statuses[objectID]?.lowercased()
                        == change.toState.lowercased() else {
                    continue
                }
                statuses[objectID] = change.fromState
            }
        }
        return statuses
    }
}

private let legacyRequirementHomeNodes = [
    "hypothesis_validity": "hypothesis_preregistration",
    "data": "data_contract",
    "factor_semantics": "factor_semantics",
    "trial_design_validity": "validation_design",
    "statistical_validity": "result_audit",
    // Strategy and market-execution requirements are admitted by the
    // trial_execution packet. They belong to that chapter even when an older
    // report carrier was created while the graph still displayed
    // validation_design.
    "strategy_design": "trial_execution",
    "market_execution_accounting": "trial_execution",
    "other": "research_decision",
]

func obligationObjectID(_ reference: String) -> String {
    reference.split(separator: ":").last.map(String.init) ?? reference
}

private func chineseText(_ value: String?) -> String? {
    guard let value else { return nil }
    let text = value.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty,
          text.range(of: #"\p{Han}"#, options: .regularExpression) != nil else {
        return nil
    }
    return text
}
