import SwiftUI

struct ProfileLiveTimeline: View {
    let steps: [ResearchTransitionStep]
    let nextCursor: String?
    var highlightedRefs: Set<String> = []
    let select: (Set<String>) -> Void
    let loadEarlier: () async -> Void

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                ForEach(steps) { step in
                    Button { select(step.allRefs) } label: { stepCard(step) }
                        .buttonStyle(.plain)
                }
                if nextCursor != nil {
                    Button("加载更早步骤") { Task { await loadEarlier() } }
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(20)
        }
    }

    private func stepCard(_ step: ResearchTransitionStep) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(step.toNode, systemImage: "arrow.triangle.branch")
                    .font(.headline)
                Spacer()
                Text(Date(timeIntervalSince1970: step.createdAt), style: .time)
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text(verbatim: L10n.format("%@ → %@", step.fromNode, step.toNode))
                .font(.callout).foregroundStyle(.secondary)
            changes(step.obligationChanges, title: "义务变化")
            changes(step.claimChanges, title: "证据状态变化")
            if !step.evidenceRefs.isEmpty {
                Text(orderedRefs(step).joined(separator: " · "))
                    .font(.caption.monospaced()).foregroundStyle(.tertiary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(
            highlightedRefs.isDisjoint(with: step.allRefs)
                ? Color.clear : Color.accentColor.opacity(0.09),
            in: RoundedRectangle(cornerRadius: 10)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.separator, lineWidth: 0.5)
        }
    }

    private func orderedRefs(_ step: ResearchTransitionStep) -> [String] {
        step.trialPlanRefs + step.obligationRefs + step.claimRefs
            + step.evidenceRefs + step.jobRefs + step.runRefs
    }

    @ViewBuilder
    private func changes(_ values: [ResearchStateChange], title: String) -> some View {
        ForEach(values) { change in
            Text(verbatim: L10n.format(
                "%@: %@ %@ → %@", title, change.objectID,
                change.fromState, change.toState
            )).font(.caption)
        }
    }
}
