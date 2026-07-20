import SwiftUI

struct LiveResearchOverview: View {
    let detail: ProfileResearchDetail

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(detail.label).font(.title2.weight(.semibold))
                        Text(detail.currentNode)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(detail.status)
                        .font(.callout.weight(.semibold))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(.quaternary, in: Capsule())
                }
                if let trial = detail.trialPlanRef {
                    ReferenceGroup(title: "Trial Plan", refs: [trial])
                }
                ReferenceGroup(
                    title: "Evidence",
                    refs: detail.evidenceRefs,
                    omitted: detail.omittedEvidenceCount
                )
                ReferenceGroup(title: "Jobs", refs: detail.jobRefs)
                ReferenceGroup(title: "Runs", refs: detail.runRefs)
                if let report = detail.reportLookupRef {
                    ReferenceGroup(title: "Report lookup", refs: [report])
                }
                if let closure = detail.researchCycle.closure {
                    GroupBox("研究关闭状态") {
                        LabeledContent(
                            "Disposition",
                            value: closure.disposition
                        )
                        .padding(8)
                    }
                }
            }
            .padding(20)
        }
    }
}

struct ReferenceGroup: View {
    let title: String
    let refs: [String]
    var omitted = 0

    var body: some View {
        GroupBox(title) {
            VStack(alignment: .leading, spacing: 6) {
                if refs.isEmpty {
                    Text("无").foregroundStyle(.secondary)
                }
                ForEach(refs, id: \.self) { ref in
                    Text(ref)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                if omitted > 0 {
                    Text("另有 \(omitted) 项未载入")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(8)
        }
    }
}
