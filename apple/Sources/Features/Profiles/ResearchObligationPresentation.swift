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
    static func readableObligationQuestion(_ value: String?) -> String {
        chineseText(value) ?? "义务描述缺失"
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
