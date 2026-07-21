import SwiftUI

struct ResearchCheckpointTimeline: View {
    let detail: ProfileResearchDetail
    let steps: [ResearchTransitionStep]
    let nextCursor: String?
    let profiles: [LocalProfileModel]
    let loadEarlier: () async -> Void
    @State private var sections: [ResearchReportSection] = []

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                currentStage
                Text("研究过程")
                    .font(.title2.weight(.semibold))
                    .padding(.top, 4)
                ForEach(orderedSteps) { step in
                    ResearchCheckpointCard(
                        step: step,
                        obligations: detail.researchCycle.obligations,
                        reportSections: ResearchCheckpointLinker.relatedSections(
                            to: step,
                            among: sections
                        ),
                        isCurrent: step.id == orderedSteps.last?.id
                    )
                }
                if orderedSteps.isEmpty {
                    Label("尚无已提交的研究步骤", systemImage: "clock")
                        .foregroundStyle(.secondary)
                        .padding(.vertical, 24)
                }
                if nextCursor != nil {
                    Button("加载更早步骤") {
                        Task { await loadEarlier() }
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .padding(20)
        }
        .task(id: detail.reportLookupRef) {
            sections = await loadReportSections()
        }
    }

    private var currentStage: some View {
        HStack(spacing: 14) {
            Image(systemName: "location.fill")
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text("当前阶段 · \(detail.currentNode)")
                    .font(.headline)
                HStack(spacing: 10) {
                    Text(detail.status)
                    if let trialPlanRef = detail.trialPlanRef {
                        Text(trialPlanRef).monospaced()
                    }
                    Text("\(detail.researchCycle.obligations.filter { $0.status != "discharged" }.count) 项未清义务")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(14)
        .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }

    private var orderedSteps: [ResearchTransitionStep] {
        steps.sorted {
            if $0.createdAt != $1.createdAt { return $0.createdAt < $1.createdAt }
            return $0.id < $1.id
        }
    }

    private func loadReportSections() async -> [ResearchReportSection] {
        let accepted = Set(steps.flatMap { Array($0.allRefs) } + [detail.reportLookupRef].compactMap { $0 })
        let artifacts = profiles.flatMap(\.researchRecords)
            .filter { record in
                accepted.contains(record.id)
                    || record.timeline.contains { accepted.contains($0.targetRef) }
                    || record.artifacts.contains { artifact in
                        artifact.sectionRefs.contains { accepted.contains($0.targetRef) }
                    }
            }
            .flatMap(\.artifacts)
        return await withTaskGroup(of: [ResearchReportSection].self) { group in
            for artifact in artifacts.prefix(20) {
                group.addTask { await ResearchReportIndex.load(artifact: artifact) }
            }
            var result: [ResearchReportSection] = []
            for await values in group { result.append(contentsOf: values) }
            return Array(result.prefix(100))
        }
    }
}

private struct ResearchCheckpointCard: View {
    let step: ResearchTransitionStep
    let obligations: [ResearchObligationProjection]
    let reportSections: [ResearchReportSection]
    let isCurrent: Bool
    @State private var expanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 14) {
                referenceGroup("Trial Plan", refs: step.trialPlanRefs)
                obligationGroup
                referenceGroup("Evidence", refs: step.evidenceRefs)
                changeGroup("证据状态变化", values: step.claimChanges)
                referenceGroup("Claims", refs: step.claimRefs)
                referenceGroup("Jobs / Runs", refs: step.jobRefs + step.runRefs)
                reportGroup
            }
            .padding(.top, 12)
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: isCurrent ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(
                        isCurrent ? Color.accentColor : Color.secondary
                    )
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text("\(step.fromNode) → \(step.toNode)")
                            .font(.headline)
                        if isCurrent {
                            Text("当前").font(.caption.weight(.semibold))
                                .foregroundStyle(.tint)
                        }
                    }
                    Text(Date(timeIntervalSince1970: step.createdAt), style: .date)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(step.edgeRef)
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        .overlay {
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(
                    isCurrent
                        ? Color.accentColor.opacity(0.35)
                        : Color.secondary.opacity(0.22),
                    lineWidth: 0.7
                )
        }
    }

    private var obligationGroup: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("义务与变化").font(.subheadline.weight(.semibold))
            ForEach(step.obligationRefs, id: \.self) { reference in
                let current = obligations.first { $0.obligationRef == reference }
                VStack(alignment: .leading, spacing: 2) {
                    Text(reference).font(.caption.monospaced())
                    if let current {
                        Text("\(current.questionSummary) · 当前为 \(current.status)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            changeGroup("义务变化", values: step.obligationChanges)
            if step.obligationRefs.isEmpty && step.obligationChanges.isEmpty {
                Text("本步骤没有义务变更").font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var reportGroup: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("报告").font(.subheadline.weight(.semibold))
            if reportSections.isEmpty {
                Text("尚无与本 checkpoint 对应的报告章节")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(reportSections) { section in
                GroupBox(section.title) {
                    Text(section.summary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .font(.caption)
                        .textSelection(.enabled)
                }
            }
        }
    }

    @ViewBuilder
    private func referenceGroup(_ title: String, refs: [String]) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.subheadline.weight(.semibold))
            if refs.isEmpty {
                Text("无").font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(refs, id: \.self) { ref in
                    Text(ref).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
        }
    }

    @ViewBuilder
    private func changeGroup(_ title: String, values: [ResearchStateChange]) -> some View {
        if !values.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.subheadline.weight(.semibold))
                ForEach(values) { change in
                    Text("\(change.objectID)：\(change.fromState) → \(change.toState)")
                        .font(.caption)
                }
            }
        }
    }
}

enum ResearchCheckpointLinker {
    static func relatedSections(
        to step: ResearchTransitionStep,
        among sections: [ResearchReportSection]
    ) -> [ResearchReportSection] {
        sections.filter { section in
            section.links.contains { step.allRefs.contains($0.targetRef) }
        }
    }
}

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
                    Button { select(step.allRefs) } label: {
                        stepCard(step)
                    }
                    .buttonStyle(.plain)
                }
                if nextCursor != nil {
                    Button("加载更早步骤") {
                        Task { await loadEarlier() }
                    }
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
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text("\(step.fromNode) → \(step.toNode)")
                .font(.callout)
                .foregroundStyle(.secondary)
            changes(step.obligationChanges, title: "义务变化")
            changes(step.claimChanges, title: "证据状态变化")
            if !step.evidenceRefs.isEmpty {
                Text(orderedRefs(step).joined(separator: " · "))
                    .font(.caption.monospaced())
                    .foregroundStyle(.tertiary)
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
    private func changes(
        _ values: [ResearchStateChange],
        title: String
    ) -> some View {
        ForEach(values) { change in
            Text(
                "\(title)：\(change.objectID) "
                    + "\(change.fromState) → \(change.toState)"
            )
            .font(.caption)
        }
    }
}
