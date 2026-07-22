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

extension ResearchJournalPresentation {
    static func obligationRows(
        links: [ResearchJournalLink],
        checkpointObligationRefs: [String]? = nil,
        aliases: [String: String] = [:],
        obligations: [ResearchObligationProjection],
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
                label: aliases[objectID]
            )
            let obligation = obligations.first {
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
                question: chineseText(link.label)
                    ?? aliases[objectID].flatMap(chineseText)
                    ?? obligation.flatMap {
                        chineseText($0.questionSummary)
                    }
                    ?? "该检查点尚未提供中文义务说明",
                materiality: materialityLabel(obligation?.materiality),
                change: change.map {
                    "\(statusLabel($0.fromState)) → \(statusLabel($0.toState))"
                } ?? "本步骤未变化",
                currentStatus: statusLabel(
                    statusOverrides[objectID]
                        ?? change?.toState
                        ?? obligation?.status
                        ?? "unknown"
                )
            )
        }
    }

    static func obligationAliases(
        sections: [ResearchJournalSection]
    ) -> [String: String] {
        var result: [String: String] = [:]
        for section in sections.sorted(by: sectionChronology) {
            for link in section.links where link.kind == "obligation" {
                guard let label = chineseText(link.label) else { continue }
                result[obligationObjectID(link.targetRef)] = label
            }
        }
        return result
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

private func obligationObjectID(_ reference: String) -> String {
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

private func sectionChronology(
    _ lhs: ResearchJournalSection,
    _ rhs: ResearchJournalSection
) -> Bool {
    if lhs.createdAt != rhs.createdAt { return lhs.createdAt < rhs.createdAt }
    return lhs.id < rhs.id
}
