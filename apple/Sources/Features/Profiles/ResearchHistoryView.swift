import SwiftUI

struct ResearchHistoryView: View {
    let profile: LocalProfileModel
    @State private var selectedRecord: String?

    var body: some View {
        GroupBox("Research History / Reports") {
            if profile.researchRecords.isEmpty {
                Text("No indexed research records")
                    .foregroundStyle(.secondary)
                    .padding(8)
            } else {
                HSplitView {
                    List(profile.researchRecords, selection: $selectedRecord) {
                        record in
                        VStack(alignment: .leading) {
                            Text(record.title)
                            HStack(spacing: 6) {
                                Text(verbatim: ProfilePresentationText.artifactStatus(record.status))
                                    .font(.caption2.weight(.semibold))
                                    .foregroundStyle(
                                        record.status == "ready"
                                            ? Color.green : Color.secondary
                                    )
                                Text(record.agentID)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                        .tag(record.id)
                    }
                    .frame(minWidth: 180)
                    if let record = selected { ResearchRecordSummaryView(record: record) }
                }
                .frame(minHeight: 180)
            }
        }
    }

    private var selected: ResearchRecordModel? {
        profile.researchRecords.first { $0.id == selectedRecord }
    }

}

private struct ResearchRecordSummaryView: View {
    let record: ResearchRecordModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(record.preferredResearchTitle).font(.title3.weight(.semibold))
                Text(record.scope).font(.caption).textSelection(.enabled)
                field(L10n.text("状态"), ProfilePresentationText.artifactStatus(record.status))
                field(L10n.text("研究员"), record.agentID)
                field(L10n.text("研究图分支"), record.graphBranchRef)
                if let artifact = record.currentReportArtifact {
                    field(L10n.text("本地报告"), artifact.localRef)
                } else {
                    Label(L10n.text("当前分支尚无报告树"),
                          systemImage: "doc.badge.ellipsis")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
        }
    }

    private func field(_ label: String, _ value: String) -> some View {
        LabeledContent(label, value: value)
            .font(.caption).textSelection(.enabled)
    }
}
